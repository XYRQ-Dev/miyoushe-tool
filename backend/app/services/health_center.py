"""
账号健康中心聚合服务。

该服务只做“读时聚合”，不额外写库：
1. 健康中心属于中枢视图，应该复用现有登录态与签到结果，而不是制造第二套真相源
2. 当前仓库没有完整通知审计表，v1 只返回可被当前数据稳定证明的健康信息
3. 健康等级必须在后端统一判定，避免账号页、首页和健康中心各自使用不同语义
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import GameRole, MihoyoAccount
from app.models.task_log import TaskLog
from app.schemas.health_center import (
    HealthAccountResponse,
    HealthCenterOverviewResponse,
    HealthCenterSummaryResponse,
    HealthCheckinSnapshotResponse,
    HealthRecentEventResponse,
)
from app.services.checkin import is_checkin_supported_game
from app.services.gacha import SUPPORTED_GACHA_GAME_CONFIGS
from app.services.redeem import SUPPORTED_REDEEM_GAME_CONFIGS
from app.utils.timezone import get_app_day_utc_range, get_current_app_date


@dataclass(frozen=True)
class _HealthAccountContext:
    account: MihoyoAccount
    roles: list[GameRole]
    logs: list[TaskLog]
    health_level: str
    health_reason: str
    latest_event_at: object


class HealthCenterService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_overview(self, *, user_id: int) -> HealthCenterOverviewResponse:
        accounts_result = await self.db.execute(
            select(MihoyoAccount)
            .where(MihoyoAccount.user_id == user_id)
            .order_by(MihoyoAccount.created_at.desc(), MihoyoAccount.id.desc())
        )
        accounts = accounts_result.scalars().all()
        if not accounts:
            return HealthCenterOverviewResponse(
                summary=HealthCenterSummaryResponse(
                    total_accounts=0,
                    healthy_accounts=0,
                    reauth_required_accounts=0,
                    warning_accounts=0,
                    failed_accounts_7d=0,
                ),
                accounts=[],
                recent_events=[],
            )

        account_ids = [account.id for account in accounts]
        roles_result = await self.db.execute(
            select(GameRole)
            .where(GameRole.account_id.in_(account_ids))
            .order_by(GameRole.id.asc())
        )
        roles_by_account: dict[int, list[GameRole]] = {}
        for role in roles_result.scalars().all():
            roles_by_account.setdefault(role.account_id, []).append(role)

        start_dt, end_dt = self._get_recent_range()
        logs_result = await self.db.execute(
            select(TaskLog)
            .where(
                TaskLog.account_id.in_(account_ids),
                TaskLog.task_type == "checkin",
                TaskLog.executed_at >= start_dt,
                TaskLog.executed_at < end_dt,
            )
            .order_by(TaskLog.executed_at.desc(), TaskLog.id.desc())
        )
        logs_by_account: dict[int, list[TaskLog]] = {}
        for log in logs_result.scalars().all():
            logs_by_account.setdefault(log.account_id, []).append(log)

        contexts: list[_HealthAccountContext] = []
        events: list[HealthRecentEventResponse] = []

        for account in accounts:
            roles = roles_by_account.get(account.id, [])
            logs = logs_by_account.get(account.id, [])
            health_level, health_reason = self._determine_health(account=account, logs=logs)
            latest_event_at = self._resolve_latest_event_at(account=account, logs=logs)
            contexts.append(
                _HealthAccountContext(
                    account=account,
                    roles=roles,
                    logs=logs,
                    health_level=health_level,
                    health_reason=health_reason,
                    latest_event_at=latest_event_at,
                )
            )
            events.extend(
                self._build_recent_events(
                    account=account,
                    logs=logs,
                    health_level=health_level,
                    health_reason=health_reason,
                )
            )

        contexts.sort(
            key=lambda item: (
                self._get_health_level_priority(item.health_level),
                -(item.latest_event_at.timestamp() if item.latest_event_at else 0),
                -item.account.id,
            )
        )
        events.sort(key=lambda item: (item.occurred_at, item.account_id), reverse=True)

        account_items = [
            self._build_account_response(
                account=context.account,
                roles=context.roles,
                logs=context.logs,
                health_level=context.health_level,
                health_reason=context.health_reason,
            )
            for context in contexts
        ]

        failed_accounts_7d = len({
            context.account.id
            for context in contexts
            if any(log.status in ("failed", "risk") for log in context.logs)
        })

        summary = HealthCenterSummaryResponse(
            total_accounts=len(accounts),
            healthy_accounts=sum(1 for context in contexts if context.health_level == "healthy"),
            reauth_required_accounts=sum(1 for account in accounts if account.cookie_status == "reauth_required"),
            warning_accounts=sum(1 for context in contexts if context.health_level == "warning"),
            failed_accounts_7d=failed_accounts_7d,
        )
        return HealthCenterOverviewResponse(
            summary=summary,
            accounts=account_items,
            recent_events=events[:20],
        )

    def _get_recent_range(self) -> tuple[object, object]:
        start_day = get_current_app_date() - timedelta(days=6)
        return get_app_day_utc_range(start_day)[0], get_app_day_utc_range(get_current_app_date())[1]

    def _determine_health(self, *, account: MihoyoAccount, logs: list[TaskLog]) -> tuple[str, str]:
        if account.cookie_status == "reauth_required":
            return "danger", "登录态失效，需要重新扫码登录"

        failed_count = sum(1 for log in logs if log.status == "failed")
        risk_count = sum(1 for log in logs if log.status == "risk")
        has_recent_checkin_issue = failed_count > 0 or risk_count > 0

        if account.cookie_status in ("expired", "refreshing"):
            return "warning", "当前登录态需要关注，建议尽快重新扫码或再次校验"

        if account.last_refresh_status in ("warning", "network_error"):
            return "warning", account.last_refresh_message or "最近一次登录态校验存在异常"

        if has_recent_checkin_issue:
            return "warning", f"近 7 天存在 {failed_count} 次失败、{risk_count} 次风险签到"

        if account.cookie_status == "valid" and self._has_success_evidence(account=account, logs=logs):
            return "healthy", "登录态有效，近 7 天无失败签到"

        return "unknown", "当前尚无成功签到或登录态校验记录，暂未完成健康判定"

    def _has_success_evidence(self, *, account: MihoyoAccount, logs: list[TaskLog]) -> bool:
        if any(log.status in ("success", "already_signed") for log in logs):
            return True
        return account.last_refresh_status in ("success", "valid")

    def _resolve_latest_event_at(self, *, account: MihoyoAccount, logs: list[TaskLog]):
        candidate_times = [log.executed_at for log in logs if log.executed_at is not None]
        if account.last_refresh_attempt_at:
            candidate_times.append(account.last_refresh_attempt_at)
        if account.last_cookie_check:
            candidate_times.append(account.last_cookie_check)
        if account.created_at:
            candidate_times.append(account.created_at)
        return max(candidate_times) if candidate_times else None

    def _build_account_response(
        self,
        *,
        account: MihoyoAccount,
        roles: list[GameRole],
        logs: list[TaskLog],
        health_level: str,
        health_reason: str,
    ) -> HealthAccountResponse:
        recent_checkin = self._build_checkin_snapshot(logs)
        return HealthAccountResponse(
            account_id=account.id,
            nickname=account.nickname,
            mihoyo_uid=account.mihoyo_uid,
            cookie_status=account.cookie_status,
            last_refresh_status=account.last_refresh_status,
            last_refresh_message=account.last_refresh_message,
            last_refresh_attempt_at=account.last_refresh_attempt_at,
            game_role_count=len(roles),
            supported_games=self._collect_supported_games(roles),
            supported_assets=self._collect_supported_assets(roles),
            health_level=health_level,
            health_reason=health_reason,
            recent_checkin=recent_checkin,
        )

    def _build_checkin_snapshot(self, logs: list[TaskLog]) -> HealthCheckinSnapshotResponse:
        latest_log = logs[0] if logs else None
        return HealthCheckinSnapshotResponse(
            success_count_7d=sum(1 for log in logs if log.status in ("success", "already_signed")),
            failed_count_7d=sum(1 for log in logs if log.status == "failed"),
            risk_count_7d=sum(1 for log in logs if log.status == "risk"),
            last_checkin_at=latest_log.executed_at if latest_log else None,
            last_checkin_status=latest_log.status if latest_log else None,
            last_checkin_message=latest_log.message if latest_log else None,
        )

    def _build_recent_events(
        self,
        *,
        account: MihoyoAccount,
        logs: list[TaskLog],
        health_level: str,
        health_reason: str,
    ) -> list[HealthRecentEventResponse]:
        account_name = self._get_account_name(account)
        events = [
            HealthRecentEventResponse(
                account_id=account.id,
                account_name=account_name,
                event_type="checkin",
                status=log.status,
                message=log.message or "签到执行异常",
                occurred_at=log.executed_at,
            )
            for log in logs
            if log.status in ("failed", "risk")
        ]

        if self._should_emit_login_event(account=account):
            events.append(
                HealthRecentEventResponse(
                    account_id=account.id,
                    account_name=account_name,
                    event_type="login_state",
                    status=account.cookie_status if account.cookie_status != "valid" else (account.last_refresh_status or "unknown"),
                    message=account.last_refresh_message or health_reason,
                    occurred_at=account.last_refresh_attempt_at or account.last_cookie_check or account.created_at,
                )
            )
        return events

    def _should_emit_login_event(self, *, account: MihoyoAccount) -> bool:
        return bool(
            account.cookie_status in ("reauth_required", "expired", "refreshing")
            or account.last_refresh_status in ("warning", "network_error")
        )

    def _collect_supported_games(self, roles: list[GameRole]) -> list[str]:
        games: list[str] = []
        for game_name, prefixes in (
            ("genshin", ("hk4e_",)),
            ("starrail", ("hkrpg_",)),
            ("bh3_cn", ("bh3_",)),
            ("nap_cn", ("nap_",)),
        ):
            if any(role.game_biz.startswith(prefixes) for role in roles):
                games.append(game_name)
        return games

    def _collect_supported_assets(self, roles: list[GameRole]) -> list[str]:
        assets: list[str] = []
        if any(role.is_enabled and is_checkin_supported_game(role.game_biz) for role in roles):
            assets.append("checkin")
        if any(self._role_matches_gacha(role) for role in roles):
            assets.append("gacha")
        if any(role.is_enabled and self._role_matches_redeem(role) for role in roles):
            assets.append("redeem")
        return assets

    def _role_matches_gacha(self, role: GameRole) -> bool:
        return any(
            role.game_biz.startswith(tuple(config["supported_role_prefixes"]))
            for config in SUPPORTED_GACHA_GAME_CONFIGS.values()
        )

    def _role_matches_redeem(self, role: GameRole) -> bool:
        return any(role.game_biz.startswith(config.role_prefixes) for config in SUPPORTED_REDEEM_GAME_CONFIGS)

    def _get_account_name(self, account: MihoyoAccount) -> str:
        return account.nickname or account.mihoyo_uid or f"账号#{account.id}"

    def _get_health_level_priority(self, health_level: str) -> int:
        priority = {"danger": 0, "warning": 1, "healthy": 2, "unknown": 3}
        return priority.get(health_level, 99)


health_center_service_type = HealthCenterService
