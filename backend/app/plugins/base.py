"""
任务插件基类
可扩展的插件架构，便于未来添加更多任务类型（如观看视频、领取礼包等）
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class TaskPlugin(ABC):
    """任务插件基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """插件名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """插件描述"""
        pass

    @abstractmethod
    async def execute(self, cookie: str, **kwargs) -> Dict[str, Any]:
        """
        执行任务
        返回包含 status 和 message 的字典
        """
        pass
