"""米哈游账号和游戏角色的 Pydantic 模型"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class GameRoleResponse(BaseModel):
    id: int
    game_biz: str
    game_uid: str
    nickname: Optional[str] = None
    region: Optional[str] = None
    level: Optional[int] = None
    is_enabled: bool = True

    model_config = {"from_attributes": True}


class AccountResponse(BaseModel):
    id: int
    user_id: int
    nickname: Optional[str] = None
    mihoyo_uid: Optional[str] = None
    cookie_status: str = "valid"
    last_cookie_check: Optional[datetime] = None
    last_refresh_attempt_at: Optional[datetime] = None
    last_refresh_status: Optional[str] = None
    last_refresh_message: Optional[str] = None
    reauth_notified_at: Optional[datetime] = None
    created_at: datetime
    game_roles: List[GameRoleResponse] = []

    model_config = {"from_attributes": True}


class AccountListResponse(BaseModel):
    accounts: List[AccountResponse]
    total: int


class QrLoginStartResponse(BaseModel):
    session_id: str
    message: str = "请使用米游社 App 扫描二维码"
