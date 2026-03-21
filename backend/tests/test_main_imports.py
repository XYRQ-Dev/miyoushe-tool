import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

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


class MainModuleImportTests(unittest.TestCase):
    def test_qr_login_success_path_dependencies_are_imported(self):
        import app.main as main_module

        # 当前正式二维码登录成功链路已经切到 Passport 会话管理器 +
        # AccountCredentialService 统一落库入口。
        # 这里锁定的是“app.main 仍然暴露现行成功路径真正依赖的对象”，
        # 避免后续重构时测试继续盯着已退役的网页登录依赖面，导致误报或错误回滚。
        self.assertTrue(callable(main_module.AccountCredentialService))
        self.assertTrue(hasattr(main_module, "passport_login_manager"))

    def test_detect_setting_source_prefers_environment_then_dotenv(self):
        from app.config import detect_setting_source

        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("ENCRYPTION_KEY=from-dotenv\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("ENCRYPTION_KEY", None)
                self.assertEqual(detect_setting_source("ENCRYPTION_KEY", env_file=env_path), "dotenv")

            with patch.dict(os.environ, {"ENCRYPTION_KEY": "from-env"}, clear=False):
                self.assertEqual(detect_setting_source("ENCRYPTION_KEY", env_file=env_path), "environment")


if __name__ == "__main__":
    unittest.main()
