"""
Playwright 浏览器管理
- 全局单例管理 Playwright 实例和浏览器
- 每次扫码登录创建独立的 BrowserContext
- 超时自动清理未使用的上下文
"""

import asyncio
import logging
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Playwright

logger = logging.getLogger(__name__)


class BrowserManager:
    """
    浏览器管理器（单例）
    使用 headless Chromium，所有扫码登录共享同一个浏览器实例
    每次登录创建独立的 BrowserContext 隔离 Cookie 和存储
    """

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._lock = asyncio.Lock()

    async def get_browser(self) -> Browser:
        """获取或懒初始化浏览器实例"""
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                logger.info("正在启动 headless Chromium 浏览器...")
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
                logger.info("浏览器启动成功")
            return self._browser

    async def create_context(self) -> BrowserContext:
        """创建独立的浏览器上下文（隔离 Cookie 等状态）"""
        browser = await self.get_browser()
        context = await browser.new_context(
            # 米游社新版登录页在桌面视图中会通过 iframe 提供完整登录平台，
            # 包含二维码入口；继续伪装成移动端会落入短信登录页，根本拿不到扫码路径。
            viewport={"width": 1440, "height": 900},
        )
        return context

    async def close(self):
        """关闭浏览器和 Playwright 实例"""
        async with self._lock:
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
            logger.info("浏览器已关闭")


# 全局单例
browser_manager = BrowserManager()
