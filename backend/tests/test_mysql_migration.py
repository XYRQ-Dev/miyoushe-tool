import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, build_engine_kwargs, ensure_account_columns, normalize_database_url
from app.migrations.sqlite_to_mysql import CORE_TABLE_MIGRATION_ORDER, migrate_sqlite_core_data
from app.config import Settings
from app.models.account import GameRole, MihoyoAccount
from app.models.gacha import GachaImportJob, GachaRecord
from app.models.redeem import RedeemBatch, RedeemExecution
from app.models.system_setting import SystemSetting
from app.models.task_log import TaskConfig, TaskLog
from app.models.user import User
from app.utils.crypto import encrypt_cookie
from app.utils.timezone import utc_now_naive


class MySqlMigrationTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _sqlite_file_url(path: str) -> str:
        return f"sqlite+aiosqlite:///{Path(path).resolve().as_posix()}"

    @staticmethod
    def _create_temp_db_path() -> str:
        file_descriptor, path = tempfile.mkstemp(dir=os.getcwd(), suffix=".db")
        os.close(file_descriptor)
        return path

    def test_migration_cli_help_can_run_from_backend_root(self):
        completed = subprocess.run(
            [sys.executable, "scripts/migrate_sqlite_to_mysql.py", "--help"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        self.assertIn("迁移 SQLite 核心数据到 MySQL 8", completed.stdout)

    async def test_normalize_database_url_converts_mysql_scheme_to_asyncmy(self):
        self.assertEqual(
            normalize_database_url("mysql://demo:pwd@mysql:3306/miyoushe"),
            "mysql+asyncmy://demo:pwd@mysql:3306/miyoushe",
        )

    async def test_build_engine_kwargs_uses_mysql_pool_healthcheck_without_sqlite_flags(self):
        kwargs = build_engine_kwargs("mysql+asyncmy://demo:pwd@mysql:3306/miyoushe")

        self.assertNotIn("connect_args", kwargs)
        self.assertTrue(kwargs["pool_pre_ping"])
        self.assertEqual(kwargs["pool_recycle"], 3600)

    async def test_ensure_account_columns_backfills_high_privilege_credential_columns_for_legacy_sqlite(self):
        legacy_path = self._create_temp_db_path()
        try:
            legacy_engine = create_async_engine(
                self._sqlite_file_url(legacy_path),
                connect_args={"check_same_thread": False},
            )

            async with legacy_engine.begin() as conn:
                # 这里显式手工创建旧版 `mihoyo_accounts` 结构，而不是直接复用 ORM 建表，
                # 目的是锁定“补列逻辑能否把历史低权限库升级到当前高权限字段集合”这件事。
                # 如果后续有人误删补列项，最直接的后果不是新库创建失败，而是老库在读取账号时
                # 才因为缺列报错，排障会比建库阶段暴露问题更晚、更隐蔽。
                await conn.exec_driver_sql(
                    """
                    CREATE TABLE mihoyo_accounts (
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        nickname VARCHAR(100),
                        mihoyo_uid VARCHAR(50),
                        cookie_encrypted TEXT,
                        stoken_encrypted TEXT,
                        stuid VARCHAR(50),
                        mid VARCHAR(100),
                        cookie_status VARCHAR(20),
                        last_cookie_check DATETIME,
                        cookie_token_updated_at DATETIME,
                        last_refresh_attempt_at DATETIME,
                        last_refresh_status VARCHAR(30),
                        last_refresh_message TEXT,
                        reauth_notified_at DATETIME,
                        created_at DATETIME
                    )
                    """
                )

            await ensure_account_columns(legacy_engine)

            async with legacy_engine.begin() as conn:
                result = await conn.exec_driver_sql("PRAGMA table_info(mihoyo_accounts)")
                columns = {row[1] for row in result.fetchall()}

            self.assertIn("credential_status", columns)
            self.assertIn("credential_source", columns)
            self.assertIn("ltoken_encrypted", columns)
            self.assertIn("cookie_token_encrypted", columns)
            self.assertIn("login_ticket_encrypted", columns)
            self.assertIn("last_token_refresh_at", columns)
            self.assertIn("last_token_refresh_status", columns)
            self.assertIn("last_token_refresh_message", columns)

            await legacy_engine.dispose()
        finally:
            if os.path.exists(legacy_path):
                os.remove(legacy_path)

    async def test_settings_default_database_url_points_to_local_mysql(self):
        original_database_url = os.environ.pop("DATABASE_URL", None)
        try:
            settings = Settings(_env_file=None)
        finally:
            if original_database_url is not None:
                os.environ["DATABASE_URL"] = original_database_url

        self.assertIn("@127.0.0.1:3306", settings.DATABASE_URL)

    async def test_migrate_sqlite_core_data_only_moves_core_tables(self):
        source_path = self._create_temp_db_path()
        target_path = self._create_temp_db_path()
        try:
            source_engine = create_async_engine(
                self._sqlite_file_url(source_path),
                connect_args={"check_same_thread": False},
            )
            source_session_factory = async_sessionmaker(
                source_engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            async with source_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with source_session_factory() as session:
                user = User(username="mysql-migrate-user", password_hash="hash", role="user", is_active=True)
                session.add(user)
                await session.flush()

                account = MihoyoAccount(
                    user_id=user.id,
                    nickname="主账号",
                    mihoyo_uid="10001",
                    cookie_status="valid",
                    cookie_encrypted=encrypt_cookie("ltuid=10001; cookie_token=test-token"),
                    created_at=utc_now_naive(),
                )
                session.add(account)
                await session.flush()

                role = GameRole(
                    account_id=account.id,
                    game_biz="hk4e_cn",
                    game_uid="10001",
                    nickname="旅行者",
                    region="cn_gf01",
                    level=60,
                    is_enabled=True,
                )
                task_config = TaskConfig(user_id=user.id, cron_expr="0 7 * * *", is_enabled=True)
                setting = SystemSetting(
                    smtp_enabled=True,
                    smtp_host="smtp.example.com",
                    smtp_port=465,
                    smtp_user="mailer@example.com",
                    smtp_password_encrypted="encrypted",
                    smtp_sender_email="mailer@example.com",
                    smtp_sender_name="米游社工具",
                    smtp_use_ssl=True,
                    menu_visibility_json='{"gacha":{"user":false,"admin":true}}',
                    updated_at=utc_now_naive(),
                )
                session.add_all([role, task_config, setting])
                await session.flush()

                session.add(
                    TaskLog(
                        account_id=account.id,
                        game_role_id=role.id,
                        task_type="checkin",
                        status="success",
                        message="签到成功",
                        total_sign_days=10,
                        executed_at=utc_now_naive(),
                    )
                )
                session.add_all(
                    [
                        GachaImportJob(
                            account_id=account.id,
                            game="genshin",
                            source_url_masked="https://example.invalid?authkey=***",
                            status="success",
                            fetched_count=1,
                            inserted_count=1,
                            duplicate_count=0,
                            message="导入完成",
                        ),
                        GachaRecord(
                            account_id=account.id,
                            game="genshin",
                            record_id="1",
                            pool_type="301",
                            pool_name="角色活动祈愿",
                            item_name="刻晴",
                            item_type="角色",
                            rank_type="5",
                            time_text="2026-03-18 10:00:00",
                        ),
                    ]
                )
                await session.flush()

                batch = RedeemBatch(
                    user_id=user.id,
                    account_count=1,
                    game="genshin",
                    code="SPRING2026",
                    success_count=1,
                    already_redeemed_count=0,
                    invalid_code_count=0,
                    invalid_cookie_count=0,
                    error_count=0,
                    failed_count=0,
                    message="完成",
                    created_at=utc_now_naive(),
                )
                session.add(batch)
                await session.flush()
                session.add(
                    RedeemExecution(
                        batch_id=batch.id,
                        account_id=account.id,
                        game="genshin",
                        account_name="主账号",
                        role_uid="10001",
                        region="cn_gf01",
                        status="success",
                        upstream_code=0,
                        message="兑换成功",
                        executed_at=utc_now_naive(),
                    )
                )

                await session.commit()

            result = await migrate_sqlite_core_data(
                source_sqlite_path=source_path,
                target_database_url=self._sqlite_file_url(target_path),
            )

            self.assertEqual(
                CORE_TABLE_MIGRATION_ORDER,
                ("users", "mihoyo_accounts", "game_roles", "task_configs", "task_logs", "system_settings"),
            )
            self.assertEqual(result.migrated_row_counts["users"], 1)
            self.assertEqual(result.migrated_row_counts["mihoyo_accounts"], 1)
            self.assertEqual(result.migrated_row_counts["game_roles"], 1)
            self.assertEqual(result.migrated_row_counts["task_logs"], 1)
            self.assertEqual(result.migrated_row_counts["system_settings"], 1)
            self.assertEqual(result.validation_errors, [])

            target_engine = create_async_engine(
                self._sqlite_file_url(target_path),
                connect_args={"check_same_thread": False},
            )
            target_session_factory = async_sessionmaker(
                target_engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            async with target_session_factory() as session:
                self.assertEqual((await session.execute(select(func.count(User.id)))).scalar_one(), 1)
                self.assertEqual((await session.execute(select(func.count(MihoyoAccount.id)))).scalar_one(), 1)
                self.assertEqual((await session.execute(select(func.count(GameRole.id)))).scalar_one(), 1)
                self.assertEqual((await session.execute(select(func.count(TaskConfig.id)))).scalar_one(), 1)
                self.assertEqual((await session.execute(select(func.count(TaskLog.id)))).scalar_one(), 1)
                self.assertEqual((await session.execute(select(func.count(SystemSetting.id)))).scalar_one(), 1)
                self.assertEqual((await session.execute(select(func.count(GachaRecord.id)))).scalar_one(), 0)
                self.assertEqual((await session.execute(select(func.count(GachaImportJob.id)))).scalar_one(), 0)
                self.assertEqual((await session.execute(select(func.count(RedeemBatch.id)))).scalar_one(), 0)
                self.assertEqual((await session.execute(select(func.count(RedeemExecution.id)))).scalar_one(), 0)

                migrated_log = (await session.execute(select(TaskLog))).scalar_one()
                migrated_role = (await session.execute(select(GameRole))).scalar_one()
                migrated_setting = (await session.execute(select(SystemSetting))).scalar_one()
                self.assertEqual(migrated_log.game_role_id, migrated_role.id)
                self.assertEqual(migrated_setting.menu_visibility_json, '{"gacha":{"user":false,"admin":true}}')

            await target_engine.dispose()
            await source_engine.dispose()
        finally:
            for path in (source_path, target_path):
                if os.path.exists(path):
                    os.remove(path)

    async def test_migrate_sqlite_core_data_rejects_non_empty_target(self):
        source_path = self._create_temp_db_path()
        target_path = self._create_temp_db_path()
        try:
            source_engine = create_async_engine(
                self._sqlite_file_url(source_path),
                connect_args={"check_same_thread": False},
            )
            target_engine = create_async_engine(
                self._sqlite_file_url(target_path),
                connect_args={"check_same_thread": False},
            )

            async with source_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with target_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            target_session_factory = async_sessionmaker(
                target_engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            async with target_session_factory() as session:
                session.add(User(username="existing-target-user", password_hash="hash", role="user", is_active=True))
                await session.commit()

            with self.assertRaisesRegex(RuntimeError, "目标数据库不是空库"):
                await migrate_sqlite_core_data(
                    source_sqlite_path=source_path,
                    target_database_url=self._sqlite_file_url(target_path),
                )

            await target_engine.dispose()
            await source_engine.dispose()
        finally:
            for path in (source_path, target_path):
                if os.path.exists(path):
                    os.remove(path)

    async def test_migrate_sqlite_core_data_rolls_back_when_validation_fails(self):
        source_path = self._create_temp_db_path()
        target_path = self._create_temp_db_path()
        try:
            source_engine = create_async_engine(
                self._sqlite_file_url(source_path),
                connect_args={"check_same_thread": False},
            )
            target_engine = create_async_engine(
                self._sqlite_file_url(target_path),
                connect_args={"check_same_thread": False},
            )
            source_session_factory = async_sessionmaker(
                source_engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            target_session_factory = async_sessionmaker(
                target_engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            async with source_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with target_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with source_session_factory() as session:
                user = User(username="rollback-user", password_hash="hash", role="user", is_active=True)
                session.add(user)
                await session.flush()
                account = MihoyoAccount(
                    user_id=user.id,
                    nickname="回滚账号",
                    mihoyo_uid="10086",
                    cookie_status="valid",
                    cookie_encrypted=encrypt_cookie("ltuid=10086; cookie_token=test-token"),
                    created_at=utc_now_naive(),
                )
                session.add(account)
                await session.flush()
                role = GameRole(
                    account_id=account.id,
                    game_biz="hk4e_cn",
                    game_uid="10086",
                    nickname="回滚角色",
                    region="cn_gf01",
                    level=60,
                    is_enabled=True,
                )
                session.add(role)
                await session.flush()
                session.add(TaskConfig(user_id=user.id, cron_expr="0 6 * * *", is_enabled=True))
                session.add(
                    TaskLog(
                        account_id=account.id,
                        game_role_id=role.id,
                        task_type="checkin",
                        status="success",
                        message="签到成功",
                        total_sign_days=1,
                        executed_at=utc_now_naive(),
                    )
                )
                await session.commit()

            with patch(
                "app.migrations.sqlite_to_mysql._validate_core_relationships",
                new=AsyncMock(return_value=["task_logs.game_role_id 存在 1 条失效关联"]),
            ):
                with self.assertRaisesRegex(RuntimeError, "迁移校验失败"):
                    await migrate_sqlite_core_data(
                        source_sqlite_path=source_path,
                        target_database_url=self._sqlite_file_url(target_path),
                    )

            async with target_session_factory() as session:
                self.assertEqual((await session.execute(select(func.count(User.id)))).scalar_one(), 0)
                self.assertEqual((await session.execute(select(func.count(MihoyoAccount.id)))).scalar_one(), 0)
                self.assertEqual((await session.execute(select(func.count(GameRole.id)))).scalar_one(), 0)
                self.assertEqual((await session.execute(select(func.count(TaskLog.id)))).scalar_one(), 0)

            result = await migrate_sqlite_core_data(
                source_sqlite_path=source_path,
                target_database_url=self._sqlite_file_url(target_path),
            )
            self.assertEqual(result.validation_errors, [])
            self.assertEqual(result.migrated_row_counts["users"], 1)

            await target_engine.dispose()
            await source_engine.dispose()
        finally:
            for path in (source_path, target_path):
                if os.path.exists(path):
                    os.remove(path)
