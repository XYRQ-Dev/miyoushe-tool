"""用户相关的 Pydantic 请求/响应模型"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=128, description="密码")


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
    created_at: datetime
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
