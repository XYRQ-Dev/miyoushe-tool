"""
实时便笺查询服务

当前版本改为通过 `genshin.py` 统一访问米游社战绩/便笺能力，而不是继续手写请求头和接口细节。
这样做的原因是：
1. 上游协议、设备参数和验证链路都在持续变化，社区活跃封装更适合承接这一层波动
2. 本项目前端仍需要稳定的聚合协议，因此服务层要把三游模型映射成固定的 cards/detail/metrics 结构
3. 便笺属于读路径，查询失败应透明反映状态，但不应在这里偷偷改写账号状态或混入第二套缓存
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
import logging
from typing import Any

import genshin
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
from app.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NoteGameConfig:
    game: str
    game_name: str
    role_prefixes: tuple[str, ...]
    fetch_method: str
    verification_retcodes: tuple[int, ...] = ()


SUPPORTED_NOTE_GAME_CONFIGS: tuple[NoteGameConfig, ...] = (
    NoteGameConfig(
        game="genshin",
        game_name="原神",
        role_prefixes=("hk4e_",),
        fetch_method="get_genshin_notes",
        verification_retcodes=(5003,),
    ),
    NoteGameConfig(
        game="starrail",
        game_name="星穹铁道",
        role_prefixes=("hkrpg_",),
        fetch_method="get_starrail_notes",
        verification_retcodes=(10041,),
    ),
    NoteGameConfig(
        game="zzz",
        game_name="绝区零",
        role_prefixes=("nap_",),
        fetch_method="get_zzz_notes",
        verification_retcodes=(-1104,),
    ),
)


class NoteService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _requires_explicit_server_for_role(self, role: GameRole) -> bool:
        """
        判定该角色是否必须走“显式 server”的便笺请求路径。

        为什么需要这层判定（长期维护注释，避免误改）：
        - genshin.py 的高层 `Client.get_*_notes()` API 只接收 uid/lang/autoauth 等参数，并不会接收 server。
          它内部会根据 UID 号段调用 `recognize_*_server(uid)` 推断 server，然后再发起上游请求。
        - 对国内 B 服（以及可能的其它渠道服）而言，UID 号段无法可靠地区分“官服/渠道服”的 server，
          例如原神 `cn_gf01` 与 `cn_qd01` 可能落在同一 UID 号段内，仅靠 UID 推断会把请求打到错误服，
          造成“查不到便笺/返回别的账号数据/触发鉴权异常”等高风险问题。
        - 但对常规场景（大部分官服/国际服），`get_*_notes(autoauth=True)` 已经能够正确处理鉴权刷新与协议变化，
          服务层没有必要也不应该把全部路径重写成底层请求，否则会增加维护成本并放大上游协议变动的影响面。

        因此策略是：
        - 仅对“无法安全仅靠 UID 猜服”的高风险角色（至少覆盖 *_bilibili）走显式 server 路径；
        - 其它角色继续使用 genshin.py 的高层接口，保持行为与维护成本稳定。
        """

        return bool(role.game_biz) and role.game_biz.endswith("_bilibili")

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
        # 就允许实际请求一次上游接口，再由 provider 返回的异常语义决定是否真的失效。
        if not account.cookie_encrypted:
            cards = [self._build_invalid_cookie_card(role) for role in supported_roles]
            return self._build_summary(account, cards)

        try:
            cookie = decrypt_cookie(account.cookie_encrypted)
        except Exception:
            cards = [self._build_invalid_cookie_card(role) for role in supported_roles]
            return self._build_summary(account, cards)

        client = self._build_genshin_client(cookie)
        cards = [await self._fetch_role_note_card(client, role) for role in supported_roles]
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
            schema_version=2,
            provider="genshin.py",
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

    def _build_genshin_client(self, cookie: str) -> genshin.Client:
        return genshin.Client(cookies=cookie, lang="zh-cn")

    async def _request_notes_with_explicit_server(
        self,
        client: genshin.Client,
        *,
        config: NoteGameConfig,
        role: GameRole,
        lang: str,
        autoauth: bool,
    ) -> Any:
        """
        通过 `request_game_record` 发起显式 server 的 notes 请求，并将 data 解析为对应 models。

        约束：
        - `role.region` 必须是上游接口所需的 server 字段（例如 cn_gf01/cn_qd01/prod_gf_cn/prod_qd_cn 等）。
        - `request_game_record` 的 `region` 参数表示“国内/国际”路由，和 server 字段不同；B 服属于国内路由。
        """

        notes_mapping: dict[str, tuple[str, genshin.Game, Any]] = {
            "genshin": ("dailyNote", genshin.Game.GENSHIN, genshin.models.Notes),
            "starrail": ("note", genshin.Game.STARRAIL, genshin.models.StarRailNote),
            "zzz": ("note", genshin.Game.ZZZ, genshin.models.ZZZNotes),
        }
        endpoint, game, model_cls = notes_mapping[config.game]

        async def _do_request() -> dict[str, Any]:
            raw = await client.request_game_record(
                endpoint,
                lang=lang,
                region=genshin.Region.CHINESE,
                game=game,
                params={"server": role.region, "role_id": role.game_uid},
            )
            return dict(raw or {})

        try:
            raw = await _do_request()
        except genshin.DataNotPublic:
            # 显式 server 路径仍要保持与 get_*_notes(autoauth=True) 等价的“自动开通便笺可见性”语义：
            # 当上游提示数据不公开时，若允许 autoauth，则尝试开启设置后重试一次。
            if not autoauth:
                raise
            await client.update_settings(3, True, game=game)
            raw = await _do_request()

        data = raw.get("data", raw)
        if not isinstance(data, dict):
            data = {}
        return model_cls(**data)

    async def _fetch_role_note_payload(self, client: genshin.Client, role: GameRole) -> tuple[NoteGameConfig | None, Any]:
        config = self._get_config_for_role(role)
        if config is None:
            return None, None

        # 这里显式固定 lang="zh-cn" 与 autoauth=True：
        # 1. 当前产品所有文案均为中文，若遗漏语言参数，不同环境可能回落到英文
        # 2. autoauth 交给 genshin.py 统一处理上游鉴权刷新，避免再次回到各接口手写补丁
        # 3. fetch_method 由配置层分发，后续新增游戏时只需要补配置和映射，不会把 if/else 散满服务
        if self._requires_explicit_server_for_role(role):
            payload = await self._request_notes_with_explicit_server(
                client,
                config=config,
                role=role,
                lang="zh-cn",
                autoauth=True,
            )
        else:
            method = getattr(client, config.fetch_method)
            payload = await method(uid=int(role.game_uid), lang="zh-cn", autoauth=True)
        return config, payload

    async def _fetch_role_note_card(self, client: genshin.Client, role: GameRole) -> NoteCardResponse:
        config = self._get_config_for_role(role)
        if config is None:
            return self._build_unsupported_card(role)

        # 异常边界必须拆开（长期维护注释，避免误改）：
        # - provider/integration（genshin.py / 上游接口 + 本地适配层）故障属于“外部依赖或接入层不稳定”，
        #   或者属于“provider 适配层的实现缺陷”，对用户而言都表现为“暂不可用”，应转成用户可见状态卡片
        #   （invalid_cookie / verification_required / upstream_error 等），以保证前端聚合协议稳定、
        #   并给用户明确的可操作反馈。
        # - detail/metrics 的映射属于“本地实现逻辑”。一旦这里抛异常，代表服务层代码缺陷或回归，
        #   必须向上抛出暴露给测试与日志，不能伪装成 upstream_error 吞掉，否则会掩盖真实 bug 并误导排障。
        try:
            _, payload = await self._fetch_role_note_payload(client, role)
        except genshin.InvalidCookies:
            return self._build_invalid_cookie_card(role, game=config.game, game_name=config.game_name)
        except genshin.CookieException:
            return self._build_invalid_cookie_card(role, game=config.game, game_name=config.game_name)
        except genshin.GenshinException as exc:
            if self._is_verification_exception(config, exc):
                return self._build_verification_required_card(
                    role,
                    game=config.game,
                    game_name=config.game_name,
                    retcode=getattr(exc, "retcode", 0),
                )
            return self._build_upstream_error_card(
                role,
                game=config.game,
                game_name=config.game_name,
                message=self._extract_exception_message(exc),
            )
        except Exception as exc:
            # 兜底保护 provider/integration 边界：包括 getattr/int/model 解析等适配层异常。
            # 这类错误不应打穿成 500（影响前端聚合协议），但也不能吞掉细节不留痕，因此必须写日志。
            logger.exception(
                "notes provider/integration error: game=%s role_id=%s game_biz=%s uid=%s region=%s",
                config.game,
                role.id,
                role.game_biz,
                role.game_uid,
                role.region,
            )
            return self._build_upstream_error_card(
                role,
                game=config.game,
                game_name=config.game_name,
                message="实时便笺暂时不可用，请稍后重试",
            )

        # 映射逻辑不做兜底吞错：映射异常属于本地实现 bug，应直接上抛。
        detail, metrics = self._build_detail_and_metrics(config.game, payload)
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
            detail_kind=config.game,
            detail=detail,
            metrics=metrics,
        )

    def _build_detail_and_metrics(self, game: str, payload: Any) -> tuple[dict[str, Any], list[NoteMetricResponse]]:
        if game == "genshin":
            return self._build_genshin_detail(payload), self._build_genshin_metrics(payload)
        if game == "starrail":
            return self._build_starrail_detail(payload), self._build_starrail_metrics(payload)
        if game == "zzz":
            return self._build_zzz_detail(payload), self._build_zzz_metrics(payload)
        return {}, []

    def _build_invalid_cookie_card(
        self,
        role: GameRole,
        *,
        game: str | None = None,
        game_name: str | None = None,
    ) -> NoteCardResponse:
        resolved_game, resolved_name = self._resolve_game_identity(role, game=game, game_name=game_name)
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
            detail_kind=None,
            detail=None,
            metrics=[],
        )

    def _build_upstream_error_card(self, role: GameRole, *, game: str, game_name: str, message: str) -> NoteCardResponse:
        return NoteCardResponse(
            role_id=role.id,
            game=game,
            game_name=game_name,
            game_biz=role.game_biz,
            role_uid=role.game_uid,
            role_nickname=role.nickname,
            region=role.region,
            level=role.level,
            status="upstream_error",
            message=message,
            updated_at=None,
            detail_kind=None,
            detail=None,
            metrics=[],
        )

    def _build_verification_required_card(
        self,
        role: GameRole,
        *,
        game: str,
        game_name: str,
        retcode: int,
    ) -> NoteCardResponse:
        if retcode == 5003:
            message = "实时便笺查询触发上游验证，请先在米游社 App 内完成账号验证后再试"
        else:
            message = "实时便笺访问受限，请先在米游社 App 内重新确认登录或完成账号验证后再试"

        return NoteCardResponse(
            role_id=role.id,
            game=game,
            game_name=game_name,
            game_biz=role.game_biz,
            role_uid=role.game_uid,
            role_nickname=role.nickname,
            region=role.region,
            level=role.level,
            status="verification_required",
            message=f"{message}（code: {retcode}）" if retcode else message,
            updated_at=None,
            detail_kind=None,
            detail=None,
            metrics=[],
        )

    def _build_unsupported_card(self, role: GameRole) -> NoteCardResponse:
        return NoteCardResponse(
            role_id=role.id,
            game="unknown",
            game_name=role.game_biz,
            game_biz=role.game_biz,
            role_uid=role.game_uid,
            role_nickname=role.nickname,
            region=role.region,
            level=role.level,
            status="unsupported",
            message="当前角色暂不支持实时便笺",
            updated_at=None,
            detail_kind=None,
            detail=None,
            metrics=[],
        )

    def _resolve_game_identity(
        self,
        role: GameRole,
        *,
        game: str | None = None,
        game_name: str | None = None,
    ) -> tuple[str, str]:
        config = self._get_config_for_role(role)
        resolved_game = game or (config.game if config else "unknown")
        resolved_name = game_name or (config.game_name if config else role.game_biz)
        return resolved_game, resolved_name

    def _build_genshin_detail(self, notes: Any) -> dict[str, Any]:
        finished_expeditions = sum(1 for item in self._get_iterable(notes, "expeditions") if self._is_finished(item))
        return {
            "current_resin": self._get_int(notes, "current_resin"),
            "max_resin": self._get_int(notes, "max_resin", default=160),
            "remaining_resin_recovery_seconds": self._get_seconds(notes, "remaining_resin_recovery_time"),
            "current_realm_currency": self._get_int(notes, "current_realm_currency"),
            "max_realm_currency": self._get_int(notes, "max_realm_currency", default=2400),
            "remaining_realm_currency_recovery_seconds": self._get_seconds(
                notes,
                "remaining_realm_currency_recovery_time",
            ),
            "completed_commissions": self._get_int(notes, "completed_commissions"),
            "max_commissions": self._get_int(notes, "max_commissions", default=4),
            "claimed_commission_reward": bool(getattr(notes, "claimed_commission_reward", False)),
            "remaining_weekly_discounts": self._get_int(notes, "remaining_resin_discounts"),
            "max_weekly_discounts": self._get_int(notes, "max_resin_discounts", default=3),
            "expeditions_finished": finished_expeditions,
            "expeditions_total": self._get_int(notes, "max_expeditions", default=len(self._get_iterable(notes, "expeditions"))),
        }

    def _build_genshin_metrics(self, notes: Any) -> list[NoteMetricResponse]:
        detail = self._build_genshin_detail(notes)
        return [
            NoteMetricResponse(
                key="resin",
                label="树脂",
                value=f"{detail['current_resin']}/{detail['max_resin']}",
                detail=self._format_recovery_text(detail["remaining_resin_recovery_seconds"], "回满"),
                tone=self._build_capacity_tone(detail["current_resin"], detail["max_resin"]),
            ),
            NoteMetricResponse(
                key="daily_commission",
                label="每日委托",
                value=f"{detail['completed_commissions']}/{detail['max_commissions']}",
                detail="当天委托完成进度",
                tone="warning" if detail["completed_commissions"] < detail["max_commissions"] else "success",
            ),
            NoteMetricResponse(
                key="home_coin",
                label="洞天宝钱",
                value=f"{detail['current_realm_currency']}/{detail['max_realm_currency']}",
                detail=self._format_recovery_text(detail["remaining_realm_currency_recovery_seconds"], "接近上限"),
                tone=self._build_capacity_tone(detail["current_realm_currency"], detail["max_realm_currency"]),
            ),
            NoteMetricResponse(
                key="weekly_discount",
                label="周本减半",
                value=f"{detail['remaining_weekly_discounts']}/{detail['max_weekly_discounts']}",
                detail="本周树脂减半次数",
                tone="warning" if detail["remaining_weekly_discounts"] > 0 else "normal",
            ),
            NoteMetricResponse(
                key="expedition",
                label="探索派遣",
                value=f"{detail['expeditions_finished']}/{detail['expeditions_total']} 已完成",
                detail="已完成/总派遣数",
                tone="warning" if detail["expeditions_finished"] > 0 else "normal",
            ),
        ]

    def _build_starrail_detail(self, notes: Any) -> dict[str, Any]:
        finished_expeditions = sum(1 for item in self._get_iterable(notes, "expeditions") if self._is_finished(item))
        return {
            "current_stamina": self._get_int(notes, "current_stamina"),
            "max_stamina": self._get_int(notes, "max_stamina", default=240),
            "remaining_stamina_recovery_seconds": self._get_seconds(notes, "stamina_recover_time"),
            "current_reserve_stamina": self._get_int(notes, "current_reserve_stamina"),
            "is_reserve_stamina_full": bool(getattr(notes, "is_reserve_stamina_full", False)),
            "current_train_score": self._get_int(notes, "current_train_score"),
            "max_train_score": self._get_int(notes, "max_train_score", default=500),
            "accepted_expedition_num": self._get_int(notes, "accepted_expedition_num"),
            "total_expedition_num": self._get_int(notes, "total_expedition_num"),
            "finished_expeditions": finished_expeditions,
            "current_rogue_score": self._get_int(notes, "current_rogue_score"),
            "max_rogue_score": self._get_int(notes, "max_rogue_score"),
            "current_bonus_synchronicity_points": self._get_int(notes, "current_bonus_synchronicity_points"),
            "max_bonus_synchronicity_points": self._get_int(notes, "max_bonus_synchronicity_points"),
            "have_bonus_synchronicity_points": bool(getattr(notes, "have_bonus_synchronicity_points", False)),
            "remaining_weekly_discounts": self._get_int(notes, "remaining_weekly_discounts"),
            "max_weekly_discounts": self._get_int(notes, "max_weekly_discounts"),
        }

    def _build_starrail_metrics(self, notes: Any) -> list[NoteMetricResponse]:
        detail = self._build_starrail_detail(notes)
        weekly_points_value = (
            f"{detail['current_bonus_synchronicity_points']}/{detail['max_bonus_synchronicity_points']}"
            if detail["have_bonus_synchronicity_points"]
            else f"{detail['current_rogue_score']}/{detail['max_rogue_score']}"
        )
        weekly_points_detail = "差分宇宙积分" if detail["have_bonus_synchronicity_points"] else "模拟宇宙积分"
        return [
            NoteMetricResponse(
                key="stamina",
                label="开拓力",
                value=f"{detail['current_stamina']}/{detail['max_stamina']}",
                detail=self._format_recovery_text(detail["remaining_stamina_recovery_seconds"], "回满"),
                tone=self._build_capacity_tone(detail["current_stamina"], detail["max_stamina"]),
            ),
            NoteMetricResponse(
                key="reserve_stamina",
                label="后备开拓力",
                value=str(detail["current_reserve_stamina"]),
                detail="离线累积资源",
                tone="normal",
            ),
            NoteMetricResponse(
                key="daily_training",
                label="每日实训",
                value=f"{detail['current_train_score']}/{detail['max_train_score']}",
                detail="活跃度进度",
                tone="warning" if detail["current_train_score"] < detail["max_train_score"] else "success",
            ),
            NoteMetricResponse(
                key="expedition",
                label="委托派遣",
                value=f"{detail['finished_expeditions']}/{detail['total_expedition_num']} 已完成",
                detail=f"进行中 {detail['accepted_expedition_num']}",
                tone="warning" if detail["finished_expeditions"] > 0 else "normal",
            ),
            NoteMetricResponse(
                key="weekly_points",
                label="周常点数",
                value=weekly_points_value,
                detail=weekly_points_detail,
                tone="warning" if detail["current_rogue_score"] < detail["max_rogue_score"] else "normal",
            ),
        ]

    def _build_zzz_detail(self, notes: Any) -> dict[str, Any]:
        battery_charge = getattr(notes, "battery_charge", None)
        engagement = getattr(notes, "engagement", None)
        hollow_zero = getattr(notes, "hollow_zero", None)
        weekly_task = getattr(notes, "weekly_task", None)
        member_card = getattr(notes, "member_card", None)
        temple_running = getattr(notes, "temple_running", None)
        return {
            "battery_charge": {
                "current": self._get_int(battery_charge, "current"),
                "max": self._get_int(battery_charge, "max"),
                "seconds_till_full": self._get_int(battery_charge, "seconds_till_full"),
            },
            "engagement": {
                "current": self._get_int(engagement, "current"),
                "max": self._get_int(engagement, "max"),
            },
            "scratch_card_completed": bool(getattr(notes, "scratch_card_completed", False)),
            "video_store_state": self._enum_value(getattr(notes, "video_store_state", None)),
            "hollow_zero": {
                "bounty_commission": self._model_dump(getattr(hollow_zero, "bounty_commission", None)),
                "investigation_point": self._model_dump(getattr(hollow_zero, "investigation_point", None)),
            },
            "card_sign": self._enum_value(getattr(notes, "card_sign", None)),
            "member_card": {
                "is_open": bool(getattr(member_card, "is_open", False)) if member_card is not None else False,
                "member_card_state": self._enum_value(getattr(member_card, "member_card_state", None)),
                "seconds_until_expire": self._get_seconds(member_card, "exp_time"),
            },
            "temple_running": {
                "bench_state": self._enum_value(getattr(temple_running, "bench_state", None)),
                "current_currency": self._get_int(temple_running, "current_currency"),
                "currency_next_refresh_seconds": self._get_seconds(temple_running, "currency_next_refresh_ts"),
                "expedition_state": self._enum_value(getattr(temple_running, "expedition_state", None)),
                "level": self._get_int(temple_running, "level"),
                "shelve_state": self._enum_value(getattr(temple_running, "shelve_state", None)),
                "weekly_currency_max": self._get_int(temple_running, "weekly_currency_max"),
            },
            "weekly_task": {
                "cur_point": self._get_int(weekly_task, "cur_point"),
                "max_point": self._get_int(weekly_task, "max_point"),
                "refresh_seconds": self._get_seconds(weekly_task, "refresh_time"),
            }
            if weekly_task is not None
            else None,
        }

    def _build_zzz_metrics(self, notes: Any) -> list[NoteMetricResponse]:
        detail = self._build_zzz_detail(notes)
        battery = detail["battery_charge"]
        engagement = detail["engagement"]
        weekly = detail["weekly_task"] or {"cur_point": 0, "max_point": 0}
        return [
            NoteMetricResponse(
                key="battery_charge",
                label="电量",
                value=f"{battery['current']}/{battery['max']}",
                detail=self._format_recovery_text(battery["seconds_till_full"], "回满"),
                tone=self._build_capacity_tone(battery["current"], battery["max"]),
            ),
            NoteMetricResponse(
                key="engagement",
                label="活跃度",
                value=f"{engagement['current']}/{engagement['max']}",
                detail="每日活跃进度",
                tone="warning" if engagement["current"] < engagement["max"] else "success",
            ),
            NoteMetricResponse(
                key="scratch_card",
                label="刮刮卡",
                value="已完成" if detail["scratch_card_completed"] else "未完成",
                detail="当日刮刮卡状态",
                tone="success" if detail["scratch_card_completed"] else "warning",
            ),
            NoteMetricResponse(
                key="video_store",
                label="录像店",
                value=str(detail["video_store_state"] or "unknown"),
                detail="营业状态",
                tone="normal",
            ),
            NoteMetricResponse(
                key="weekly_task",
                label="周常",
                value=f"{weekly['cur_point']}/{weekly['max_point']}",
                detail="周常积分进度",
                tone="warning" if weekly["max_point"] and weekly["cur_point"] < weekly["max_point"] else "success",
            ),
        ]

    def _is_verification_exception(self, config: NoteGameConfig, exc: genshin.GenshinException) -> bool:
        retcode = getattr(exc, "retcode", 0)
        message = self._extract_exception_message(exc)
        if retcode in config.verification_retcodes:
            return True
        # 仅用 retcode 与明确的“验证”提示判定验证态。普通英文词 “app” 出现在大量无关上游错误中，容易误把真实故障上抛成 verification_required，
        # 但 verification_required 会阻止用户刷新尝试并误导告警，必须保持高置信度，因此只保留更具体的描述。
        if "验证" in message:
            return True
        return False

    def _extract_exception_message(self, exc: genshin.GenshinException) -> str:
        original = getattr(exc, "original", "") or ""
        if original:
            return original
        text = str(exc).strip()
        return text or "实时便笺暂时不可用，请稍后重试"

    def _get_int(self, source: Any, field: str, *, default: int = 0) -> int:
        if source is None:
            return default
        value = getattr(source, field, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _get_iterable(self, source: Any, field: str) -> list[Any]:
        if source is None:
            return []
        value = getattr(source, field, None)
        return list(value or [])

    def _get_seconds(self, source: Any, field: str) -> int:
        if source is None:
            return 0
        value = getattr(source, field, None)
        if value is None:
            return 0
        if isinstance(value, timedelta):
            return max(0, int(value.total_seconds()))
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    def _is_finished(self, item: Any) -> bool:
        finished = getattr(item, "finished", None)
        if isinstance(finished, bool):
            return finished
        status = str(getattr(item, "status", "")).lower()
        return status == "finished"

    def _enum_value(self, value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        return value

    def _model_dump(self, value: Any) -> Any:
        if value is None:
            return None
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if hasattr(value, "__dict__"):
            return dict(value.__dict__)
        return value

    def _build_capacity_tone(self, current: int, maximum: int) -> str:
        if maximum <= 0:
            return "normal"
        ratio = current / maximum
        if ratio >= 0.9:
            return "warning"
        if ratio >= 0.6:
            return "info"
        return "normal"

    def _format_recovery_text(self, seconds: int | None, suffix: str) -> str | None:
        total_seconds = int(seconds or 0)
        if total_seconds <= 0:
            return f"已{suffix}"

        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        parts: list[str] = []
        if hours:
            parts.append(f"{hours}小时")
        if minutes or not parts:
            parts.append(f"{minutes}分钟")
        return f"{''.join(parts)}后{suffix}"
