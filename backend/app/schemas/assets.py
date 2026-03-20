"""角色资产总览聚合响应模型。"""

from datetime import datetime

from pydantic import BaseModel


class RoleAssetOverviewSummaryResponse(BaseModel):
    total_accounts: int
    total_roles: int
    gacha_archived_games: int


class RoleAssetCheckinSummaryResponse(BaseModel):
    last_status: str | None = None
    last_message: str | None = None
    last_executed_at: datetime | None = None


class RoleAssetRoleResponse(BaseModel):
    role_id: int
    game: str
    game_name: str
    game_biz: str
    game_uid: str
    nickname: str | None = None
    region: str | None = None
    level: int | None = None
    is_enabled: bool
    supported_assets: list[str]
    has_gacha_archive: bool
    recent_checkin: RoleAssetCheckinSummaryResponse


class RoleAssetAccountResponse(BaseModel):
    account_id: int
    account_name: str
    nickname: str | None = None
    mihoyo_uid: str | None = None
    cookie_status: str
    last_refresh_status: str | None = None
    roles: list[RoleAssetRoleResponse]


class RoleAssetOverviewResponse(BaseModel):
    summary: RoleAssetOverviewSummaryResponse
    accounts: list[RoleAssetAccountResponse]
