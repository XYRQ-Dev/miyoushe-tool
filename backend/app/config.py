"""
应用配置管理
通过环境变量或 .env 文件加载配置，敏感信息不硬编码
"""

import os
import secrets
from pathlib import Path
from pydantic_settings import BaseSettings


def detect_setting_source(setting_name: str, *, env_file: str | Path = ".env") -> str:
    """
    检测某个配置项来自哪里。

    这里专门给启动期诊断使用，只返回来源标签，不返回配置值本身：
    1. `environment` 表示来自进程环境变量
    2. `dotenv` 表示来自当前工作目录下的 `.env`
    3. `generated_default` 表示像 `ENCRYPTION_KEY` 这类安全敏感项仍在使用运行期随机默认值
    4. `default` 表示普通配置项使用代码内默认值
    """
    if os.environ.get(setting_name):
        return "environment"

    env_path = Path(env_file)
    if env_path.exists():
        try:
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                key, separator, _ = line.partition("=")
                if separator and key.strip() == setting_name:
                    return "dotenv"
        except OSError:
            pass

    if setting_name in {"SECRET_KEY", "ENCRYPTION_KEY"}:
        return "generated_default"
    return "default"


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

    # 数据库连接串
    # 默认值必须优先照顾“本机直接启动后端”的场景，因此这里使用 127.0.0.1，
    # 不能写 Docker Compose 内部服务名 `mysql`。否则开发者按 README 本地运行 uvicorn 时，
    # 会在没有容器内 DNS 的情况下直接因为主机名不存在而启动失败。
    # 容器部署再通过 docker-compose 显式覆盖成 `@mysql:3306`。
    DATABASE_URL: str = "mysql+asyncmy://miyoushe:change_me_mysql_password@127.0.0.1:3306/miyoushe?charset=utf8mb4"

    # 这里只在配置层暴露测试库变量名，方便部署文档、排障日志和 IDE 自动补全看到它。
    # 统一测试基座不能直接读取 `settings.TEST_DATABASE_URL`，因为 `settings` 会在 import 时缓存环境快照；
    # 而单测需要在同一进程里反复 patch 环境变量验证“缺失/非法必须失败”，因此测试代码必须直接读 `os.environ`。
    TEST_DATABASE_URL: str = ""

    # Cookie 加密密钥。
    # 这里保留随机默认值仅用于让旧测试与最小启动路径不至于直接崩溃；
    # 真实部署必须通过 `.env` 或环境变量显式固定，否则服务重启后旧密文会无法解密。
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
