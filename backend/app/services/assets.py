"""
角色资产总览聚合服务。

该服务只负责把现有账号、角色、签到、抽卡能力聚合为稳定的只读视图：
1. 不新增数据库表，避免把“页面展示状态”做成第二套真相源
2. 抽卡和兑换目前仍是账号 + 游戏维度，因此角色卡只携带入口上下文，不伪造角色级业务语义
3. 便笺状态只返回“是否具备查询前提”，不会在总览页隐式触发上游请求
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import GameRole, MihoyoAccount
from app.models.gacha import GachaRecord
from app.models.task_log import TaskLog
from app.schemas.assets import (
    RoleAssetAccountResponse,
    RoleAssetCheckinSummaryResponse,
    RoleAssetOverviewResponse,
    RoleAssetOverviewSummaryResponse,
    RoleAssetRoleResponse,
)
from app.services.checkin import is_checkin_supported_game
from app.services.gacha import SUPPORTED_GACHA_GAME_CONFIGS
from app.services.notes import SUPPORTED_NOTE_GAME_CONFIGS
from app.services.redeem import SUPPORTED_REDEEM_GAME_CONFIGS


@dataclass(frozen=True)
class RoleGameDescriptor:
    game: str
    game_name: str
    role_prefixes: tuple[str, ...]


ROLE_GAME_DESCRIPTORS: tuple[RoleGameDescriptor, ...] = (
    RoleGameDescriptor(game="genshin", game_name="原神", role_prefixes=("hk4e_",)),
    RoleGameDescriptor(game="starrail", game_name="星穹铁道", role_prefixes=("hkrpg_",)),
    RoleGameDescriptor(game="bh3_cn", game_name="崩坏3", role_prefixes=("bh3_",)),
    RoleGameDescriptor(game="nap_cn", game_name="绝区零", role_prefixes=("nap_",)),
)


class RoleAssetService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_overview(self, *, user_id: int) -> RoleAssetOverviewResponse:
        accounts_result = await self.db.execute(
            select(MihoyoAccount)
            .where(MihoyoAccount.user_id == user_id)
            .order_by(MihoyoAccount.created_at.desc(), MihoyoAccount.id.desc())
        )
        accounts = accounts_result.scalars().all()
        if not accounts:
            return RoleAssetOverviewResponse(
                summary=RoleAssetOverviewSummaryResponse(
                    total_accounts=0,
                    total_roles=0,
                    note_supported_roles=0,
                    gacha_archived_games=0,
                ),
                accounts=[],
            )

        account_ids = [account.id for account in accounts]
        roles_result = await self.db.execute(
            select(GameRole)
            .where(GameRole.account_id.in_(account_ids))
            .order_by(GameRole.account_id.asc(), GameRole.id.asc())
        )
        roles = roles_result.scalars().all()

        roles_by_account: dict[int, list[GameRole]] = {}
        for role in roles:
            roles_by_account.setdefault(role.account_id, []).append(role)

        latest_logs_by_role = await self._load_latest_checkin_logs([role.id for role in roles])
        gacha_archive_pairs = await self._load_gacha_archive_pairs(account_ids)

        account_items = [
            self._build_account_response(
                account=account,
                roles=roles_by_account.get(account.id, []),
                latest_logs_by_role=latest_logs_by_role,
                gacha_archive_pairs=gacha_archive_pairs,
            )
            for account in accounts
        ]

        summary = RoleAssetOverviewSummaryResponse(
            total_accounts=len(accounts),
            total_roles=len(roles),
            note_supported_roles=sum(1 for role in roles if role.is_enabled and self._role_matches_note(role)),
            gacha_archived_games=len(gacha_archive_pairs),
        )
        return RoleAssetOverviewResponse(summary=summary, accounts=account_items)

    async def _load_latest_checkin_logs(self, role_ids: list[int]) -> dict[int, TaskLog]:
        if not role_ids:
            return {}

        logs_result = await self.db.execute(
            select(TaskLog)
            .where(
                TaskLog.game_role_id.in_(role_ids),
                TaskLog.task_type == "checkin",
            )
            .order_by(TaskLog.executed_at.desc(), TaskLog.id.desc())
        )
        latest_logs_by_role: dict[int, TaskLog] = {}
        for log in logs_result.scalars().all():
            if log.game_role_id is None or log.game_role_id in latest_logs_by_role:
                continue
            latest_logs_by_role[log.game_role_id] = log
        return latest_logs_by_role

    async def _load_gacha_archive_pairs(self, account_ids: list[int]) -> set[tuple[int, str]]:
        if not account_ids:
            return set()

        rows = await self.db.execute(
            select(GachaRecord.account_id, GachaRecord.game)
            .where(GachaRecord.account_id.in_(account_ids))
            .group_by(GachaRecord.account_id, GachaRecord.game)
        )
        return {(account_id, game) for account_id, game in rows.all()}

    def _build_account_response(
        self,
        *,
        account: MihoyoAccount,
        roles: list[GameRole],
        latest_logs_by_role: dict[int, TaskLog],
        gacha_archive_pairs: set[tuple[int, str]],
    ) -> RoleAssetAccountResponse:
        return RoleAssetAccountResponse(
            account_id=account.id,
            account_name=self._get_account_name(account),
            nickname=account.nickname,
            mihoyo_uid=account.mihoyo_uid,
            cookie_status=account.cookie_status,
            last_refresh_status=account.last_refresh_status,
            roles=[
                self._build_role_response(
                    account=account,
                    role=role,
                    latest_log=latest_logs_by_role.get(role.id),
                    gacha_archive_pairs=gacha_archive_pairs,
                )
                for role in roles
            ],
        )

    def _build_role_response(
        self,
        *,
        account: MihoyoAccount,
        role: GameRole,
        latest_log: TaskLog | None,
        gacha_archive_pairs: set[tuple[int, str]],
    ) -> RoleAssetRoleResponse:
        game, game_name = self._resolve_game(role)
        return RoleAssetRoleResponse(
            role_id=role.id,
            game=game,
            game_name=game_name,
            game_biz=role.game_biz,
            game_uid=role.game_uid,
            nickname=role.nickname,
            region=role.region,
            level=role.level,
            is_enabled=role.is_enabled,
            supported_assets=self._collect_supported_assets(role),
            notes_status=self._resolve_notes_status(account=account, role=role),
            has_gacha_archive=(account.id, game) in gacha_archive_pairs,
            recent_checkin=RoleAssetCheckinSummaryResponse(
                last_status=latest_log.status if latest_log else None,
                last_message=latest_log.message if latest_log else None,
                last_executed_at=latest_log.executed_at if latest_log else None,
            ),
        )

    def _resolve_game(self, role: GameRole) -> tuple[str, str]:
        for descriptor in ROLE_GAME_DESCRIPTORS:
            if role.game_biz.startswith(descriptor.role_prefixes):
                return descriptor.game, descriptor.game_name
        return role.game_biz, role.game_biz

    def _resolve_notes_status(self, *, account: MihoyoAccount, role: GameRole) -> str:
        if not role.is_enabled or not self._role_matches_note(role):
            return "unsupported"

        # 角色资产总览只判断“是否具备查询前提”，不主动请求上游便笺接口。
        # 这里把明确缺少登录态或已知需要重登的账号标成 login_required，避免总览页为了展示卡片而引入额外副作用。
        if account.cookie_status == "reauth_required" or not account.cookie_encrypted:
            return "login_required"
        return "available"

    def _collect_supported_assets(self, role: GameRole) -> list[str]:
        assets: list[str] = []
        if role.is_enabled and is_checkin_supported_game(role.game_biz):
            assets.append("checkin")
        if role.is_enabled and self._role_matches_note(role):
            assets.append("notes")
        if self._role_matches_gacha(role):
            assets.append("gacha")
        if role.is_enabled and self._role_matches_redeem(role):
            assets.append("redeem")
        return assets

    def _role_matches_note(self, role: GameRole) -> bool:
        return any(role.game_biz.startswith(config.role_prefixes) for config in SUPPORTED_NOTE_GAME_CONFIGS)

    def _role_matches_gacha(self, role: GameRole) -> bool:
        return any(
            role.game_biz.startswith(tuple(config["supported_role_prefixes"]))
            for config in SUPPORTED_GACHA_GAME_CONFIGS.values()
        )

    def _role_matches_redeem(self, role: GameRole) -> bool:
        return any(role.game_biz.startswith(config.role_prefixes) for config in SUPPORTED_REDEEM_GAME_CONFIGS)

    def _get_account_name(self, account: MihoyoAccount) -> str:
        return account.nickname or account.mihoyo_uid or f"账号#{account.id}"
