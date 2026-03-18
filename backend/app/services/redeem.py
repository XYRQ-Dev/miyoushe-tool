"""
兑换码批量执行服务

首版刻意把“批次编排”和“上游请求”拆开：
1. 批次、统计、历史查询属于系统内稳定能力，后续要长期复用
2. 上游兑换接口的参数与返回码更容易变化，必须限制在适配层里收口
3. 这样即使未来接入更多游戏或修正上游细节，也不会波及前端和历史数据模型
"""

import logging
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import GameRole, MihoyoAccount
from app.models.redeem import RedeemBatch, RedeemExecution
from app.schemas.redeem import (
    RedeemAccountListResponse,
    RedeemAccountOption,
    RedeemBatchDetailResponse,
    RedeemBatchListResponse,
    RedeemBatchSummaryResponse,
    RedeemExecuteRequest,
    RedeemExecutionResponse,
)
from app.utils.crypto import decrypt_cookie
from app.utils.device import generate_device_id, get_default_headers
from app.utils.ds import generate_ds_v2

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RedeemGameConfig:
    game: str
    game_name: str
    endpoint: str
    role_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class RedeemOutcome:
    status: str
    message: str
    upstream_code: int | None = None


@dataclass(frozen=True)
class PendingExecution:
    account_id: int
    game: str
    account_name: str
    role_uid: str | None
    region: str | None
    status: str
    message: str
    upstream_code: int | None = None


SUPPORTED_REDEEM_GAME_CONFIGS: tuple[RedeemGameConfig, ...] = (
    RedeemGameConfig(
        game="genshin",
        game_name="原神",
        endpoint="https://api-takumi.mihoyo.com/common/apicdkey/api/webExchangeCdkey",
        role_prefixes=("hk4e_",),
    ),
    RedeemGameConfig(
        game="starrail",
        game_name="星穹铁道",
        endpoint="https://api-takumi.mihoyo.com/common/apicdkey/api/webExchangeCdkeyHyl",
        role_prefixes=("hkrpg_",),
    ),
)


class RedeemService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_supported_accounts(self, user_id: int) -> RedeemAccountListResponse:
        result = await self.db.execute(
            select(MihoyoAccount)
            .where(MihoyoAccount.user_id == user_id)
            .order_by(MihoyoAccount.created_at.desc(), MihoyoAccount.id.desc())
        )
        accounts = result.scalars().all()
        if not accounts:
            return RedeemAccountListResponse(accounts=[], total=0)

        account_ids = [account.id for account in accounts]
        roles_result = await self.db.execute(
            select(GameRole).where(
                GameRole.account_id.in_(account_ids),
                GameRole.is_enabled.is_(True),
            )
        )
        roles_by_account: dict[int, list[GameRole]] = {}
        for role in roles_result.scalars().all():
            roles_by_account.setdefault(role.account_id, []).append(role)

        options: list[RedeemAccountOption] = []
        for account in accounts:
            roles = roles_by_account.get(account.id, [])
            supported_games = self._collect_supported_games(roles)
            if not supported_games:
                continue

            options.append(
                RedeemAccountOption(
                    id=account.id,
                    nickname=account.nickname,
                    mihoyo_uid=account.mihoyo_uid,
                    supported_games=supported_games,
                )
            )

        return RedeemAccountListResponse(accounts=options, total=len(options))

    async def execute_batch(self, *, user_id: int, request: RedeemExecuteRequest) -> RedeemBatchDetailResponse:
        config = self._get_config(request.game)
        account_ids = self._normalize_account_ids(request.account_ids)
        code = self._normalize_code(request.code)

        accounts = await self._load_owned_accounts(account_ids=account_ids, user_id=user_id)
        role_map = await self._load_redeem_roles(account_ids)

        pending_executions: list[PendingExecution] = []
        # 先把所有上游调用完成，再开启写事务落批次和明细。
        # 这是 SQLite 下非常关键的边界：如果写事务跨网络调用，整个服务会更容易出现 database is locked。
        async with httpx.AsyncClient(timeout=20) as client:
            for account_id in account_ids:
                account = accounts[account_id]
                role = role_map.get(account_id, {}).get(request.game)
                account_name = self._get_account_name(account)

                if role is None:
                    pending_executions.append(
                        PendingExecution(
                            account_id=account.id,
                            game=request.game,
                            account_name=account_name,
                            role_uid=None,
                            region=None,
                            status="unsupported_game",
                            message=f"账号未配置可用于{config.game_name}兑换的角色信息",
                        )
                    )
                    continue

                if not account.cookie_encrypted:
                    pending_executions.append(
                        PendingExecution(
                            account_id=account.id,
                            game=request.game,
                            account_name=account_name,
                            role_uid=role.game_uid,
                            region=role.region,
                            status="invalid_cookie",
                            message="登录态失效或缺少 Cookie，请先刷新登录状态后再兑换",
                        )
                    )
                    continue

                try:
                    outcome = await self._redeem_for_account(
                        client=client,
                        account=account,
                        role=role,
                        code=code,
                        config=config,
                    )
                except httpx.HTTPError:
                    logger.warning(
                        "兑换码上游请求失败: user_id=%s account_id=%s game=%s code=%s",
                        user_id,
                        account.id,
                        request.game,
                        code,
                        exc_info=True,
                    )
                    outcome = RedeemOutcome(status="network_error", message="兑换请求失败，请稍后重试")
                except Exception:
                    logger.exception(
                        "兑换码执行异常: user_id=%s account_id=%s game=%s code=%s",
                        user_id,
                        account.id,
                        request.game,
                        code,
                    )
                    outcome = RedeemOutcome(status="error", message="兑换执行异常，请稍后重试")

                pending_executions.append(
                    PendingExecution(
                        account_id=account.id,
                        game=request.game,
                        account_name=account_name,
                        role_uid=role.game_uid,
                        region=role.region,
                        status=outcome.status,
                        upstream_code=outcome.upstream_code,
                        message=outcome.message,
                    )
                )

        batch = RedeemBatch(
            user_id=user_id,
            account_count=len(pending_executions),
            game=request.game,
            code=code,
            message="兑换已完成",
        )
        self.db.add(batch)
        await self.db.flush()

        executions = [
            RedeemExecution(
                batch_id=batch.id,
                account_id=item.account_id,
                game=item.game,
                account_name=item.account_name,
                role_uid=item.role_uid,
                region=item.region,
                status=item.status,
                upstream_code=item.upstream_code,
                message=item.message,
            )
            for item in pending_executions
        ]
        for execution in executions:
            self.db.add(execution)

        self._apply_batch_counters(batch, executions)
        await self.db.commit()
        await self.db.refresh(batch)

        return self._build_batch_detail(batch=batch, executions=executions)

    async def list_batches(self, *, user_id: int, game: str | None = None) -> RedeemBatchListResponse:
        conditions = [RedeemBatch.user_id == user_id]
        if game:
            self._get_config(game)
            conditions.append(RedeemBatch.game == game)

        result = await self.db.execute(
            select(RedeemBatch)
            .where(and_(*conditions))
            .order_by(RedeemBatch.created_at.desc(), RedeemBatch.id.desc())
        )
        batches = result.scalars().all()
        return RedeemBatchListResponse(
            items=[self._build_batch_summary(batch) for batch in batches],
            total=len(batches),
        )

    async def get_batch_detail(self, *, user_id: int, batch_id: int) -> RedeemBatchDetailResponse:
        result = await self.db.execute(
            select(RedeemBatch).where(
                RedeemBatch.id == batch_id,
                RedeemBatch.user_id == user_id,
            )
        )
        batch = result.scalar_one_or_none()
        if batch is None:
            raise HTTPException(status_code=404, detail="兑换批次不存在")

        execution_result = await self.db.execute(
            select(RedeemExecution)
            .where(RedeemExecution.batch_id == batch.id)
            .order_by(RedeemExecution.id.asc())
        )
        executions = execution_result.scalars().all()
        return self._build_batch_detail(batch=batch, executions=executions)

    async def _load_owned_accounts(self, *, account_ids: list[int], user_id: int) -> dict[int, MihoyoAccount]:
        result = await self.db.execute(
            select(MihoyoAccount).where(
                MihoyoAccount.id.in_(account_ids),
                MihoyoAccount.user_id == user_id,
            )
        )
        accounts = {account.id: account for account in result.scalars().all()}
        if len(accounts) != len(account_ids):
            raise HTTPException(status_code=404, detail="账号不存在")
        return accounts

    async def _load_redeem_roles(self, account_ids: list[int]) -> dict[int, dict[str, GameRole]]:
        result = await self.db.execute(
            select(GameRole)
            .where(
                GameRole.account_id.in_(account_ids),
                GameRole.is_enabled.is_(True),
            )
            .order_by(GameRole.id.asc())
        )
        role_map: dict[int, dict[str, GameRole]] = {}
        for role in result.scalars().all():
            config = self._get_config_for_role(role)
            if config is None:
                continue
            role_map.setdefault(role.account_id, {})
            role_map[role.account_id].setdefault(config.game, role)
        return role_map

    async def _redeem_for_account(
        self,
        *,
        client: httpx.AsyncClient,
        account: MihoyoAccount,
        role: GameRole,
        code: str,
        config: RedeemGameConfig,
    ) -> RedeemOutcome:
        try:
            cookie = decrypt_cookie(account.cookie_encrypted or "")
        except Exception:
            return RedeemOutcome(
                status="invalid_cookie",
                message="登录态失效或损坏，请先重新扫码或刷新登录状态",
            )

        payload = await self._execute_upstream_redeem(
            client=client,
            account=account,
            role=role,
            code=code,
            cookie=cookie,
            config=config,
        )
        return self._map_upstream_result(payload)

    async def _execute_upstream_redeem(
        self,
        *,
        client: httpx.AsyncClient,
        account: MihoyoAccount,
        role: GameRole,
        code: str,
        cookie: str,
        config: RedeemGameConfig,
    ) -> dict:
        params = {
            "uid": role.game_uid,
            "region": role.region or "",
            "lang": "zh-cn",
            "cdkey": code,
            "game_biz": role.game_biz,
            "sLangKey": "zh-cn",
        }
        query = urlencode(params)
        headers = get_default_headers(
            cookie,
            device_id=generate_device_id(),
            ds=generate_ds_v2(query=query),
        )
        headers["Referer"] = "https://user.mihoyo.com/"
        headers["Origin"] = "https://user.mihoyo.com"

        # 这里保留独立的上游调用方法，而不是把 httpx 细节散落在批次循环里，
        # 目的是让测试可以只替换这一层，稳定验证系统内的状态语义与归档行为。
        response = await client.get(config.endpoint, params=params, headers=headers)
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            # 上游偶发返回网关页或鉴权页时，症状表现为“HTTP 成功但响应不可解析”。
            # 这里必须继续按网络边界失败处理；若误归为系统异常，前端统计会把外部波动说成我们自身故障。
            raise httpx.DecodingError(
                "兑换接口返回了无法解析的响应",
                request=getattr(response, "request", None),
            ) from exc

    def _map_upstream_result(self, payload: dict) -> RedeemOutcome:
        retcode = int(payload.get("retcode", -1))
        message = str(payload.get("message") or payload.get("msg") or "").strip()
        normalized = message.lower()

        if retcode == 0:
            return RedeemOutcome(status="success", message=message or "兑换成功", upstream_code=retcode)
        if retcode in (-100, -101):
            return RedeemOutcome(
                status="invalid_cookie",
                message=message or "登录态失效，请刷新后重试",
                upstream_code=retcode,
            )
        if retcode in (-5008, -2017) or any(keyword in message for keyword in ("已使用", "已兑换", "已经兑换")):
            return RedeemOutcome(
                status="already_redeemed",
                message=message or "该兑换码已使用",
                upstream_code=retcode,
            )
        if retcode in (-2003, -2001, -1071) or any(keyword in normalized for keyword in ("invalid", "expired")):
            return RedeemOutcome(
                status="invalid_code",
                message=message or "兑换码无效或已失效",
                upstream_code=retcode,
            )
        if any(keyword in message for keyword in ("无效", "失效", "不存在")):
            return RedeemOutcome(
                status="invalid_code",
                message=message,
                upstream_code=retcode,
            )
        return RedeemOutcome(
            status="error",
            message=message or f"上游返回未知状态（code: {retcode}）",
            upstream_code=retcode,
        )

    def _apply_batch_counters(self, batch: RedeemBatch, executions: list[RedeemExecution]) -> None:
        batch.account_count = len(executions)
        batch.success_count = sum(1 for item in executions if item.status == "success")
        batch.already_redeemed_count = sum(1 for item in executions if item.status == "already_redeemed")
        batch.invalid_code_count = sum(1 for item in executions if item.status == "invalid_code")
        batch.invalid_cookie_count = sum(1 for item in executions if item.status == "invalid_cookie")
        # failed_count 只表示真正失败的账号，故意排除 already_redeemed。
        # 否则前端会把“正常的重复兑换”误渲染成异常，用户也无法从摘要里分辨风险和幂等结果。
        batch.error_count = sum(1 for item in executions if item.status in ("network_error", "error", "unsupported_game"))
        batch.failed_count = batch.invalid_code_count + batch.invalid_cookie_count + batch.error_count

    def _build_batch_summary(self, batch: RedeemBatch) -> RedeemBatchSummaryResponse:
        return RedeemBatchSummaryResponse(
            batch_id=batch.id,
            code=batch.code,
            game=batch.game,
            total_accounts=batch.account_count,
            success_count=batch.success_count,
            already_redeemed_count=batch.already_redeemed_count,
            invalid_code_count=batch.invalid_code_count,
            invalid_cookie_count=batch.invalid_cookie_count,
            error_count=batch.error_count,
            failed_count=batch.failed_count,
            message=batch.message,
            created_at=batch.created_at,
        )

    def _build_batch_detail(
        self,
        *,
        batch: RedeemBatch,
        executions: list[RedeemExecution],
    ) -> RedeemBatchDetailResponse:
        return RedeemBatchDetailResponse(
            **self._build_batch_summary(batch).model_dump(),
            executions=[
                RedeemExecutionResponse(
                    id=item.id,
                    account_id=item.account_id,
                    account_name=item.account_name,
                    game=item.game,
                    status=item.status,
                    upstream_code=item.upstream_code,
                    message=item.message,
                    executed_at=item.executed_at,
                )
                for item in executions
            ],
        )

    def _collect_supported_games(self, roles: list[GameRole]) -> list[str]:
        supported_games: list[str] = []
        for config in SUPPORTED_REDEEM_GAME_CONFIGS:
            if any(role.game_biz.startswith(config.role_prefixes) for role in roles):
                supported_games.append(config.game)
        return supported_games

    def _get_account_name(self, account: MihoyoAccount) -> str:
        return account.nickname or account.mihoyo_uid or f"账号#{account.id}"

    def _get_config(self, game: str) -> RedeemGameConfig:
        for config in SUPPORTED_REDEEM_GAME_CONFIGS:
            if config.game == game:
                return config
        raise HTTPException(status_code=400, detail="暂不支持该游戏的兑换码执行")

    def _get_config_for_role(self, role: GameRole) -> RedeemGameConfig | None:
        for config in SUPPORTED_REDEEM_GAME_CONFIGS:
            if role.game_biz.startswith(config.role_prefixes):
                return config
        return None

    def _normalize_account_ids(self, account_ids: list[int]) -> list[int]:
        normalized: list[int] = []
        for account_id in account_ids:
            if account_id not in normalized:
                normalized.append(account_id)
        if not normalized:
            raise HTTPException(status_code=400, detail="请选择至少一个目标账号")
        return normalized

    def _normalize_code(self, code: str) -> str:
        normalized = code.strip().upper()
        if len(normalized) < 3:
            raise HTTPException(status_code=400, detail="兑换码不能为空")
        return normalized


redeem_service_type = RedeemService
