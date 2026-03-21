import os
import sys
import tempfile
import types
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "mysql+asyncmy://demo:demo@127.0.0.1:3306/miyoushe?charset=utf8mb4"

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
    def test_database_module_no_longer_exposes_sqlite_compat_helpers(self):
        database_module = import_module("app.database")

        # Task 1 已经把运行时冻结为 MySQL-only，这里继续锁定导出面也必须一起收口。
        # 如果只删调用、不删符号，后续很容易又有人把旧补列逻辑从别处接回来，
        # 让“运行时修 SQLite 结构”这种已废弃路径借尸还魂。
        self.assertFalse(hasattr(database_module, "ensure_account_columns"))
        self.assertFalse(hasattr(database_module, "ensure_redeem_columns"))

    def test_sqlite_migration_module_is_no_longer_importable(self):
        # 迁移脚本与迁移模块一起下线，避免仓库继续暗示“SQLite 仍是受支持的升级路径”。
        # 这里只测 import 失败而不是测文件是否存在，是为了从调用者视角锁定真实公开行为。
        with self.assertRaises(ModuleNotFoundError):
            import_module("app.migrations.sqlite_to_mysql")

    def test_normalize_database_url_rejects_sqlite(self):
        from app.database import normalize_database_url

        # 这里先把“运行时不再偷偷接受 SQLite”钉死。
        # 否则后续有人为了让本地某条临时链路跑通，重新放开 SQLite 回退时，
        # 线上与测试环境会再次分叉，MySQL-only 重构就会被悄悄架空。
        with self.assertRaises(RuntimeError):
            normalize_database_url("sqlite:///tmp/demo.db")

    def test_get_mihoyo_account_legacy_column_ddls_only_returns_missing_columns(self):
        from app.database import get_mihoyo_account_legacy_column_ddls

        statements = get_mihoyo_account_legacy_column_ddls(
            {
                "id",
                "user_id",
                "cookie_encrypted",
                "stoken_encrypted",
                "ltoken_encrypted",
                "stuid",
                "mid",
                "cookie_status",
                "last_cookie_check",
                "cookie_token_updated_at",
                "last_refresh_attempt_at",
                "last_refresh_status",
                "last_refresh_message",
                "reauth_notified_at",
                "created_at",
            }
        )

        # 这里锁定“冷启动补列”只补旧库真实缺失的 Passport 根凭据字段，
        # 避免后续把整个 ORM 结构都粗暴翻译成启动期 DDL，扩大兼容逻辑的破坏面。
        self.assertEqual(
            statements,
            [
                "ALTER TABLE mihoyo_accounts ADD COLUMN cookie_token_encrypted TEXT NULL",
                "ALTER TABLE mihoyo_accounts ADD COLUMN login_ticket_encrypted TEXT NULL",
                "ALTER TABLE mihoyo_accounts ADD COLUMN credential_source VARCHAR(30) NULL",
                "ALTER TABLE mihoyo_accounts ADD COLUMN credential_status VARCHAR(30) NULL DEFAULT 'reauth_required'",
                "ALTER TABLE mihoyo_accounts ADD COLUMN last_token_refresh_at DATETIME NULL",
                "ALTER TABLE mihoyo_accounts ADD COLUMN last_token_refresh_status VARCHAR(30) NULL",
                "ALTER TABLE mihoyo_accounts ADD COLUMN last_token_refresh_message TEXT NULL",
            ],
        )

    def test_gacha_legacy_column_ddls_only_add_missing_game_uid(self):
        from app.database import (
            get_gacha_import_job_legacy_index_ddls,
            get_gacha_import_job_legacy_column_ddls,
            get_gacha_record_legacy_index_ddls,
            get_gacha_record_legacy_column_ddls,
        )

        # 抽卡旧库的兼容目标很窄：只补 `game_uid`，不在冷启动里偷偷扩散成索引/唯一键/历史回填大迁移。
        self.assertEqual(
            get_gacha_record_legacy_column_ddls(
                {
                    "id",
                    "account_id",
                    "game",
                    "record_id",
                    "pool_type",
                    "pool_name",
                    "item_name",
                    "item_type",
                    "rank_type",
                    "time_text",
                    "imported_at",
                }
            ),
            ["ALTER TABLE gacha_records ADD COLUMN game_uid VARCHAR(50) NULL"],
        )
        self.assertEqual(
            get_gacha_import_job_legacy_column_ddls(
                {
                    "id",
                    "account_id",
                    "game",
                    "source_url_masked",
                    "status",
                    "fetched_count",
                    "inserted_count",
                    "duplicate_count",
                    "message",
                    "created_at",
                }
            ),
            ["ALTER TABLE gacha_import_jobs ADD COLUMN game_uid VARCHAR(50) NULL"],
        )
        self.assertEqual(get_gacha_record_legacy_column_ddls({"game_uid"}), [])
        self.assertEqual(get_gacha_import_job_legacy_column_ddls({"game_uid"}), [])
        self.assertEqual(
            get_gacha_record_legacy_index_ddls(
                {
                    "uq_gacha_record_account_game_record",
                    "ix_gacha_records_account_id",
                    "ix_gacha_records_game",
                }
            ),
            [
                "ALTER TABLE gacha_records DROP INDEX uq_gacha_record_account_game_record",
                "ALTER TABLE gacha_records ADD UNIQUE INDEX uq_gacha_record_account_game_uid_record (account_id, game, game_uid, record_id)",
                "ALTER TABLE gacha_records ADD INDEX ix_gacha_records_game_uid (game_uid)",
            ],
        )
        self.assertEqual(
            get_gacha_import_job_legacy_index_ddls({"ix_gacha_import_jobs_account_id"}),
            ["ALTER TABLE gacha_import_jobs ADD INDEX ix_gacha_import_jobs_game_uid (game_uid)"],
        )
        self.assertEqual(
            get_gacha_record_legacy_index_ddls(
                {
                    "uq_gacha_record_account_game_uid_record",
                    "ix_gacha_records_game_uid",
                }
            ),
            [],
        )
        self.assertEqual(get_gacha_import_job_legacy_index_ddls({"ix_gacha_import_jobs_game_uid"}), [])

    def test_get_test_database_url_requires_mysql_asyncmy_url(self):
        mysql_test_case = import_module("tests.mysql_test_case")

        # 测试基座必须只接受显式传入的 MySQL 异步连接串。
        # 这里同时覆盖“缺失”和“前缀非法”两类误配，避免测试在开发机上静默回落到 SQLite，
        # 让用例看似稳定、实际却完全绕过了正式部署的数据库约束。
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_DATABASE_URL", None)
            with self.assertRaises(RuntimeError):
                mysql_test_case.get_test_database_url()

        with patch.dict(
            os.environ,
            {"TEST_DATABASE_URL": "sqlite+aiosqlite:///:memory:"},
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                mysql_test_case.get_test_database_url()

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
