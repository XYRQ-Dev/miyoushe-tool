"""系统级配置相关的 Pydantic 模型"""

from typing import Optional

from pydantic import BaseModel, Field


class AdminEmailSettingsResponse(BaseModel):
    smtp_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_use_ssl: bool = True
    smtp_sender_name: str = ""
    smtp_sender_email: str = ""
    smtp_password_configured: bool = False


class AdminEmailSettingsUpdate(BaseModel):
    smtp_enabled: bool = False
    smtp_host: str = Field(default="", max_length=255)
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_user: str = Field(default="", max_length=255)
    smtp_password: Optional[str] = Field(default=None, max_length=255)
    smtp_use_ssl: bool = True
    smtp_sender_name: str = Field(default="", max_length=255)
    smtp_sender_email: str = Field(default="", max_length=255)
