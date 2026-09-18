"""用户相关的 Pydantic 请求/响应模型"""

from typing import Optional
from pydantic import BaseModel, Field

from app.utils.timezone import ShanghaiDateTime


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=128, description="密码")
    # 邀请码只在系统开启时由服务端校验；这里放宽上限，避免超长请求在 schema 层暴露成和“码错误”不同的 422。
    invite_code: Optional[str] = Field(default=None, max_length=64, description="注册邀请码")


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    email_notify: bool = True
    notify_on: str = "always"
    role: str
    is_active: bool
    created_at: ShanghaiDateTime
    visible_menu_keys: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    email: Optional[str] = None
    email_notify: Optional[bool] = None
    notify_on: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: int
    username: str
    role: str
