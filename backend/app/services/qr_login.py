"""
米游社扫码登录服务
使用 Playwright 打开米游社登录页面，截取二维码，通过 WebSocket 推送给前端
"""

import asyncio
import base64
import json
import logging
from datetime import datetime
from typing import Optional, Dict

from playwright.async_api import BrowserContext, Page

from app.services.browser import browser_manager
from app.utils.crypto import encrypt_cookie

logger = logging.getLogger(__name__)

# 米游社登录页面 URL
MIYOUSHE_LOGIN_URL = "https://user.mihoyo.com/#/login/captcha"


class QrLoginSession:
    """
    单次扫码登录会话
    管理从打开登录页到提取 Cookie 的完整生命周期
    """

    def __init__(self, session_id: str, user_id: int):
        self.session_id = session_id
        self.user_id = user_id
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.status = "pending"  # pending / qr_ready / scanned / success / failed / timeout
        self.cookie_string: Optional[str] = None
        self.error_message: Optional[str] = None

    async def start(self):
        """启动登录会话：创建浏览器上下文，导航到登录页"""
        try:
            self.context = await browser_manager.create_context()
            self.page = await self.context.new_page()

            logger.info(f"[{self.session_id}] 正在打开米游社登录页面...")
            await self.page.goto(MIYOUSHE_LOGIN_URL, wait_until="networkidle", timeout=30000)

            # 等待页面加载完成
            await asyncio.sleep(2)

        except Exception as e:
            self.status = "failed"
            self.error_message = f"打开登录页面失败: {str(e)}"
            logger.error(f"[{self.session_id}] {self.error_message}")
            raise

    async def get_qr_image(self) -> Optional[str]:
        """
        切换到扫码登录并截取二维码图片
        返回 base64 编码的 PNG 图片
        """
        if not self.page:
            return None

        try:
            # 尝试点击"扫码登录"选项卡
            # 米游社登录页面可能有不同的布局，尝试多种选择器
            qr_tab_selectors = [
                'text="扫码登录"',
                '.tab-item:has-text("扫码登录")',
                '[class*="qr"]',
                'text="二维码登录"',
            ]

            for selector in qr_tab_selectors:
                try:
                    element = await self.page.wait_for_selector(selector, timeout=3000)
                    if element:
                        await element.click()
                        await asyncio.sleep(1)
                        break
                except Exception:
                    continue

            # 等待二维码出现
            await asyncio.sleep(2)

            # 截取二维码区域（尝试多种选择器定位二维码元素）
            qr_selectors = [
                'img[class*="qr"]',
                '.qr-code img',
                'canvas[class*="qr"]',
                '[class*="qrcode"]',
                '.login-qr img',
            ]

            qr_element = None
            for selector in qr_selectors:
                try:
                    qr_element = await self.page.wait_for_selector(selector, timeout=3000)
                    if qr_element:
                        break
                except Exception:
                    continue

            if qr_element:
                # 截取二维码元素
                screenshot = await qr_element.screenshot(type="png")
            else:
                # 找不到二维码元素时截取整个页面
                logger.warning(f"[{self.session_id}] 未找到二维码元素，截取整个页面")
                screenshot = await self.page.screenshot(type="png")

            self.status = "qr_ready"
            return base64.b64encode(screenshot).decode("utf-8")

        except Exception as e:
            self.status = "failed"
            self.error_message = f"获取二维码失败: {str(e)}"
            logger.error(f"[{self.session_id}] {self.error_message}")
            return None

    async def poll_login_status(self) -> str:
        """
        轮询登录状态
        检测页面是否跳转（表示登录成功）或出现新内容
        返回当前状态
        """
        if not self.page or self.status in ("success", "failed", "timeout"):
            return self.status

        try:
            current_url = self.page.url

            # 如果 URL 已经不是登录页面，说明登录成功
            if "login" not in current_url.lower() and "user.mihoyo.com" not in current_url:
                self.status = "success"
                return self.status

            # 检查页面内容是否有"已扫码"或"登录成功"的提示
            page_content = await self.page.content()
            if "已扫码" in page_content or "扫码成功" in page_content:
                self.status = "scanned"

            # 检查是否有用户信息出现（登录成功的标志）
            try:
                user_info = await self.page.wait_for_selector(
                    '[class*="user-info"], [class*="avatar"], [class*="nickname"]',
                    timeout=2000,
                )
                if user_info:
                    self.status = "success"
            except Exception:
                pass

            return self.status

        except Exception as e:
            logger.warning(f"[{self.session_id}] 轮询状态异常: {e}")
            return self.status

    async def extract_cookies(self) -> Optional[str]:
        """
        登录成功后提取所有 Cookie
        拼接成 key=value; 格式的字符串
        """
        if not self.context:
            return None

        try:
            cookies = await self.context.cookies()
            # 筛选米游社相关域名的 Cookie
            relevant_domains = [".mihoyo.com", ".miyoushe.com", ".hoyoverse.com"]
            filtered = [
                c for c in cookies
                if any(d in c.get("domain", "") for d in relevant_domains)
            ]

            if not filtered:
                # 如果筛选后为空，使用全部 Cookie
                filtered = cookies

            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in filtered)
            self.cookie_string = cookie_str
            return cookie_str

        except Exception as e:
            logger.error(f"[{self.session_id}] 提取 Cookie 失败: {e}")
            return None

    async def close(self):
        """关闭会话，释放浏览器资源"""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
        except Exception as e:
            logger.warning(f"[{self.session_id}] 关闭会话异常: {e}")
        finally:
            self.page = None
            self.context = None


class QrLoginManager:
    """管理所有活跃的扫码登录会话"""

    def __init__(self):
        self._sessions: Dict[str, QrLoginSession] = {}

    def create_session(self, session_id: str, user_id: int) -> QrLoginSession:
        session = QrLoginSession(session_id, user_id)
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[QrLoginSession]:
        return self._sessions.get(session_id)

    async def remove_session(self, session_id: str):
        session = self._sessions.pop(session_id, None)
        if session:
            await session.close()

    async def cleanup_expired(self, max_age_seconds: int = 180):
        """清理超时会话（默认 3 分钟）"""
        # 简单实现：清理所有非成功状态的会话
        expired = [
            sid for sid, s in self._sessions.items()
            if s.status not in ("success",)
        ]
        for sid in expired:
            await self.remove_session(sid)


# 全局单例
qr_login_manager = QrLoginManager()
