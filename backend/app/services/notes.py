"""
实时便笺查询服务

首版只负责“按账号聚合可展示的实时状态”，不在查询过程中改写账号状态或引入额外缓存。
这样做的原因是：
1. 便笺面板属于读路径，用户刷新页面时不应隐式触发一连串状态迁移
2. 当前系统已有独立的登录态维护逻辑，便笺查询只需要把失败原因透明返回前端
3. 不同游戏的便笺字段差异很大，先在服务层统一成稳定展示模型，后续页面演进才不会被上游字段绑死
"""

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import GameRole, MihoyoAccount
from app.schemas.notes import (
    NoteAccountListResponse,
    NoteAccountOption,
    NoteCardResponse,
    NoteMetricResponse,
    NoteSummaryResponse,
)
from app.utils.crypto import decrypt_cookie
from app.utils.device import generate_device_id, get_default_headers
from app.utils.ds import generate_ds_v2
from app.utils.timezone import utc_now_naive


@dataclass(frozen=True)
class NoteGameConfig:
    game: str
    game_name: str
    endpoint: str
    role_prefixes: tuple[str, ...]


SUPPORTED_NOTE_GAME_CONFIGS: tuple[NoteGameConfig, ...] = (
    NoteGameConfig(
        game="genshin",
        game_name="原神",
        endpoint="https://api-takumi-record.mihoyo.com/game_record/app/genshin/api/dailyNote",
        role_prefixes=("hk4e_",),
    ),
    NoteGameConfig(
        game="starrail",
        game_name="星穹铁道",
        endpoint="https://api-takumi-record.mihoyo.com/game_record/app/hkrpg/api/note",
        role_prefixes=("hkrpg_",),
    ),
)


class NoteService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_owned_account(self, account_id: int, user_id: int) -> MihoyoAccount:
        result = await self.db.execute(
            select(MihoyoAccount).where(
                MihoyoAccount.id == account_id,
                MihoyoAccount.user_id == user_id,
            )
        )
        account = result.scalar_one_or_none()
        if account is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        return account

    async def list_supported_accounts(self, user_id: int) -> NoteAccountListResponse:
        result = await self.db.execute(
            select(MihoyoAccount).where(MihoyoAccount.user_id == user_id).order_by(MihoyoAccount.created_at.desc())
        )
        accounts = result.scalars().all()

        items: list[NoteAccountOption] = []
        for account in accounts:
            roles = await self._load_supported_roles(account.id)
            supported_games = self._collect_supported_games(roles)
            if not supported_games:
                continue

            items.append(
                NoteAccountOption(
                    id=account.id,
                    nickname=account.nickname,
                    mihoyo_uid=account.mihoyo_uid,
                    supported_games=supported_games,
                )
            )

        return NoteAccountListResponse(accounts=items, total=len(items))

    async def get_summary(self, *, account: MihoyoAccount) -> NoteSummaryResponse:
        supported_roles = await self._load_supported_roles(account.id)

        if not supported_roles:
            return NoteSummaryResponse(
                account_id=account.id,
                account_name=self._get_account_name(account),
                total_cards=0,
                available_cards=0,
                failed_cards=0,
                cards=[],
            )

        # 便笺属于读路径，不应该因为历史状态字段滞后就直接拒绝真实查询。
        # 这里只把“没有 Cookie / Cookie 解密失败”视为明确不可用；只要仍有可解密 Cookie，
        # 就允许实际请求一次上游接口，再由上游 retcode 决定是否真的失效。
        if not account.cookie_encrypted:
            cards = [self._build_invalid_cookie_card(role) for role in supported_roles]
            return self._build_summary(account, cards)

        try:
            cookie = decrypt_cookie(account.cookie_encrypted)
        except Exception:
            cards = [self._build_invalid_cookie_card(role) for role in supported_roles]
            return self._build_summary(account, cards)

        cards: list[NoteCardResponse] = []
        async with httpx.AsyncClient(timeout=20) as client:
            for role in supported_roles:
                cards.append(await self._fetch_role_note_card(client, cookie, role))

        return self._build_summary(account, cards)

    async def _load_supported_roles(self, account_id: int) -> list[GameRole]:
        result = await self.db.execute(
            select(GameRole).where(
                GameRole.account_id == account_id,
                GameRole.is_enabled.is_(True),
            ).order_by(GameRole.id.asc())
        )
        roles = result.scalars().all()
        return [role for role in roles if self._get_config_for_role(role)]

    def _build_summary(self, account: MihoyoAccount, cards: list[NoteCardResponse]) -> NoteSummaryResponse:
        available_cards = sum(1 for card in cards if card.status == "available")
        return NoteSummaryResponse(
            account_id=account.id,
            account_name=self._get_account_name(account),
            total_cards=len(cards),
            available_cards=available_cards,
            failed_cards=len(cards) - available_cards,
            cards=cards,
        )

    def _collect_supported_games(self, roles: list[GameRole]) -> list[str]:
        supported_games: list[str] = []
        for config in SUPPORTED_NOTE_GAME_CONFIGS:
            if any(role.game_biz.startswith(config.role_prefixes) for role in roles):
                supported_games.append(config.game)
        return supported_games

    def _get_account_name(self, account: MihoyoAccount) -> str:
        return account.nickname or account.mihoyo_uid or f"账号#{account.id}"

    def _get_config_for_role(self, role: GameRole) -> NoteGameConfig | None:
        for config in SUPPORTED_NOTE_GAME_CONFIGS:
            if role.game_biz.startswith(config.role_prefixes):
                return config
        return None

    async def _fetch_role_note_card(
        self,
        client: httpx.AsyncClient,
        cookie: str,
        role: GameRole,
    ) -> NoteCardResponse:
        config = self._get_config_for_role(role)
        if config is None:
            return self._build_error_card(role, game="unknown", game_name=role.game_biz, message="当前角色暂不支持实时便笺")

        params = {
            "role_id": role.game_uid,
            "server": role.region or "",
        }
        query = urlencode(params)
        headers = get_default_headers(cookie, device_id=generate_device_id(), ds=generate_ds_v2(query=query))

        try:
            response = await client.get(config.endpoint, params=params, headers=headers)
            payload = response.json()
        except Exception as exc:
            return self._build_error_card(
                role,
                game=config.game,
                game_name=config.game_name,
                message=f"便笺查询失败：{exc}",
            )

        retcode = int(payload.get("retcode", -1))
        if retcode == 0:
            data = payload.get("data") or {}
            if config.game == "genshin":
                metrics = self._build_genshin_metrics(data)
            else:
                metrics = self._build_starrail_metrics(data)
            return NoteCardResponse(
                role_id=role.id,
                game=config.game,
                game_name=config.game_name,
                game_biz=role.game_biz,
                role_uid=role.game_uid,
                role_nickname=role.nickname,
                region=role.region,
                level=role.level,
                status="available",
                message=None,
                updated_at=utc_now_naive().strftime("%Y-%m-%d %H:%M:%S"),
                metrics=metrics,
            )

        if retcode in (-100, -101):
            return self._build_invalid_cookie_card(role, game=config.game, game_name=config.game_name)

        message = payload.get("message") or payload.get("msg") or f"上游返回错误（code: {retcode}）"
        return self._build_error_card(role, game=config.game, game_name=config.game_name, message=message)

    def _build_invalid_cookie_card(
        self,
        role: GameRole,
        *,
        game: str | None = None,
        game_name: str | None = None,
    ) -> NoteCardResponse:
        config = self._get_config_for_role(role)
        resolved_game = game or (config.game if config else "unknown")
        resolved_name = game_name or (config.game_name if config else role.game_biz)
        return NoteCardResponse(
            role_id=role.id,
            game=resolved_game,
            game_name=resolved_name,
            game_biz=role.game_biz,
            role_uid=role.game_uid,
            role_nickname=role.nickname,
            region=role.region,
            level=role.level,
            status="invalid_cookie",
            message="登录态失效或缺少 Cookie，请先刷新登录状态后再查看实时便笺",
            updated_at=None,
            metrics=[],
        )

    def _build_error_card(self, role: GameRole, *, game: str, game_name: str, message: str) -> NoteCardResponse:
        return NoteCardResponse(
            role_id=role.id,
            game=game,
            game_name=game_name,
            game_biz=role.game_biz,
            role_uid=role.game_uid,
            role_nickname=role.nickname,
            region=role.region,
            level=role.level,
            status="error",
            message=message,
            updated_at=None,
            metrics=[],
        )

    def _build_genshin_metrics(self, data: dict) -> list[NoteMetricResponse]:
        current_resin = int(data.get("current_resin") or 0)
        max_resin = int(data.get("max_resin") or 160)
        current_home_coin = int(data.get("current_home_coin") or 0)
        max_home_coin = int(data.get("max_home_coin") or 2400)
        finished_task_num = int(data.get("finished_task_num") or 0)
        total_task_num = int(data.get("total_task_num") or 4)
        remain_discount = int(data.get("remain_resin_discount_num") or 0)
        max_discount = int(data.get("resin_discount_num_limit") or 3)
        expeditions = data.get("expeditions") or []
        finished_expeditions = sum(1 for item in expeditions if str(item.get("status", "")).lower() == "finished")
        total_expeditions = int(data.get("max_expedition_num") or len(expeditions) or 0)

        return [
            NoteMetricResponse(
                key="resin",
                label="树脂",
                value=f"{current_resin}/{max_resin}",
                detail=self._format_recovery_text(data.get("resin_recovery_time"), "回满"),
                tone=self._build_capacity_tone(current_resin, max_resin),
            ),
            NoteMetricResponse(
                key="daily_commission",
                label="每日委托",
                value=f"{finished_task_num}/{total_task_num}",
                detail="当天委托完成进度",
                tone="warning" if finished_task_num < total_task_num else "success",
            ),
            NoteMetricResponse(
                key="home_coin",
                label="洞天宝钱",
                value=f"{current_home_coin}/{max_home_coin}",
                detail=self._format_recovery_text(data.get("home_coin_recovery_time"), "接近上限"),
                tone=self._build_capacity_tone(current_home_coin, max_home_coin),
            ),
            NoteMetricResponse(
                key="weekly_discount",
                label="周本减半",
                value=f"{remain_discount}/{max_discount}",
                detail="本周树脂减半次数",
                tone="warning" if remain_discount > 0 else "normal",
            ),
            NoteMetricResponse(
                key="expedition",
                label="探索派遣",
                value=f"{finished_expeditions}/{total_expeditions} 已完成",
                detail="已完成/总派遣数",
                tone="warning" if finished_expeditions > 0 else "normal",
            ),
        ]

    def _build_starrail_metrics(self, data: dict) -> list[NoteMetricResponse]:
        current_stamina = int(data.get("current_stamina") or 0)
        max_stamina = int(data.get("max_stamina") or 240)
        reserve_stamina = int(data.get("current_reserve_stamina") or 0)
        accepted_expedition_num = int(data.get("accepted_epedition_num") or 0)
        total_expedition_num = int(data.get("total_expedition_num") or accepted_expedition_num)
        finished_expeditions = sum(
            1 for item in (data.get("expeditions") or []) if str(item.get("status", "")).lower() == "finished"
        )
        current_train_score = int(data.get("current_train_score") or 0)
        max_train_score = int(data.get("max_train_score") or 500)

        return [
            NoteMetricResponse(
                key="stamina",
                label="开拓力",
                value=f"{current_stamina}/{max_stamina}",
                detail=self._format_recovery_text(data.get("stamina_recover_time"), "回满"),
                tone=self._build_capacity_tone(current_stamina, max_stamina),
            ),
            NoteMetricResponse(
                key="reserve_stamina",
                label="后备开拓力",
                value=str(reserve_stamina),
                detail="离线累积资源",
                tone="normal",
            ),
            NoteMetricResponse(
                key="daily_training",
                label="每日实训",
                value=f"{current_train_score}/{max_train_score}",
                detail="活跃度进度",
                tone="warning" if current_train_score < max_train_score else "success",
            ),
            NoteMetricResponse(
                key="expedition",
                label="委托派遣",
                value=f"{finished_expeditions}/{total_expedition_num} 已完成",
                detail=f"进行中 {accepted_expedition_num}",
                tone="warning" if finished_expeditions > 0 else "normal",
            ),
        ]

    def _build_capacity_tone(self, current: int, maximum: int) -> str:
        if maximum <= 0:
            return "normal"
        ratio = current / maximum
        if ratio >= 0.9:
            return "warning"
        if ratio >= 0.6:
            return "info"
        return "normal"

    def _format_recovery_text(self, value: str | int | None, suffix: str) -> str | None:
        seconds = int(value or 0)
        if seconds <= 0:
            return f"已{suffix}"

        hours, remainder = divmod(seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        parts: list[str] = []
        if hours:
            parts.append(f"{hours}小时")
        if minutes or not parts:
            parts.append(f"{minutes}分钟")
        return f"{''.join(parts)}后{suffix}"
