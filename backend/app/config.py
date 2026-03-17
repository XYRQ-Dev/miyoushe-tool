"""
应用配置管理
通过环境变量或 .env 文件加载配置，敏感信息不硬编码
"""

import os
import secrets
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 应用基础配置
    APP_NAME: str = "米游社自动签到"
    DEBUG: bool = False
    APP_TIMEZONE: str = "Asia/Shanghai"

    # JWT 配置
    SECRET_KEY: str = secrets.token_urlsafe(32)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 小时
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # 数据库路径
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/miyoushe.db"

    # Cookie 加密密钥（AES-256，必须 32 字节 base64）
    ENCRYPTION_KEY: str = secrets.token_urlsafe(32)

    # SMTP 邮件配置
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_SSL: bool = True

    # 签到调度默认配置
    DEFAULT_CRON_HOUR: str = "6-8"
    DEFAULT_CRON_MINUTE: str = "0"

    # 米游社 API 版本
    MIHOYO_APP_VERSION: str = "2.71.1"
    MIHOYO_CLIENT_TYPE: str = "5"
    MIHOYO_SALT: str = "YVEIkzDFNHLeKXLxzqCA9TzxCpWwbIbk"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
