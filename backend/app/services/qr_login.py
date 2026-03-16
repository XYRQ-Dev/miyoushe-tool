"""
米游社扫码登录服务
使用 Playwright 打开米游社登录页面，截取二维码，通过 WebSocket 推送给前端
"""

import asyncio
import base64
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Tuple, Any

from playwright.async_api import BrowserContext, Page, Frame

from app.services.browser import browser_manager

logger = logging.getLogger(__name__)

# 米游社登录页面 URL
MIYOUSHE_LOGIN_URL = (
    "https://user.mihoyo.com/passport/index.html"
    "?legacy_env=production#/login?is_from_legacy=1"
)


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
        self.last_qr_selector: Optional[str] = None
        self.last_qr_element_type: Optional[str] = None
        self.login_frame: Optional[Frame] = None

    async def start(self):
        """启动登录会话：创建浏览器上下文，导航到登录页"""
        try:
            self.context = await browser_manager.create_context()
            self.page = await self.context.new_page()

            logger.info(f"[{self.session_id}] 正在打开米游社登录页面...")
            await self.page.goto(MIYOUSHE_LOGIN_URL, wait_until="networkidle", timeout=30000)

            # 新版页面先进入门户页，再通过 iframe 打开登录平台。
            # 只有先点主页的“登录”按钮并拿到 iframe，后续扫码/密码/短信模式切换才有统一入口。
            await self.ensure_login_frame()

        except Exception as e:
            self.status = "failed"
            self.error_message = f"打开登录页面失败: {str(e)}"
            logger.error(f"[{self.session_id}] {self.error_message}")
            raise

    async def ensure_login_frame(self) -> Optional[Frame]:
        """
        获取登录平台 iframe。
        新版米游社把登录弹层封装在 iframe 内，继续只在主页面查找元素会永远找不到二维码。
        """
        if not self.page:
            return None
        if self.login_frame:
            return self.login_frame

        try:
            login_button = self.page.get_by_role("button", name="登录").first
            await login_button.click(timeout=5000)
            await asyncio.sleep(1)
        except Exception:
            logger.info(f"[{self.session_id}] 首页登录按钮点击失败，尝试直接查找登录 iframe")

        for _ in range(10):
            frame = self.page.frame(url=lambda url: "login-platform" in url)
            if frame:
                self.login_frame = frame
                logger.info(f"[{self.session_id}] 已获取登录 iframe url={frame.url}")
                return frame
            await asyncio.sleep(0.5)

        logger.warning(f"[{self.session_id}] 未找到登录 iframe")
        return None

    async def is_password_login_visible(self) -> bool:
        """
        判断页面是否仍停留在账号密码登录态。
        这里显式检查表单元素，而不是依赖 URL 或泛化 class 规则，
        否则会把“登录页局部截图”误判成二维码，直接导致前端显示错误图片。
        """
        frame = await self.ensure_login_frame()
        if not frame:
            return False

        selectors = [
            'input[type="password"]',
            'input[placeholder*="密码"]',
            'input[placeholder*="手机号"]',
            'input[name*="password"]',
            'form input',
        ]

        for selector in selectors:
            try:
                element = await frame.query_selector(selector)
                if element:
                    return True
            except Exception:
                continue
        return False

    async def is_sms_login_visible(self) -> bool:
        """判断是否还停留在短信验证码登录态，用于确认扫码切换是否真正生效。"""
        frame = await self.ensure_login_frame()
        if not frame:
            return False

        selectors = [
            'input[placeholder*="手机号"]',
            'input[placeholder*="验证码"]',
            'text="获取验证码"',
            'text="短信登录"',
        ]
        for selector in selectors:
            try:
                element = await frame.query_selector(selector)
                if element:
                    return True
            except Exception:
                continue
        return False

    async def switch_to_qr_mode(self) -> bool:
        """
        显式切换到扫码登录界面。
        新版米游社把入口放在登录 iframe 左上角的二维码按钮中，
        这里只允许点击明确的扫码入口，避免继续误点到小图标或装饰元素。
        """
        frame = await self.ensure_login_frame()
        if not frame:
            return False

        selectors = [
            '.qr-login-btn--wrapper',
            '.qr-login-btn',
            'text="扫码登录"',
            'text="二维码登录"',
        ]

        for selector in selectors:
            try:
                element = await frame.wait_for_selector(selector, timeout=2500)
                if element:
                    await element.click(force=True)
                    await asyncio.sleep(1)
                    logger.info(f"[{self.session_id}] 已尝试点击扫码登录入口: {selector}")
                    return True
            except Exception:
                continue

        logger.warning(f"[{self.session_id}] 未找到扫码登录入口")
        return False

    async def find_qr_element(self) -> Tuple[Optional[str], Optional[Any], Optional[str]]:
        """
        查找真正的二维码元素。
        仅接受明确的二维码 canvas/img 节点，禁止退化成整页截图，
        否则即使“看起来有图”，前端也只能展示错误内容而不是可扫码二维码。
        """
        frame = await self.ensure_login_frame()
        if not frame:
            return None, None, None

        selectors = [
            ("img", 'img[class*="qr"]'),
            ("img", '[src*="/qr"]'),
            ("canvas", 'canvas[class*="qr"]'),
            ("canvas", '[class*="qrcode"] canvas'),
        ]

        for element_type, selector in selectors:
            try:
                element = await frame.wait_for_selector(selector, timeout=2500)
                if element:
                    bbox = await element.bounding_box()
                    # 二维码在当前页面中是大尺寸核心元素；
                    # 如果宽高仍然只有几十像素，几乎可以确定命中的是角标/装饰图标，不能返回给前端。
                    if not bbox or bbox["width"] < 120 or bbox["height"] < 120:
                        logger.info(
                            f"[{self.session_id}] 忽略非二维码候选 selector={selector} bbox={bbox}"
                        )
                        continue
                    self.last_qr_selector = selector
                    self.last_qr_element_type = element_type
                    return element_type, element, selector
            except Exception:
                continue
        return None, None, None

    async def capture_debug_snapshot(self, reason: str):
        """
        仅在排障时写入临时目录快照，避免把调试图发给前端污染用户界面。
        文件落在系统临时目录，既不进入仓库，也不参与正常业务返回。
        """
        if not self.page:
            return

        try:
            debug_dir = Path(tempfile.gettempdir()) / "miyoushe-tool" / "qr-login-debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            screenshot_path = debug_dir / f"{self.session_id}-{timestamp}.png"
            await self.page.screenshot(path=str(screenshot_path), type="png")
            logger.warning(
                f"[{self.session_id}] 已保存调试快照 reason={reason} path={screenshot_path}"
            )
        except Exception as e:
            logger.warning(f"[{self.session_id}] 保存调试快照失败: {e}")

    async def get_qr_image(self) -> Optional[str]:
        """
        切换到扫码登录并截取二维码图片
        返回 base64 编码的 PNG 图片
        """
        if not self.page:
            return None

        try:
            password_login_visible = await self.is_password_login_visible()
            logger.info(
                f"[{self.session_id}] 获取二维码前状态 url={self.page.url} "
                f"frame_url={(self.login_frame.url if self.login_frame else None)} "
                f"password_login_visible={password_login_visible}"
            )

            if password_login_visible or await self.is_sms_login_visible():
                switched = await self.switch_to_qr_mode()
                if not switched:
                    self.status = "failed"
                    self.error_message = "未找到扫码登录入口，请稍后重试"
                    await self.capture_debug_snapshot("qr-entry-not-found")
                    logger.error(f"[{self.session_id}] {self.error_message}")
                    return None

                await asyncio.sleep(2)
                password_login_visible = await self.is_password_login_visible()
                sms_login_visible = await self.is_sms_login_visible()
                logger.info(
                    f"[{self.session_id}] 切换扫码模式后状态 url={self.page.url} "
                    f"frame_url={(self.login_frame.url if self.login_frame else None)} "
                    f"password_login_visible={password_login_visible} "
                    f"sms_login_visible={sms_login_visible}"
                )
                if password_login_visible or sms_login_visible:
                    self.status = "failed"
                    self.error_message = "未进入扫码登录界面，请稍后重试"
                    await self.capture_debug_snapshot("still-password-login")
                    logger.error(f"[{self.session_id}] {self.error_message}")
                    return None

            element_type, qr_element, selector = await self.find_qr_element()
            logger.info(
                f"[{self.session_id}] 二维码元素检测结果 selector={selector} "
                f"element_type={element_type}"
            )
            if not qr_element or not element_type:
                self.status = "failed"
                self.error_message = "未找到二维码，请重试"
                await self.capture_debug_snapshot("qr-element-missing")
                logger.error(f"[{self.session_id}] {self.error_message}")
                return None

            screenshot = await qr_element.screenshot(type="png")

            self.status = "qr_ready"
            return base64.b64encode(screenshot).decode("utf-8")

        except Exception as e:
            self.status = "failed"
            self.error_message = f"获取二维码失败: {str(e)}"
            await self.capture_debug_snapshot("qr-image-exception")
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
