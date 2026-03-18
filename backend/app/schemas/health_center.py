"""账号健康中心聚合响应模型。"""

from datetime import datetime

from pydantic import BaseModel


class HealthCenterSummaryResponse(BaseModel):
    total_accounts: int
    healthy_accounts: int
    reauth_required_accounts: int
    warning_accounts: int
    failed_accounts_7d: int


class HealthCheckinSnapshotResponse(BaseModel):
    success_count_7d: int
    failed_count_7d: int
    risk_count_7d: int
    last_checkin_at: datetime | None = None
    last_checkin_status: str | None = None
    last_checkin_message: str | None = None


class HealthAccountResponse(BaseModel):
    account_id: int
    nickname: str | None = None
    mihoyo_uid: str | None = None
    cookie_status: str
    last_refresh_status: str | None = None
    last_refresh_message: str | None = None
    last_refresh_attempt_at: datetime | None = None
    auto_refresh_available: bool
    game_role_count: int
    supported_games: list[str]
    supported_assets: list[str]
    health_level: str
    health_reason: str
    recent_checkin: HealthCheckinSnapshotResponse


class HealthRecentEventResponse(BaseModel):
    account_id: int
    account_name: str
    event_type: str
    status: str
    message: str
    occurred_at: datetime


class HealthCenterOverviewResponse(BaseModel):
    summary: HealthCenterSummaryResponse
    accounts: list[HealthAccountResponse]
    recent_events: list[HealthRecentEventResponse]
