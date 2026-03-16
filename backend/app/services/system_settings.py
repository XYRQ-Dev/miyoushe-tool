"""
系统配置服务

集中处理全局单例配置的读取与创建，避免多个服务各自“没有就自己造一份”，
从而导致数据库里出现多行配置或设备标识漂移。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_setting import SystemSetting


class SystemSettingsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def ensure_table_exists(self) -> None:
        """
        为旧部署补建 system_settings 表。

        本项目历史上没有迁移工具，线上很多实例是直接在旧 SQLite 库上升级代码。
        如果这里只依赖应用启动时的 `create_all()`，一旦进程未完全重启或旧库未补表，
        首次访问签到接口就会直接 500。这里按需补建，确保接口层对旧库具备自愈能力。
        """
        async with self.db.bind.begin() as conn:
            await conn.run_sync(SystemSetting.__table__.create, checkfirst=True)

    async def get_or_create(self) -> SystemSetting:
        try:
            result = await self.db.execute(
                select(SystemSetting).order_by(SystemSetting.id.asc()).limit(1)
            )
            config = result.scalar_one_or_none()
        except OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            await self.ensure_table_exists()
            result = await self.db.execute(
                select(SystemSetting).order_by(SystemSetting.id.asc()).limit(1)
            )
            config = result.scalar_one_or_none()

        if config is not None:
            return config

        config = SystemSetting(
            smtp_enabled=False,
            smtp_port=465,
            smtp_use_ssl=True,
            updated_at=datetime.utcnow(),
        )
        self.db.add(config)
        await self.db.flush()
        return config
