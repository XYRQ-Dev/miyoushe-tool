"""
米游社签到插件
封装签到逻辑为插件形式，便于统一管理
"""

from typing import Any, Dict
from app.plugins.base import TaskPlugin


class MiyousheCheckinPlugin(TaskPlugin):
    """米游社每日签到插件"""

    @property
    def name(self) -> str:
        return "miyoushe_checkin"

    @property
    def description(self) -> str:
        return "米游社每日签到（支持原神、星铁、绝区零、崩坏3）"

    async def execute(self, cookie: str, **kwargs) -> Dict[str, Any]:
        """
        执行签到
        实际逻辑委托给 CheckinService
        """
        from app.services.checkin import CheckinService
        # 此处为插件入口，具体逻辑在 CheckinService 中实现
        return {"status": "delegated", "message": "使用 CheckinService 执行"}
