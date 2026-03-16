"""
系统配置服务

集中处理全局单例配置的读取与创建，避免多个服务各自“没有就自己造一份”，
从而导致数据库里出现多行配置或设备标识漂移。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_setting import SystemSetting


class SystemSettingsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create(self) -> SystemSetting:
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
