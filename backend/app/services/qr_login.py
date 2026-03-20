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
RELEVANT_COOKIE_DOMAINS = (".mihoyo.com", ".miyoushe.com", ".hoyoverse.com")
STOKEN_COOKIE_KEYS = {"stoken", "stoken_v2"}
STUID_COOKIE_KEYS = {"stuid", "ltuid", "ltuid_v2", "account_id", "account_id_v2", "login_uid"}
MID_COOKIE_KEYS = {"mid", "ltmid_v2", "account_mid_v2"}


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
        self.captured_cookies: list[dict[str, Any]] = []
        self.error_message: Optional[str] = None
        self.last_qr_selector: Optional[str] = None
        self.last_qr_element_type: Optional[str] = None
        self.login_frame: Optional[Frame] = None
        # 与当前 main.py 成功分支兼容；网页登录成功时如果暂时拉不到角色，仍可回填米游社 UID。
        self.account_mihoyo_uid: Optional[str] = None

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
            ".qr-login-btn--wrapper",
            ".qr-login-btn",
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

            # 如果 URL 已经不是登录页面，说明登录成功。
            # 继续停留在 login/user.mihoyo.com 域通常仍表示处于登录流程中。
            if "login" not in current_url.lower() and "user.mihoyo.com" not in current_url:
                self.status = "success"
                return self.status

            page_content = await self.page.content()
            if "已扫码" in page_content or "扫码成功" in page_content:
                self.status = "scanned"

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
            filtered = await self._load_relevant_cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in filtered)
            self.cookie_string = cookie_str
            return cookie_str

        except Exception as e:
            logger.error(f"[{self.session_id}] 提取 Cookie 失败: {e}")
            return None

    async def extract_cookie_diagnostics(self, token_info: dict[str, str | None]) -> dict[str, Any]:
        """
        输出安全的 Cookie 诊断摘要。

        这里只记录键名与字段是否存在，绝不记录 Cookie 原值、stoken 原值或其他敏感信息，
        目的是回答“网页登录链路到底拿到了哪些字段”，而不是把高敏凭据写进日志。
        """
        cookies = self.captured_cookies or await self._load_relevant_cookies()
        cookie_names = sorted(
            {
                str(cookie.get("name") or "").strip()
                for cookie in cookies
                if str(cookie.get("name") or "").strip()
            }
        )
        stoken = token_info.get("stoken")
        return {
            "cookie_count": len(cookies),
            "cookie_names": cookie_names,
            "has_stoken_cookie": any(name in STOKEN_COOKIE_KEYS for name in cookie_names),
            "has_stuid_cookie": any(name in STUID_COOKIE_KEYS for name in cookie_names),
            "has_mid_cookie": any(name in MID_COOKIE_KEYS for name in cookie_names),
            "has_cookie_token": "cookie_token" in cookie_names,
            "has_login_ticket": "login_ticket" in cookie_names,
            "has_login_uid": "login_uid" in cookie_names,
            "has_game_token": "game_token" in cookie_names,
            "parsed_has_stoken": bool(stoken),
            "parsed_has_stuid": bool(token_info.get("stuid")),
            "parsed_has_mid": bool(token_info.get("mid")),
            "parsed_stoken_is_v2": bool(stoken and stoken.startswith("v2_")),
        }

    @staticmethod
    def _filter_relevant_cookies(cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        filtered = [
            cookie
            for cookie in cookies
            if any(domain in str(cookie.get("domain", "")) for domain in RELEVANT_COOKIE_DOMAINS)
        ]
        return filtered or cookies

    async def _load_relevant_cookies(self) -> list[dict[str, Any]]:
        if not self.context:
            return []
        cookies = await self.context.cookies()
        filtered = self._filter_relevant_cookies(cookies)
        # 这里缓存“本次成功登录时真正参与拼接 cookie_str 的那批 Cookie”，
        # 让后续诊断日志与正式落库使用的是同一份输入，避免再次读取浏览器状态导致结论漂移。
        self.captured_cookies = filtered
        return filtered

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
        expired = [
            sid for sid, session in self._sessions.items()
            if session.status not in ("success",)
        ]
        for sid in expired:
            await self.remove_session(sid)


qr_login_manager = QrLoginManager()
