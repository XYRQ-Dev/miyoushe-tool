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
    # `has_high_privilege_auth` 表示账号是否已经具备 Passport 根凭据，
    # 不是“当前 Cookie 一定可用”的同义词。前端需要同时看它和 `cookie_status`，
    # 才能区分“高权限已接入但工作 Cookie 尚未补齐”和“账号仍停留在旧网页登录形态”。
    has_high_privilege_auth: bool = False
    # `credential_status` 表示根凭据层的最终对外语义。
    # 对旧 Cookie-only 账号，后端会强制把它收口为 `reauth_required`，
    # 即使数据库里还残留旧版本写下的 `valid` 或空值也不能透传。
    # 如果误把这里继续当成“原始库值回显”，前端就会把必须升级的旧账号误展示为正常。
    credential_status: Optional[str] = None
    credential_source: Optional[str] = None
    # `upgrade_required` 是旧账号迁移期的显式标志：
    # 只要账号仍然只有历史网页登录 Cookie、没有 Passport 根凭据，就必须为 `True`。
    # 不要把它和 `cookie_status` 合并理解；前者回答“账号形态是否过时”，后者回答“工作 Cookie 现在是否能用”。
    upgrade_required: bool = False
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
    message: str = "请使用米游社 App 扫描二维码完成高权限登录"
