import os
import base64
import sys
import types
import unittest
from unittest.mock import AsyncMock

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

playwright_module = types.ModuleType("playwright")
playwright_async_api = types.ModuleType("playwright.async_api")
playwright_async_api.BrowserContext = object
playwright_async_api.Page = object
playwright_async_api.Frame = object
playwright_async_api.Browser = object
playwright_async_api.Playwright = object
playwright_async_api.async_playwright = AsyncMock()
playwright_module.async_api = playwright_async_api
sys.modules.setdefault("playwright", playwright_module)
sys.modules.setdefault("playwright.async_api", playwright_async_api)

crypto_module = types.ModuleType("app.utils.crypto")
crypto_module.encrypt_cookie = lambda value: value
sys.modules.setdefault("app.utils.crypto", crypto_module)

from app.services.qr_login import QrLoginSession


class QrLoginSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_qr_image_returns_canvas_screenshot_when_already_in_qr_mode(self):
        session = QrLoginSession("session-1", 1)
        session.page = AsyncMock()
        session.login_frame = types.SimpleNamespace(url="https://example.com/#/login/qr")
        qr_element = AsyncMock()
        qr_element.screenshot = AsyncMock(return_value=b"png-bytes")

        session.is_password_login_visible = AsyncMock(return_value=False)
        session.is_sms_login_visible = AsyncMock(return_value=False)
        session.switch_to_qr_mode = AsyncMock(return_value=True)
        session.find_qr_element = AsyncMock(return_value=("canvas", qr_element, 'canvas[class*="qr"]'))
        session.capture_debug_snapshot = AsyncMock()

        image = await session.get_qr_image()

        self.assertEqual(image, base64.b64encode(b"png-bytes").decode("utf-8"))
        self.assertEqual(session.status, "qr_ready")
        session.switch_to_qr_mode.assert_not_awaited()
        session.find_qr_element.assert_awaited_once()

    async def test_get_qr_image_switches_mode_before_capturing_qr(self):
        session = QrLoginSession("session-2", 1)
        session.page = AsyncMock()
        session.login_frame = types.SimpleNamespace(url="https://example.com/#/login/qr")
        qr_element = AsyncMock()
        qr_element.screenshot = AsyncMock(return_value=b"img-bytes")

        session.is_password_login_visible = AsyncMock(side_effect=[True, False])
        session.is_sms_login_visible = AsyncMock(return_value=False)
        session.switch_to_qr_mode = AsyncMock(return_value=True)
        session.find_qr_element = AsyncMock(return_value=("img", qr_element, '.qr-code img'))
        session.capture_debug_snapshot = AsyncMock()

        image = await session.get_qr_image()

        self.assertEqual(image, base64.b64encode(b"img-bytes").decode("utf-8"))
        session.switch_to_qr_mode.assert_awaited_once()
        self.assertEqual(session.is_password_login_visible.await_count, 2)

    async def test_get_qr_image_fails_when_page_stays_in_password_mode(self):
        session = QrLoginSession("session-3", 1)
        session.page = AsyncMock()
        session.login_frame = types.SimpleNamespace(url="https://example.com/#/login/captcha")
        session.is_password_login_visible = AsyncMock(side_effect=[True, True])
        session.is_sms_login_visible = AsyncMock(return_value=False)
        session.switch_to_qr_mode = AsyncMock(return_value=True)
        session.find_qr_element = AsyncMock()
        session.capture_debug_snapshot = AsyncMock()

        image = await session.get_qr_image()

        self.assertIsNone(image)
        self.assertEqual(session.status, "failed")
        self.assertIn("未进入扫码登录界面", session.error_message)
        session.find_qr_element.assert_not_awaited()

    async def test_get_qr_image_fails_when_qr_element_missing(self):
        session = QrLoginSession("session-4", 1)
        session.page = AsyncMock()
        session.login_frame = types.SimpleNamespace(url="https://example.com/#/login/qr")
        session.is_password_login_visible = AsyncMock(return_value=False)
        session.is_sms_login_visible = AsyncMock(return_value=False)
        session.switch_to_qr_mode = AsyncMock(return_value=True)
        session.find_qr_element = AsyncMock(return_value=(None, None, None))
        session.capture_debug_snapshot = AsyncMock()

        image = await session.get_qr_image()

        self.assertIsNone(image)
        self.assertEqual(session.status, "failed")
        self.assertIn("未找到二维码", session.error_message)
        session.capture_debug_snapshot.assert_awaited()


if __name__ == "__main__":
    unittest.main()
