import os
import json
import unittest
from datetime import datetime, timedelta, timezone, date
from email.header import decode_header
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "mysql+asyncmy://demo:demo@127.0.0.1:3306/miyoushe?charset=utf8mb4"

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_me, get_register_options, register
from app.api.admin import (
    get_email_settings,
    get_invite_code_settings,
    get_menu_visibility,
    send_broadcast_email,
    update_email_settings,
    update_invite_code_settings,
    update_menu_visibility,
)
from app.api.accounts import list_accounts, refresh_login_state
from app.api.logs import get_sign_calendar, list_logs
from app.api.tasks import execute_checkin, get_task_config, get_today_status, update_task_config
from app.models.account import GameRole, MihoyoAccount
from app.models.admin_operation_log import AdminOperationLog
from app.models.system_setting import SystemSetting
from app.models.task_log import TaskConfig, TaskLog
from app.models.user import User
from app.schemas.admin_notification import (
    AdminBroadcastEmailFailure,
    AdminBroadcastEmailRequest,
    AdminBroadcastEmailResponse,
)
from app.schemas.system_setting import (
    AdminEmailSettingsUpdate,
    AdminInviteCodeSettingsUpdate,
    AdminMenuVisibilityItemUpdate,
    AdminMenuVisibilityUpdate,
)
from app.schemas.task_log import CheckinSummary, CheckinResult, TaskConfigCreate
from app.schemas.user import UserCreate
from app.services.admin_broadcast import AdminBroadcastService
from app.services.checkin import CHECKIN_GAME_CONFIGS, CheckinApiError, CheckinGameConfig, CheckinService
from app.services.geetest import GENERIC_RISK_MESSAGE, GEETEST_RISK_MESSAGE
from app.services.login_state import LoginStateService
from app.services.notifier import NotificationService
from app.services.scheduler import ScheduleRegistrationError, ScheduleRegistrationResult, SchedulerService
from app.services.system_settings import SystemSettingsService
from app.utils.timezone import SHANGHAI, utc_now, utc_now_naive
from app.utils.crypto import decrypt_text, encrypt_text
from app.utils.device import HYPERION_APP_VERSION
from tests.mysql_test_case import MySqlIsolatedAsyncioTestCase


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, *, get_payload=None, post_payload=None, get_payloads_by_url=None):
        self.get_payload = get_payload
        self.post_payload = post_payload
        self.get_payloads_by_url = get_payloads_by_url or {}
        self.last_get = None
        self.last_post = None
        self.get_calls = []
        self.post_calls = []

    async def get(self, url, **kwargs):
        self.last_get = {"url": url, **kwargs}
        self.get_calls.append(self.last_get)
        payload = self.get_payloads_by_url.get(url, self.get_payload)
        return FakeResponse(payload)

    async def post(self, url, **kwargs):
        self.last_post = {"url": url, **kwargs}
        self.post_calls.append(self.last_post)
        return FakeResponse(self.post_payload)


class CheckinAndAdminTests(MySqlIsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if hasattr(SystemSettingsService, "_storage_ready_sync_engines"):
            SystemSettingsService._storage_ready_sync_engines.clear()
        await super().asyncSetUp()
        # 注册用例使用独立且暂停的调度器，避免全局任务泄漏或触发真实签到
        self.registration_scheduler = SchedulerService()
        self.registration_scheduler.scheduler.start(paused=True)
        self.registration_scheduler._started = True
        registration_patch = patch("app.api.auth.scheduler_service", self.registration_scheduler)
        registration_patch.start()
        self.addCleanup(registration_patch.stop)

    async def asyncTearDown(self):
        self.registration_scheduler.stop()
        if hasattr(SystemSettingsService, "_storage_ready_sync_engines"):
            SystemSettingsService._storage_ready_sync_engines.clear()
        await super().asyncTearDown()

    async def _create_user(self, session: AsyncSession, username: str) -> User:
        # SQLite 时代不少测试直接把 `user_id=1` 塞给账号夹具也能混过去，
        # 但 MySQL-only 后外键会真实校验 `mihoyo_accounts.user_id -> users.id`。
        # 这里统一显式建父用户，避免后续有人又把“业务失败”与“测试夹具先违法 FK”混在一起。
        user = User(username=username, password_hash="x", role="user", is_active=True)
        session.add(user)
        await session.flush()
        await session.refresh(user)
        return user

    async def test_register_creates_default_task_config(self):
        async with await self._new_session() as session:
            user = await register(
                UserCreate(username="new-user", password="password123"),
                db=session,
            )

            config = (
                await session.execute(select(TaskConfig).where(TaskConfig.user_id == user.id))
            ).scalar_one()

        self.assertEqual(config.cron_expr, "0 6 * * *")
        self.assertTrue(config.is_enabled)

        runtime = self.registration_scheduler.get_user_schedule_status(user.id, enabled=True)
        self.assertTrue(runtime.job_registered)
        self.assertIsNotNone(runtime.next_run_time)
        job = self.registration_scheduler.scheduler.get_job(runtime.job_id)
        self.assertEqual(job.trigger.timezone, SHANGHAI)

    async def test_register_commits_user_and_config_before_registering_schedule(self):
        service = self.registration_scheduler
        original_add = service._add_job

        async def verify_committed(user_id, config):
            async with await self._new_session() as verify_session:
                self.assertIsNotNone(await verify_session.get(User, user_id))
                stored = (await verify_session.execute(
                    select(TaskConfig).where(TaskConfig.user_id == user_id)
                )).scalar_one()
                self.assertEqual(stored.cron_expr, config.cron_expr)
            return await original_add(user_id, config)

        async with await self._new_session() as session:
            with patch.object(service, "_add_job", side_effect=verify_committed) as add:
                await register(UserCreate(username="committed-schedule", password="password123"), db=session)
            add.assert_awaited_once()

    async def test_register_commit_failure_does_not_register_schedule(self):
        async with await self._new_session() as session:
            with patch.object(session, "commit", new=AsyncMock(side_effect=RuntimeError("commit failed"))), patch.object(
                self.registration_scheduler, "ensure_user_schedule", new=AsyncMock(),
            ) as ensure:
                with self.assertRaisesRegex(RuntimeError, "commit failed"):
                    await register(UserCreate(username="failed-commit", password="password123"), db=session)
                ensure.assert_not_awaited()
            await session.rollback()
        async with await self._new_session() as session:
            self.assertEqual((await session.execute(select(func.count(User.id)))).scalar_one(), 0)
            self.assertEqual((await session.execute(select(func.count(TaskConfig.id)))).scalar_one(), 0)

    async def test_register_scheduler_failure_succeeds_and_get_retries(self):
        service = self.registration_scheduler
        async with await self._new_session() as session:
            with patch.object(service.scheduler, "add_job", side_effect=RuntimeError("scheduler unavailable")):
                registered = await register(
                    UserCreate(username="retry-schedule", password="password123"), db=session,
                )
                user = await session.get(User, registered.id)
                with patch("app.api.tasks.scheduler_service", service):
                    failed = await get_task_config(current_user=user, db=session)
                self.assertFalse(failed.job_registered)
                self.assertIsNone(failed.next_run_time)
                self.assertIn("scheduler unavailable", failed.scheduler_error)
            with patch("app.api.tasks.scheduler_service", service):
                recovered = await get_task_config(current_user=user, db=session)
                job = service.scheduler.get_job(recovered.job_id)
                again = await get_task_config(current_user=user, db=session)
            self.assertTrue(recovered.job_registered)
            self.assertIsNone(recovered.scheduler_error)
            self.assertEqual(again.next_run_time, recovered.next_run_time)
            self.assertIs(service.scheduler.get_job(recovered.job_id), job)
            self.assertEqual(len(service.scheduler.get_jobs()), 1)

    async def test_get_task_config_creates_historical_config_and_recovers_job(self):
        async with await self._new_session() as session:
            user = await self._create_user(session, "historical-schedule")
            await session.commit()
            with patch("app.api.tasks.scheduler_service", self.registration_scheduler):
                response = await get_task_config(current_user=user, db=session)
            self.assertTrue(response.job_registered)
            self.assertEqual(response.cron_expr, "0 6 * * *")
            self.assertIsNotNone(response.next_run_time)
        async with await self._new_session() as session:
            self.assertEqual((await session.execute(select(func.count(TaskConfig.id)))).scalar_one(), 1)

    async def test_get_task_config_preserves_disabled_and_custom_config(self):
        async with await self._new_session() as session:
            user = await self._create_user(session, "disabled-schedule")
            config = TaskConfig(user_id=user.id, cron_expr="15 9 * * *", is_enabled=False)
            session.add(config)
            await session.commit()
            with patch("app.api.tasks.scheduler_service", self.registration_scheduler):
                disabled = await get_task_config(current_user=user, db=session)
                self.assertFalse(disabled.job_registered)
                self.assertEqual(disabled.cron_expr, "15 9 * * *")
                config.is_enabled = True
                await session.commit()
                enabled = await get_task_config(current_user=user, db=session)
            self.assertTrue(enabled.job_registered)
            self.assertEqual(enabled.cron_expr, "15 9 * * *")

    async def test_ensure_schedule_skips_inactive_user_and_reports_stopped_scheduler(self):
        config = TaskConfig(user_id=7, cron_expr="0 6 * * *", is_enabled=True)
        service = SchedulerService()
        inactive = await service.ensure_user_schedule(config, user_active=False)
        self.assertFalse(inactive.job_registered)
        self.assertEqual(service.scheduler.get_jobs(), [])
        stopped = await service.ensure_user_schedule(config, user_active=True)
        self.assertFalse(stopped.job_registered)
        self.assertIsNone(stopped.next_run_time)
        self.assertIn("尚未启动", stopped.scheduler_error)

    async def test_register_returns_visible_menu_keys_consistent_with_get_me(self):
        async with await self._new_session() as session:
            # 首个注册用户按产品约定会自动升为管理员。
            # 这里先放一个已存在用户，确保本用例验证的是“普通用户注册后的菜单可见性”。
            session.add(User(username="bootstrap-admin", password_hash="x", role="admin", is_active=True))
            await session.commit()

            registered = await register(
                UserCreate(username="visible-menu-user", password="password123"),
                db=session,
            )
            db_user = (
                await session.execute(select(User).where(User.id == registered.id))
            ).scalar_one()
            me = await get_me(current_user=db_user, db=session)

        self.assertEqual(registered.visible_menu_keys, me.visible_menu_keys)
        self.assertIn("dashboard", registered.visible_menu_keys)
        self.assertNotIn("admin_users", registered.visible_menu_keys)
        self.assertNotIn("admin_menu_management", registered.visible_menu_keys)

    async def test_get_me_persists_system_settings_for_new_database(self):
        async with await self._new_session() as session:
            user = User(username="persist-settings-user", password_hash="x", role="admin", is_active=True)
            session.add(user)
            await session.commit()
            await session.refresh(user)

            response = await get_me(current_user=user, db=session)

        self.assertIn("dashboard", response.visible_menu_keys)

        async with await self._new_session() as verify_session:
            settings_count = (
                await verify_session.execute(select(func.count(SystemSetting.id)))
            ).scalar_one()

        self.assertEqual(settings_count, 1)

    async def test_register_persists_system_settings_response_side_effect(self):
        async with await self._new_session() as session:
            response = await register(
                UserCreate(username="persist-register-settings", password="password123"),
                db=session,
            )

        self.assertIn("dashboard", response.visible_menu_keys)

        async with await self._new_session() as verify_session:
            settings_count = (
                await verify_session.execute(select(func.count(SystemSetting.id)))
            ).scalar_one()

        self.assertEqual(settings_count, 1)

    async def test_get_or_create_persists_system_settings_without_committing_unrelated_session_changes(self):
        async with await self._new_session() as session:
            # MySQL-only 测试下外键会真实生效，不能再像旧 SQLite 用例那样假设 `user_id=1`
            # 必然存在；这里必须先落真实用户，才能把“系统配置初始化不会提前提交账号脏数据”
            # 与“测试夹具本身违反外键约束”区分开。
            user = User(username="txn-boundary-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()

            account = MihoyoAccount(user_id=user.id, nickname="事务边界账号", cookie_status="valid")
            session.add(account)
            await session.commit()
            await session.refresh(account)

            account.cookie_status = "expired"
            account.last_refresh_status = "failed"
            account.last_refresh_message = "不应被提前提交"

            config = await SystemSettingsService(session).get_or_create()
            self.assertFalse(config.smtp_enabled)

        async with await self._new_session() as verify_session:
            settings_count = (
                await verify_session.execute(select(func.count(SystemSetting.id)))
            ).scalar_one()
            stored_account = (
                await verify_session.execute(select(MihoyoAccount).where(MihoyoAccount.id == account.id))
            ).scalar_one()

        self.assertEqual(settings_count, 1)
        self.assertEqual(stored_account.cookie_status, "valid")
        self.assertIsNone(stored_account.last_refresh_status)
        self.assertIsNone(stored_account.last_refresh_message)

    async def test_system_settings_storage_preparation_runs_once_and_get_or_create_avoids_schema_inspection_hot_path(self):
        async with await self._new_session() as session:
            service = SystemSettingsService(session)

            with patch.object(
                SystemSettingsService,
                "ensure_table_exists",
                new=AsyncMock(),
            ) as mock_ensure_table_exists, patch.object(
                SystemSettingsService,
                "ensure_required_columns",
                new=AsyncMock(),
            ) as mock_ensure_required_columns:
                await service.ensure_storage_ready()
                mock_ensure_table_exists.assert_awaited_once()
                mock_ensure_required_columns.assert_awaited_once()

                mock_ensure_table_exists.reset_mock()
                mock_ensure_required_columns.reset_mock()

                config = await service.get_or_create()
                self.assertFalse(config.smtp_enabled)
                mock_ensure_table_exists.assert_not_awaited()
                mock_ensure_required_columns.assert_not_awaited()

                await service.ensure_storage_ready()
                mock_ensure_table_exists.assert_not_awaited()
                mock_ensure_required_columns.assert_not_awaited()

    async def test_scheduler_load_all_schedules_creates_missing_default_config_and_registers_job(self):
        async with await self._new_session() as session:
            user = User(username="missing-config-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.commit()
            await session.refresh(user)

        service = SchedulerService()
        service.scheduler.start()
        try:
            with patch("app.services.scheduler.async_session", self.session_factory):
                await service._load_all_schedules()

            async with await self._new_session() as verify_session:
                config = (await verify_session.execute(select(TaskConfig))).scalar_one()

            self.assertEqual(config.cron_expr, "0 6 * * *")
            self.assertTrue(config.is_enabled)
            # MySQL 测试基座当前只清空数据、不重置 AUTO_INCREMENT；
            # 若把 job id 写死为 `checkin_user_1`，前序用例留下的自增序列会让“任务已注册”被误判成失败。
            self.assertIsNotNone(service.scheduler.get_job(f"checkin_user_{user.id}"))
        finally:
            service.stop()

    async def test_scheduler_load_skips_inactive_users_without_changing_config(self):
        async with await self._new_session() as session:
            user = await self._create_user(session, "inactive-schedule")
            user.is_active = False
            session.add(TaskConfig(user_id=user.id, cron_expr="20 8 * * *", is_enabled=True))
            await session.commit()
        service = self.registration_scheduler
        with patch("app.services.scheduler.async_session", self.session_factory):
            await service._load_all_schedules()
        self.assertEqual(service.scheduler.get_jobs(), [])
        async with await self._new_session() as session:
            config = (await session.execute(select(TaskConfig))).scalar_one()
            self.assertTrue(config.is_enabled)
            self.assertEqual(config.cron_expr, "20 8 * * *")

    async def test_scheduler_update_user_schedule_registers_job_and_returns_next_run_time(self):
        service = SchedulerService()
        service.scheduler.start()
        try:
            config = TaskConfig(user_id=7, cron_expr="0 6 * * *", is_enabled=True)

            result = await service.update_user_schedule(7, config)

            self.assertTrue(result.job_registered)
            self.assertEqual(result.job_id, "checkin_user_7")
            self.assertIsNotNone(result.next_run_time)
            self.assertIsNone(result.scheduler_error)
            self.assertIsNotNone(service.scheduler.get_job("checkin_user_7"))
        finally:
            service.stop()

    async def test_scheduler_update_user_schedule_rejects_invalid_cron_expression(self):
        service = SchedulerService()
        service.scheduler.start()
        try:
            config = TaskConfig(user_id=8, cron_expr="0 6 * * *", is_enabled=True)
            await service.update_user_schedule(8, config)
            old_job = service.scheduler.get_job("checkin_user_8")
            old_trigger = old_job.trigger
            config.cron_expr = "bad cron"

            with self.assertRaises(ScheduleRegistrationError) as ctx:
                await service.update_user_schedule(8, config)
            self.assertIs(service.scheduler.get_job("checkin_user_8"), old_job)
            self.assertIs(old_job.trigger, old_trigger)
        finally:
            service.stop()

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Cron 表达式无效", str(ctx.exception))

    async def test_scheduler_update_user_schedule_disabling_removes_existing_job(self):
        service = SchedulerService()
        service.scheduler.start()
        try:
            config = TaskConfig(user_id=9, cron_expr="0 6 * * *", is_enabled=True)
            await service.update_user_schedule(9, config)
            config.is_enabled = False

            result = await service.update_user_schedule(9, config)

            self.assertFalse(result.job_registered)
            self.assertFalse(result.enabled)
            self.assertIsNone(result.next_run_time)
            self.assertIsNone(service.scheduler.get_job("checkin_user_9"))
        finally:
            service.stop()

    async def test_scheduler_execute_checkin_uses_delay_within_one_minute_and_still_notifies(self):
        service = SchedulerService()
        expected_summary = CheckinSummary(
            total=1,
            success=1,
            failed=0,
            already_signed=0,
            risk=0,
            results=[CheckinResult(account_id=1, status="success", message="ok")],
        )

        with patch("app.services.scheduler.async_session", self.session_factory), patch(
            "app.services.scheduler.random.uniform",
            return_value=12.5,
        ) as mock_uniform, patch(
            "asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep, patch(
            "app.services.scheduler.CheckinService",
        ) as mock_checkin_cls, patch(
            "app.services.notifier.notification_service.send_checkin_report",
            new_callable=AsyncMock,
        ) as mock_send_report:
            mock_checkin = mock_checkin_cls.return_value
            mock_checkin.execute_for_user = AsyncMock(return_value=expected_summary)

            await service._execute_checkin(42)

        mock_uniform.assert_called_once_with(0, 60)
        mock_sleep.assert_awaited_once_with(12.5)
        mock_checkin.execute_for_user.assert_awaited_once_with(42)
        mock_send_report.assert_awaited_once()
        self.assertEqual(mock_send_report.await_args.args[0], 42)
        self.assertEqual(mock_send_report.await_args.args[1], expected_summary)
        self.assertEqual(mock_send_report.await_args.kwargs["source"], "scheduled_checkin")

    async def test_update_task_config_returns_scheduler_runtime_fields(self):
        async with await self._new_session() as session:
            user = User(username="task-config-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.commit()
            await session.refresh(user)

            expected_result = ScheduleRegistrationResult(
                enabled=True,
                job_registered=True,
                job_id=f"checkin_user_{user.id}",
                next_run_time=datetime(2026, 3, 18, 6, 0, tzinfo=SHANGHAI),
                scheduler_error=None,
            )

            with patch(
                "app.api.tasks.scheduler_service.update_user_schedule",
                new=AsyncMock(return_value=expected_result),
            ):
                response = await update_task_config(
                    TaskConfigCreate(cron_expr="0 6 * * *", is_enabled=True),
                    current_user=user,
                    db=session,
                )

        self.assertTrue(response.job_registered)
        self.assertEqual(response.job_id, f"checkin_user_{user.id}")
        self.assertEqual(response.next_run_time, expected_result.next_run_time)
        self.assertEqual(response.next_run_time.utcoffset(), timedelta(hours=8))
        self.assertIsNone(response.scheduler_error)

    async def test_update_task_config_raises_http_error_for_invalid_cron(self):
        async with await self._new_session() as session:
            user = User(username="invalid-cron-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.commit()
            await session.refresh(user)

            with patch(
                "app.api.tasks.scheduler_service.update_user_schedule",
                new=AsyncMock(side_effect=ScheduleRegistrationError("Cron 表达式无效: bad cron", status_code=400)),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    await update_task_config(
                        TaskConfigCreate(cron_expr="bad cron", is_enabled=True),
                        current_user=user,
                        db=session,
                    )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Cron 表达式无效", ctx.exception.detail)

    async def test_build_checkin_headers_include_starward_required_fields(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            headers = service._build_checkin_headers(
                "ltuid=1;",
                device_id="device-id",
                device_fp="device-fp",
                config=CheckinGameConfig(act_id="e202304121516551", sign_game="hkrpg"),
            )

        self.assertEqual(headers["x-rpc-signgame"], "hkrpg")
        self.assertEqual(headers["x-rpc-device_id"], "device-id")
        self.assertEqual(headers["x-rpc-device_fp"], "device-fp")
        self.assertEqual(headers["x-rpc-app_version"], HYPERION_APP_VERSION)
        self.assertIn("miHoYoBBS", headers["User-Agent"])
        self.assertTrue(headers["DS"])

    async def test_build_checkin_headers_omits_bh3_signgame_and_uses_bh3_referer(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            headers = service._build_checkin_headers(
                "ltuid=1;",
                device_id="device-id",
                device_fp="device-fp",
                config=CheckinGameConfig(
                    act_id="e202306201626331",
                    sign_game="bh3",
                    send_sign_game=False,
                    referer="https://webstatic.mihoyo.com/bbs/event/signin/bh3/index.html?bbs_auth_required=true&act_id=e202306201626331&bbs_presentation_style=fullscreen&utm_source=bbs&utm_medium=mys&utm_campaign=icon",
                ),
            )

        self.assertNotIn("x-rpc-signgame", headers)
        self.assertEqual(headers["Referer"], "https://webstatic.mihoyo.com/bbs/event/signin/bh3/index.html?bbs_auth_required=true&act_id=e202306201626331&bbs_presentation_style=fullscreen&utm_source=bbs&utm_medium=mys&utm_campaign=icon")

    async def test_build_checkin_headers_supports_zzz_signgame(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            headers = service._build_checkin_headers(
                "ltuid=1;",
                device_id="device-id",
                device_fp="device-fp",
                config=CheckinGameConfig(
                    act_id="e202406242138391",
                    sign_game="zzz",
                    info_url="https://act-nap-api.mihoyo.com/event/luna/zzz/info",
                    sign_url="https://act-nap-api.mihoyo.com/event/luna/zzz/sign",
                    rewards_url="https://act-nap-api.mihoyo.com/event/luna/zzz/home",
                ),
            )

        self.assertEqual(headers["x-rpc-signgame"], "zzz")

    async def test_bh3_cn_uses_expected_checkin_game_config(self):
        config = CHECKIN_GAME_CONFIGS.get("bh3_cn")

        self.assertIsNotNone(config)
        self.assertEqual(config.act_id, "e202306201626331")
        self.assertEqual(config.sign_game, "bh3")
        self.assertFalse(config.send_sign_game)
        self.assertIn("act_id=e202306201626331", config.referer)

    async def test_nap_cn_uses_expected_checkin_game_config(self):
        config = CHECKIN_GAME_CONFIGS.get("nap_cn")

        self.assertIsNotNone(config)
        self.assertEqual(config.act_id, "e202406242138391")
        self.assertEqual(config.sign_game, "zzz")
        self.assertEqual(config.info_url, "https://act-nap-api.mihoyo.com/event/luna/zzz/info")
        self.assertEqual(config.sign_url, "https://act-nap-api.mihoyo.com/event/luna/zzz/sign")
        self.assertEqual(config.rewards_url, "https://act-nap-api.mihoyo.com/event/luna/zzz/home")

    async def test_utc_now_helpers_return_utc_with_and_without_tzinfo(self):
        aware_now = utc_now()
        naive_now = utc_now_naive()

        self.assertEqual(aware_now.tzinfo, timezone.utc)
        self.assertIsNone(naive_now.tzinfo)
        self.assertLess(abs((aware_now.replace(tzinfo=None) - naive_now).total_seconds()), 2)

    async def _do_sign_with_payload(self, session, post_payload):
        service = CheckinService(session)
        role = GameRole(id=2, account_id=1, game_biz="hkrpg_cn", game_uid="10001", region="prod_gf_cn")
        client = FakeClient(post_payload=post_payload)
        result = await service._do_sign(
            client,
            "ltuid=1;",
            CheckinGameConfig(act_id="e202304121516551", sign_game="hkrpg"),
            MihoyoAccount(id=1, user_id=1, nickname="测试账号"),
            role,
            ("device-id", "device-fp"),
        )
        return result, client

    async def test_do_sign_sends_uid_as_string_and_recognizes_risk(self):
        async with await self._new_session() as session:
            result, client = await self._do_sign_with_payload(
                session,
                {"retcode": 0, "data": {"is_risk": True, "gt": "captcha", "challenge": "ch"}},
            )

        sent_body = json.loads(client.last_post["content"])
        self.assertEqual(sent_body["uid"], "10001")
        self.assertEqual(result.status, "risk")
        self.assertEqual(result.message, GEETEST_RISK_MESSAGE)
        self.assertEqual(len(client.post_calls), 1)
        self.assertNotIn("x-rpc-challenge", client.last_post["headers"])

    async def test_do_sign_treats_success_one_as_risk_not_success(self):
        async with await self._new_session() as session:
            result, client = await self._do_sign_with_payload(
                session,
                {"retcode": 0, "data": {"success": 1}},
            )

        self.assertEqual(result.status, "risk")
        self.assertEqual(result.message, GENERIC_RISK_MESSAGE)
        self.assertEqual(len(client.post_calls), 1)

    async def test_do_sign_treats_nonzero_risk_code_without_tokens_as_risk(self):
        async with await self._new_session() as session:
            result, _client = await self._do_sign_with_payload(
                session,
                {"retcode": 0, "data": {"risk_code": 375}},
            )

        self.assertEqual(result.status, "risk")
        self.assertEqual(result.message, GENERIC_RISK_MESSAGE)

    async def test_do_sign_treats_geetest_retcode_as_risk_instead_of_api_error(self):
        async with await self._new_session() as session:
            result, client = await self._do_sign_with_payload(
                session,
                {"retcode": 1034, "message": "not login"},
            )

        self.assertEqual(result.status, "risk")
        self.assertEqual(result.message, GEETEST_RISK_MESSAGE)
        self.assertEqual(len(client.post_calls), 1)
        self.assertNotIn("x-rpc-challenge", client.last_post["headers"])

    async def test_do_sign_keeps_already_signed_for_minus_5003(self):
        async with await self._new_session() as session:
            result, _client = await self._do_sign_with_payload(
                session,
                {"retcode": -5003, "message": "already signed"},
            )

        self.assertEqual(result.status, "already_signed")
        self.assertEqual(result.message, "今日已签到")

    async def test_do_sign_succeeds_when_success_is_zero_without_risk(self):
        async with await self._new_session() as session:
            result, client = await self._do_sign_with_payload(
                session,
                {"retcode": 0, "data": {"success": 0, "is_risk": False, "total_sign_day": 12}},
            )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.total_sign_days, 12)
        self.assertEqual(len(client.post_calls), 1)
        self.assertNotIn("x-rpc-challenge", client.last_post["headers"])

    async def test_get_sign_info_raises_structured_error_when_upstream_fails(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            role = GameRole(id=2, account_id=1, game_biz="hkrpg_cn", game_uid="10001", region="prod_gf_cn")
            client = FakeClient(get_payload={"retcode": -100, "message": "invalid request"})

            with self.assertRaises(CheckinApiError) as ctx:
                await service._get_sign_info(
                    client,
                    "ltuid=1;",
                    CheckinGameConfig(act_id="e202304121516551", sign_game="hkrpg"),
                    role,
                    ("device-id", "device-fp"),
                )

        self.assertIn("查询签到状态失败", str(ctx.exception))
        self.assertIn("invalid request", str(ctx.exception))

    async def test_execute_for_user_calls_short_and_long_delays_in_starward_positions(self):
        async with await self._new_session() as session:
            user = await self._create_user(session, "checkin-delay-user")
            account = MihoyoAccount(user_id=user.id, cookie_encrypted="encrypted", cookie_status="valid")
            session.add(account)
            await session.flush()
            role = GameRole(account_id=account.id, game_biz="hkrpg_cn", game_uid="10001", region="prod_gf_cn", is_enabled=True)
            session.add(role)
            await session.commit()

            service = CheckinService(session)
            service._ensure_device_state = AsyncMock(return_value=("device-id", "device-fp"))
            service._get_sign_info = AsyncMock(return_value={"is_sign": False, "total_sign_day": 12})
            service._ensure_monthly_rewards = AsyncMock(return_value=[])
            service._do_sign = AsyncMock(
                return_value=CheckinResult(
                    account_id=account.id,
                    game_role_id=role.id,
                    status="success",
                    message="签到成功",
                    total_sign_days=12,
                )
            )
            service._sleep_between_info_and_sign = AsyncMock()
            service._sleep_between_roles = AsyncMock()

            with patch("app.services.checkin.decrypt_cookie", return_value="ltuid=1;"):
                summary = await service.execute_for_user(user.id)

        self.assertEqual(summary.success, 1)
        service._sleep_between_info_and_sign.assert_awaited_once()
        service._sleep_between_roles.assert_awaited_once()

    async def _assert_checkin_after_cookie_refresh(self, scenarios, *, cached_role=False):
        async with await self._new_session() as session:
            user = await self._create_user(session, "checkin-cookie-refresh-user")
            accounts = []
            roles_by_account = {}
            for index, scenario in enumerate(scenarios):
                account = MihoyoAccount(
                    user_id=user.id,
                    cookie_encrypted=encrypt_text(f"cookie_token=old-{index};"),
                    cookie_status="unknown" if scenario == "verified" else "expired",
                    stoken_encrypted=encrypt_text("test-stoken"),
                    stuid=str(index + 1),
                    mid=f"test-mid-{index}",
                )
                session.add(account)
                await session.flush()
                accounts.append(account)
                roles = [
                    GameRole(
                        account_id=account.id,
                        game_biz="hkrpg_cn",
                        game_uid=f"{index + 1}000{role_index}",
                        region="prod_gf_cn",
                        is_enabled=True,
                    )
                    for role_index in range(2)
                ]
                session.add_all(roles)
                await session.flush()
                roles_by_account[account.id] = roles

            cached = roles_by_account[accounts[0].id][0] if cached_role else None
            if cached is not None:
                session.add(TaskLog(
                    account_id=cached.account_id,
                    game_role_id=cached.id,
                    task_type="checkin",
                    status="success",
                    message="签到成功",
                    executed_at=utc_now_naive(),
                ))
            await session.commit()

            scenario_by_id = dict(zip((account.id for account in accounts), scenarios))

            async def verify_cookie(account):
                scenario = scenario_by_id[account.id]
                state = {"verified": "valid", "network_error": "network_error"}.get(scenario, "expired")
                return {"state": state, "message": "网络异常，暂未确认失效" if state == "network_error" else state}

            async def repair_cookie(account):
                if scenario_by_id[account.id] == "reauth_required":
                    account.credential_status = "reauth_required"
                    return {"state": "reauth_required", "message": "根凭据已失效"}
                account.cookie_encrypted = encrypt_text(f"cookie_token=repaired-{account.id};")
                return {"state": "valid", "message": "工作 Cookie 已修复"}

            async def checkin_role(account, role, cookie, client, device_state):
                return CheckinResult(
                    account_id=account.id,
                    game_role_id=role.id,
                    status="success",
                    message="签到成功",
                )

            service = CheckinService(session)
            service._ensure_device_state = AsyncMock(return_value=("device-id", "device-fp"))
            service._checkin_role = AsyncMock(side_effect=checkin_role)
            # 保留真实登录态分支，只替换外部校验、凭据换取、角色同步和通知边界
            with patch.object(LoginStateService, "verify_cookie", new=AsyncMock(side_effect=verify_cookie)) as verify, patch(
                "app.services.login_state.AccountCredentialService.ensure_work_cookie",
                new=AsyncMock(side_effect=repair_cookie),
            ) as repair, patch(
                "app.services.login_state.refresh_account_roles",
                new=AsyncMock(return_value={"roles_sync_status": "success", "roles_count": 2}),
            ), patch(
                "app.services.login_state.notification_service.send_reauth_required_notification",
                new=AsyncMock(return_value=True),
            ) as notify:
                summary = await service.execute_for_user(user.id)

            logs = (await session.execute(
                select(TaskLog).where(TaskLog.account_id.in_([account.id for account in accounts]))
            )).scalars().all()
            expected_statuses = {}
            expected_cookies = {}
            for index, account in enumerate(accounts):
                scenario = scenario_by_id[account.id]
                for role in roles_by_account[account.id]:
                    if cached is not None and role.id == cached.id:
                        expected_statuses[role.id] = "already_signed"
                    elif scenario in ("verified", "repaired"):
                        expected_statuses[role.id] = "success"
                        expected_cookies[role.id] = (
                            f"cookie_token=old-{index};" if scenario == "verified"
                            else f"cookie_token=repaired-{account.id};"
                        )
                    else:
                        expected_statuses[role.id] = "failed"

            self.assertEqual(summary.total, len(expected_statuses))
            self.assertEqual(summary.success, len(expected_cookies))
            self.assertEqual(summary.failed, list(expected_statuses.values()).count("failed"))
            self.assertEqual(summary.already_signed, int(cached_role))
            self.assertEqual(summary.risk, 0)
            self.assertEqual({item.game_role_id: item.status for item in summary.results}, expected_statuses)
            self.assertEqual(len(logs), len(expected_statuses))
            self.assertEqual(
                {log.game_role_id: log.status for log in logs},
                {role_id: "success" if status == "already_signed" else status
                 for role_id, status in expected_statuses.items()},
            )
            calls = service._checkin_role.await_args_list
            self.assertEqual(len(calls), len(expected_cookies))
            self.assertEqual({call.args[1].id: call.args[2] for call in calls}, expected_cookies)
            self.assertEqual(verify.await_count, len(accounts))
            self.assertEqual(repair.await_count, sum(s in ("repaired", "reauth_required") for s in scenarios))
            self.assertEqual(notify.await_count, scenarios.count("reauth_required"))
            self.assertEqual(service._ensure_device_state.await_count, int(bool(expected_cookies)))
            messages = {item.game_role_id: item.message for item in summary.results}
            for log in logs:
                if log.status == "failed":
                    self.assertEqual(log.message, messages[log.game_role_id])
                    expected_message = (
                        "根凭据已失效" if scenario_by_id[log.account_id] == "reauth_required" else "网络异常"
                    )
                    self.assertIn(expected_message, log.message)

    async def test_execute_for_user_continues_after_unknown_cookie_verifies(self):
        await self._assert_checkin_after_cookie_refresh(["verified"])

    async def test_execute_for_user_uses_repaired_cookie_in_same_run(self):
        await self._assert_checkin_after_cookie_refresh(["repaired"])

    async def test_execute_for_user_logs_each_role_when_root_credentials_expire(self):
        await self._assert_checkin_after_cookie_refresh(["reauth_required"])

    async def test_execute_for_user_logs_each_role_when_cookie_verification_has_network_error(self):
        await self._assert_checkin_after_cookie_refresh(["network_error"])

    async def test_execute_for_user_continues_other_accounts_after_cookie_refresh_failure(self):
        await self._assert_checkin_after_cookie_refresh(["reauth_required", "repaired", "network_error", "verified"])

    async def test_execute_for_user_reuses_signed_role_and_repairs_cookie_for_pending_role(self):
        await self._assert_checkin_after_cookie_refresh(["repaired"], cached_role=True)

    async def test_execute_for_user_reuses_today_success_log_without_calling_upstream(self):
        async with await self._new_session() as session:
            user = await self._create_user(session, "checkin-cache-success-user")
            account = MihoyoAccount(user_id=user.id, cookie_encrypted="encrypted", cookie_status="valid", nickname="测试账号")
            session.add(account)
            await session.flush()
            role = GameRole(
                account_id=account.id,
                game_biz="hkrpg_cn",
                game_uid="10001",
                region="prod_gf_cn",
                is_enabled=True,
                nickname="星铁角色",
            )
            session.add(role)
            await session.flush()
            session.add(
                TaskLog(
                    account_id=account.id,
                    game_role_id=role.id,
                    task_type="checkin",
                    status="success",
                    message="签到成功",
                    total_sign_days=12,
                    reward_name="原石",
                    reward_cnt=20,
                    reward_icon="https://example.com/primogem.png",
                    executed_at=datetime(2026, 3, 16, 16, 30, 0),
                )
            )
            await session.commit()

            service = CheckinService(session)
            service._ensure_device_state = AsyncMock()
            service._get_sign_info = AsyncMock()
            service._do_sign = AsyncMock()

            with patch("app.services.checkin.get_shanghai_date", return_value=date(2026, 3, 17), create=True):
                summary = await service.execute_for_user(user.id)

            log_count = (
                await session.execute(select(TaskLog).where(TaskLog.account_id == account.id))
            ).scalars().all()

        self.assertEqual(summary.total, 1)
        self.assertEqual(summary.success, 0)
        self.assertEqual(summary.already_signed, 1)
        self.assertEqual(summary.results[0].status, "already_signed")
        self.assertEqual(summary.results[0].message, "今日已签到（复用当日记录，未重复调用接口）")
        self.assertEqual(summary.results[0].total_sign_days, 12)
        self.assertEqual(summary.results[0].reward_name, "原石")
        self.assertEqual(summary.results[0].reward_cnt, 20)
        self.assertEqual(len(log_count), 1)
        service._ensure_device_state.assert_not_awaited()
        service._get_sign_info.assert_not_awaited()
        service._do_sign.assert_not_awaited()

    async def test_execute_for_user_reuses_today_already_signed_log_without_calling_upstream(self):
        async with await self._new_session() as session:
            user = await self._create_user(session, "checkin-cache-already-signed-user")
            account = MihoyoAccount(user_id=user.id, cookie_encrypted="encrypted", cookie_status="valid")
            session.add(account)
            await session.flush()
            role = GameRole(account_id=account.id, game_biz="hk4e_cn", game_uid="10001", region="cn_gf01", is_enabled=True)
            session.add(role)
            await session.flush()
            session.add(
                TaskLog(
                    account_id=account.id,
                    game_role_id=role.id,
                    task_type="checkin",
                    status="already_signed",
                    message="今日已签到",
                    total_sign_days=20,
                    executed_at=datetime(2026, 3, 16, 16, 30, 0),
                )
            )
            await session.commit()

            service = CheckinService(session)
            service._ensure_device_state = AsyncMock()
            service._get_sign_info = AsyncMock()
            service._do_sign = AsyncMock()

            with patch("app.services.checkin.get_shanghai_date", return_value=date(2026, 3, 17), create=True):
                summary = await service.execute_for_user(user.id)

        self.assertEqual(summary.total, 1)
        self.assertEqual(summary.already_signed, 1)
        self.assertEqual(summary.results[0].status, "already_signed")
        self.assertEqual(summary.results[0].total_sign_days, 20)
        service._ensure_device_state.assert_not_awaited()
        service._get_sign_info.assert_not_awaited()
        service._do_sign.assert_not_awaited()

    async def test_execute_for_user_does_not_short_circuit_today_failed_log(self):
        async with await self._new_session() as session:
            user = await self._create_user(session, "checkin-failed-log-user")
            account = MihoyoAccount(user_id=user.id, cookie_encrypted="encrypted", cookie_status="valid")
            session.add(account)
            await session.flush()
            role = GameRole(account_id=account.id, game_biz="hkrpg_cn", game_uid="10001", region="prod_gf_cn", is_enabled=True)
            session.add(role)
            await session.flush()
            session.add(
                TaskLog(
                    account_id=account.id,
                    game_role_id=role.id,
                    task_type="checkin",
                    status="failed",
                    message="网络错误",
                    executed_at=datetime(2026, 3, 16, 16, 30, 0),
                )
            )
            await session.commit()

            service = CheckinService(session)
            service._ensure_device_state = AsyncMock(return_value=("device-id", "device-fp"))
            service._get_sign_info = AsyncMock(return_value={"is_sign": False, "total_sign_day": 13})
            service._ensure_monthly_rewards = AsyncMock(return_value=[])
            service._do_sign = AsyncMock(
                return_value=CheckinResult(
                    account_id=account.id,
                    game_role_id=role.id,
                    status="success",
                    message="签到成功",
                    total_sign_days=13,
                )
            )
            service._sleep_between_info_and_sign = AsyncMock()
            service._sleep_between_roles = AsyncMock()

            with patch("app.services.checkin.decrypt_cookie", return_value="ltuid=1;"), patch(
                "app.services.checkin.get_shanghai_date",
                return_value=date(2026, 3, 17),
                create=True,
            ):
                summary = await service.execute_for_user(user.id)

        self.assertEqual(summary.success, 1)
        self.assertEqual(summary.already_signed, 0)
        service._ensure_device_state.assert_awaited_once()
        service._get_sign_info.assert_awaited_once()
        service._do_sign.assert_awaited_once()

    async def test_execute_for_user_uses_latest_today_log_status_for_short_circuit(self):
        async with await self._new_session() as session:
            user = await self._create_user(session, "checkin-latest-log-user")
            account = MihoyoAccount(user_id=user.id, cookie_encrypted="encrypted", cookie_status="valid")
            session.add(account)
            await session.flush()
            role = GameRole(account_id=account.id, game_biz="hkrpg_cn", game_uid="10001", region="prod_gf_cn", is_enabled=True)
            session.add(role)
            await session.flush()
            session.add_all([
                TaskLog(
                    account_id=account.id,
                    game_role_id=role.id,
                    task_type="checkin",
                    status="success",
                    message="签到成功",
                    total_sign_days=10,
                    executed_at=datetime(2026, 3, 16, 16, 30, 0),
                ),
                TaskLog(
                    account_id=account.id,
                    game_role_id=role.id,
                    task_type="checkin",
                    status="failed",
                    message="网络错误",
                    executed_at=datetime(2026, 3, 16, 17, 30, 0),
                ),
            ])
            await session.commit()

            service = CheckinService(session)
            service._ensure_device_state = AsyncMock(return_value=("device-id", "device-fp"))
            service._get_sign_info = AsyncMock(return_value={"is_sign": False, "total_sign_day": 11})
            service._ensure_monthly_rewards = AsyncMock(return_value=[])
            service._do_sign = AsyncMock(
                return_value=CheckinResult(
                    account_id=account.id,
                    game_role_id=role.id,
                    status="success",
                    message="签到成功",
                    total_sign_days=11,
                )
            )
            service._sleep_between_info_and_sign = AsyncMock()
            service._sleep_between_roles = AsyncMock()

            with patch("app.services.checkin.decrypt_cookie", return_value="ltuid=1;"), patch(
                "app.services.checkin.get_shanghai_date",
                return_value=date(2026, 3, 17),
                create=True,
            ):
                summary = await service.execute_for_user(user.id)

        self.assertEqual(summary.success, 1)
        self.assertEqual(summary.already_signed, 0)
        service._get_sign_info.assert_awaited_once()
        service._do_sign.assert_awaited_once()

    async def test_execute_for_user_only_short_circuits_matching_role(self):
        async with await self._new_session() as session:
            user = await self._create_user(session, "checkin-matching-role-user")
            account = MihoyoAccount(user_id=user.id, cookie_encrypted="encrypted", cookie_status="valid", nickname="测试账号")
            session.add(account)
            await session.flush()
            cached_role = GameRole(account_id=account.id, game_biz="hk4e_cn", game_uid="10001", region="cn_gf01", is_enabled=True)
            pending_role = GameRole(account_id=account.id, game_biz="hkrpg_cn", game_uid="10002", region="prod_gf_cn", is_enabled=True)
            session.add_all([cached_role, pending_role])
            await session.flush()
            session.add(
                TaskLog(
                    account_id=account.id,
                    game_role_id=cached_role.id,
                    task_type="checkin",
                    status="success",
                    message="签到成功",
                    total_sign_days=3,
                    executed_at=datetime(2026, 3, 16, 16, 30, 0),
                )
            )
            await session.commit()

            service = CheckinService(session)
            service._ensure_device_state = AsyncMock(return_value=("device-id", "device-fp"))
            service._checkin_role = AsyncMock(
                return_value=CheckinResult(
                    account_id=account.id,
                    game_role_id=pending_role.id,
                    status="success",
                    message="签到成功",
                    total_sign_days=9,
                )
            )

            with patch("app.services.checkin.decrypt_cookie", return_value="ltuid=1;"), patch(
                "app.services.checkin.get_shanghai_date",
                return_value=date(2026, 3, 17),
                create=True,
            ):
                summary = await service.execute_for_user(user.id)

            logs = (
                await session.execute(
                    select(TaskLog).where(TaskLog.account_id == account.id).order_by(TaskLog.id.asc())
                )
            ).scalars().all()

        self.assertEqual(summary.total, 2)
        self.assertEqual(summary.success, 1)
        self.assertEqual(summary.already_signed, 1)
        self.assertEqual(summary.results[0].game_role_id, cached_role.id)
        self.assertEqual(summary.results[0].status, "already_signed")
        self.assertEqual(summary.results[1].game_role_id, pending_role.id)
        self.assertEqual(summary.results[1].status, "success")
        self.assertEqual(len(logs), 2)
        service._ensure_device_state.assert_awaited_once()
        service._checkin_role.assert_awaited_once()

    async def test_execute_for_user_does_not_reuse_yesterday_success_log(self):
        async with await self._new_session() as session:
            user = await self._create_user(session, "checkin-yesterday-log-user")
            account = MihoyoAccount(user_id=user.id, cookie_encrypted="encrypted", cookie_status="valid")
            session.add(account)
            await session.flush()
            role = GameRole(account_id=account.id, game_biz="hkrpg_cn", game_uid="10001", region="prod_gf_cn", is_enabled=True)
            session.add(role)
            await session.flush()
            session.add(
                TaskLog(
                    account_id=account.id,
                    game_role_id=role.id,
                    task_type="checkin",
                    status="success",
                    message="签到成功",
                    total_sign_days=7,
                    executed_at=datetime(2026, 3, 15, 16, 30, 0),
                )
            )
            await session.commit()

            service = CheckinService(session)
            service._ensure_device_state = AsyncMock(return_value=("device-id", "device-fp"))
            service._get_sign_info = AsyncMock(return_value={"is_sign": False, "total_sign_day": 8})
            service._ensure_monthly_rewards = AsyncMock(return_value=[])
            service._do_sign = AsyncMock(
                return_value=CheckinResult(
                    account_id=account.id,
                    game_role_id=role.id,
                    status="success",
                    message="签到成功",
                    total_sign_days=8,
                )
            )
            service._sleep_between_info_and_sign = AsyncMock()
            service._sleep_between_roles = AsyncMock()

            with patch("app.services.checkin.decrypt_cookie", return_value="ltuid=1;"), patch(
                "app.services.checkin.get_shanghai_date",
                return_value=date(2026, 3, 17),
                create=True,
            ):
                summary = await service.execute_for_user(user.id)

        self.assertEqual(summary.success, 1)
        self.assertEqual(summary.already_signed, 0)
        service._get_sign_info.assert_awaited_once()
        service._do_sign.assert_awaited_once()

    async def test_execute_for_user_runs_bh3_cn_checkin(self):
        async with await self._new_session() as session:
            user = await self._create_user(session, "checkin-bh3-user")
            account = MihoyoAccount(user_id=user.id, cookie_encrypted="encrypted", cookie_status="valid")
            session.add(account)
            await session.flush()
            role = GameRole(account_id=account.id, game_biz="bh3_cn", game_uid="30001", region="android01", is_enabled=True)
            session.add(role)
            await session.commit()

            service = CheckinService(session)
            service._ensure_device_state = AsyncMock(return_value=("device-id", "device-fp"))
            service._get_sign_info = AsyncMock(return_value={"is_sign": False, "total_sign_day": 8})
            service._ensure_monthly_rewards = AsyncMock(return_value=[])
            service._do_sign = AsyncMock(
                return_value=CheckinResult(
                    account_id=account.id,
                    game_role_id=role.id,
                    status="success",
                    message="签到成功",
                    total_sign_days=8,
                )
            )

            with patch("app.services.checkin.decrypt_cookie", return_value="ltuid=1;"):
                summary = await service.execute_for_user(user.id)

        self.assertEqual(summary.total, 1)
        self.assertEqual(summary.success, 1)
        service._get_sign_info.assert_awaited_once()
        service._do_sign.assert_awaited_once()

    async def test_execute_for_user_runs_nap_cn_checkin(self):
        async with await self._new_session() as session:
            user = await self._create_user(session, "checkin-nap-user")
            account = MihoyoAccount(user_id=user.id, cookie_encrypted="encrypted", cookie_status="valid")
            session.add(account)
            await session.flush()
            role = GameRole(account_id=account.id, game_biz="nap_cn", game_uid="20001", region="prod_gf_cn", is_enabled=True)
            session.add(role)
            await session.commit()

            service = CheckinService(session)
            service._ensure_device_state = AsyncMock(return_value=("device-id", "device-fp"))
            service._get_sign_info = AsyncMock(return_value={"is_sign": False, "total_sign_day": 5})
            service._ensure_monthly_rewards = AsyncMock(return_value=[])
            service._do_sign = AsyncMock(
                return_value=CheckinResult(
                    account_id=account.id,
                    game_role_id=role.id,
                    status="success",
                    message="签到成功",
                    total_sign_days=5,
                )
            )

            with patch("app.services.checkin.decrypt_cookie", return_value="ltuid=1;"):
                summary = await service.execute_for_user(user.id)

        self.assertEqual(summary.total, 1)
        self.assertEqual(summary.success, 1)
        service._get_sign_info.assert_awaited_once()
        service._do_sign.assert_awaited_once()

    async def test_execute_for_user_still_skips_unsupported_games_without_logging_failure(self):
        async with await self._new_session() as session:
            user = await self._create_user(session, "checkin-unsupported-game-user")
            account = MihoyoAccount(user_id=user.id, cookie_encrypted="encrypted", cookie_status="valid")
            session.add(account)
            await session.flush()
            session.add(GameRole(account_id=account.id, game_biz="nxx_cn", game_uid="40001", region="prod_gf_cn", is_enabled=True))
            await session.commit()

            service = CheckinService(session)
            service._ensure_device_state = AsyncMock(return_value=("device-id", "device-fp"))
            service._get_sign_info = AsyncMock()
            service._do_sign = AsyncMock()

            with patch("app.services.checkin.decrypt_cookie", return_value="ltuid=1;"):
                summary = await service.execute_for_user(user.id)

        self.assertEqual(summary.total, 0)
        self.assertEqual(summary.failed, 0)
        service._get_sign_info.assert_not_awaited()
        service._do_sign.assert_not_awaited()

    async def test_get_sign_info_uses_bh3_checkin_act_id(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            role = GameRole(id=3, account_id=1, game_biz="bh3_cn", game_uid="30001", region="android01")
            client = FakeClient(get_payload={"retcode": 0, "data": {"is_sign": False, "total_sign_day": 3}})

            await service._get_sign_info(
                client,
                "ltuid=1;",
                CheckinGameConfig(
                    act_id="e202306201626331",
                    sign_game="bh3",
                    send_sign_game=False,
                    referer="https://webstatic.mihoyo.com/bbs/event/signin/bh3/index.html?bbs_auth_required=true&act_id=e202306201626331&bbs_presentation_style=fullscreen&utm_source=bbs&utm_medium=mys&utm_campaign=icon",
                ),
                role,
                ("device-id", "device-fp"),
            )

        self.assertEqual(client.last_get["params"]["act_id"], "e202306201626331")
        self.assertNotIn("x-rpc-signgame", client.last_get["headers"])
        self.assertIn("act_id=e202306201626331", client.last_get["headers"]["Referer"])

    async def test_get_sign_info_uses_zzz_checkin_info_url_and_act_id(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            role = GameRole(id=4, account_id=1, game_biz="nap_cn", game_uid="20001", region="prod_gf_cn")
            client = FakeClient(get_payload={"retcode": 0, "data": {"is_sign": False, "total_sign_day": 4}})

            await service._get_sign_info(
                client,
                "ltuid=1;",
                CheckinGameConfig(
                    act_id="e202406242138391",
                    sign_game="zzz",
                    info_url="https://act-nap-api.mihoyo.com/event/luna/zzz/info",
                    sign_url="https://act-nap-api.mihoyo.com/event/luna/zzz/sign",
                    rewards_url="https://act-nap-api.mihoyo.com/event/luna/zzz/home",
                ),
                role,
                ("device-id", "device-fp"),
            )

        self.assertEqual(client.last_get["url"], "https://act-nap-api.mihoyo.com/event/luna/zzz/info")
        self.assertEqual(client.last_get["params"]["act_id"], "e202406242138391")
        self.assertEqual(client.last_get["headers"]["x-rpc-signgame"], "zzz")

    async def test_do_sign_uses_zzz_checkin_sign_url(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            role = GameRole(id=5, account_id=1, game_biz="nap_cn", game_uid="20001", region="prod_gf_cn")
            client = FakeClient(post_payload={"retcode": 0, "data": {"total_sign_day": 6}})

            await service._do_sign(
                client,
                "ltuid=1;",
                CheckinGameConfig(
                    act_id="e202406242138391",
                    sign_game="zzz",
                    info_url="https://act-nap-api.mihoyo.com/event/luna/zzz/info",
                    sign_url="https://act-nap-api.mihoyo.com/event/luna/zzz/sign",
                    rewards_url="https://act-nap-api.mihoyo.com/event/luna/zzz/home",
                ),
                MihoyoAccount(id=1, user_id=1, nickname="测试账号"),
                role,
                ("device-id", "device-fp"),
            )

        self.assertEqual(client.last_post["url"], "https://act-nap-api.mihoyo.com/event/luna/zzz/sign")
        self.assertEqual(client.last_post["headers"]["x-rpc-signgame"], "zzz")

    async def test_refresh_device_fp_accepts_real_world_payload_shape(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            client = FakeClient(
                post_payload={
                    "retcode": 0,
                    "message": "OK",
                    "data": {
                        "device_fp": "713617441b",
                        "code": 403,
                        "msg": "传入的参数有误",
                    },
                }
            )

            device_fp = await service._refresh_device_fp(client, "device-id")

        self.assertEqual(device_fp, "713617441b")

    async def test_ensure_device_state_falls_back_when_device_fp_api_fails(self):
        async with await self._new_session() as session:
            service = CheckinService(session)

            class BrokenClient:
                async def post(self, *args, **kwargs):
                    raise RuntimeError("network down")

            device_id, device_fp = await service._ensure_device_state(BrokenClient())

            self.assertTrue(device_id)
            self.assertTrue(device_fp)
            self.assertEqual(len(device_fp), 10)

    async def test_admin_email_settings_encrypt_password_and_hide_plaintext(self):
        async with await self._new_session() as session:
            admin = User(username="admin", password_hash="x", role="admin", is_active=True)
            session.add(admin)
            await session.commit()

            response = await update_email_settings(
                AdminEmailSettingsUpdate(
                    smtp_enabled=True,
                    smtp_host="smtp.example.com",
                    smtp_port=465,
                    smtp_user="mailer@example.com",
                    smtp_password="secret-password",
                    smtp_use_ssl=True,
                    smtp_sender_name="签到助手",
                    smtp_sender_email="mailer@example.com",
                ),
                admin=admin,
                db=session,
            )

            stored = (await session.execute(select(SystemSetting))).scalar_one()
            self.assertNotEqual(stored.smtp_password_encrypted, "secret-password")
            self.assertEqual(decrypt_text(stored.smtp_password_encrypted), "secret-password")
            self.assertTrue(response.smtp_password_configured)

            read_back = await get_email_settings(admin=admin, db=session)
            self.assertTrue(read_back.smtp_password_configured)
            self.assertEqual(read_back.smtp_user, "mailer@example.com")

    async def test_admin_invite_code_settings_encrypt_and_return_plaintext(self):
        async with await self._new_session() as session:
            admin = User(username="invite-admin", password_hash="x", role="admin", is_active=True)
            session.add(admin)
            await session.commit()

            response = await update_invite_code_settings(
                AdminInviteCodeSettingsUpdate(invite_code_enabled=True, invite_code=" Welcome_1 "),
                admin=admin,
                db=session,
            )
            stored = (await session.execute(select(SystemSetting))).scalar_one()

            self.assertTrue(response.invite_code_enabled)
            self.assertEqual(response.invite_code, "Welcome_1")
            self.assertNotEqual(stored.invite_code_encrypted, "Welcome_1")
            self.assertEqual(decrypt_text(stored.invite_code_encrypted), "Welcome_1")

            read_back = await get_invite_code_settings(admin=admin, db=session)
            self.assertTrue(read_back.invite_code_enabled)
            self.assertEqual(read_back.invite_code, "Welcome_1")

    async def test_admin_invite_code_settings_reject_enabled_empty_or_invalid_format(self):
        async with await self._new_session() as session:
            admin = User(username="invite-invalid-admin", password_hash="x", role="admin", is_active=True)
            session.add(admin)
            await session.commit()

            with self.assertRaises(HTTPException) as empty_ctx:
                await update_invite_code_settings(
                    AdminInviteCodeSettingsUpdate(invite_code_enabled=True, invite_code="  "),
                    admin=admin,
                    db=session,
                )
            with self.assertRaises(HTTPException) as format_ctx:
                await update_invite_code_settings(
                    AdminInviteCodeSettingsUpdate(invite_code_enabled=True, invite_code="bad code"),
                    admin=admin,
                    db=session,
                )

        self.assertEqual(empty_ctx.exception.status_code, 400)
        self.assertIn("必须填写邀请码", empty_ctx.exception.detail)
        self.assertEqual(format_ctx.exception.status_code, 400)
        self.assertIn("4-32", format_ctx.exception.detail)

    async def test_register_options_reflect_invite_requirement_states(self):
        async with await self._new_session() as session:
            empty_options = await get_register_options(db=session)
            self.assertFalse(empty_options.invite_required)

            await update_invite_code_settings(
                AdminInviteCodeSettingsUpdate(invite_code_enabled=True, invite_code="GateCode1"),
                admin=User(username="unused", password_hash="x", role="admin", is_active=True),
                db=session,
            )
            still_first_user = await get_register_options(db=session)
            self.assertFalse(still_first_user.invite_required)

            session.add(User(username="bootstrap-admin", password_hash="x", role="admin", is_active=True))
            await session.commit()
            required_options = await get_register_options(db=session)
            self.assertTrue(required_options.invite_required)

            await update_invite_code_settings(
                AdminInviteCodeSettingsUpdate(invite_code_enabled=False, invite_code="GateCode1"),
                admin=User(username="unused-2", password_hash="x", role="admin", is_active=True),
                db=session,
            )
            disabled_options = await get_register_options(db=session)
            self.assertFalse(disabled_options.invite_required)

    async def test_register_requires_invite_code_after_first_user(self):
        async with await self._new_session() as session:
            session.add(User(username="bootstrap-admin", password_hash="x", role="admin", is_active=True))
            await session.commit()
            await update_invite_code_settings(
                AdminInviteCodeSettingsUpdate(invite_code_enabled=True, invite_code="Invite_OK"),
                admin=User(username="unused", password_hash="x", role="admin", is_active=True),
                db=session,
            )

            with self.assertRaises(HTTPException) as missing_ctx:
                await register(
                    UserCreate(username="no-code-user", password="password123"),
                    db=session,
                )
            with self.assertRaises(HTTPException) as wrong_ctx:
                await register(
                    UserCreate(
                        username="wrong-code-user",
                        password="password123",
                        invite_code="Invite_NO",
                    ),
                    db=session,
                )

            registered = await register(
                UserCreate(
                    username="invited-user",
                    password="password123",
                    invite_code="Invite_OK",
                ),
                db=session,
            )

        self.assertEqual(missing_ctx.exception.status_code, 400)
        self.assertEqual(missing_ctx.exception.detail, "邀请码错误")
        self.assertEqual(wrong_ctx.exception.status_code, 400)
        self.assertEqual(wrong_ctx.exception.detail, "邀请码错误")
        self.assertEqual(registered.username, "invited-user")
        self.assertEqual(registered.role, "user")

    async def test_register_skips_invite_code_for_first_user_even_when_enabled(self):
        async with await self._new_session() as session:
            await update_invite_code_settings(
                AdminInviteCodeSettingsUpdate(invite_code_enabled=True, invite_code="Invite_OK"),
                admin=User(username="unused", password_hash="x", role="admin", is_active=True),
                db=session,
            )
            first_user = await register(
                UserCreate(username="first-admin", password="password123"),
                db=session,
            )

        self.assertEqual(first_user.role, "admin")

    async def test_register_without_invite_code_still_works_when_disabled(self):
        async with await self._new_session() as session:
            session.add(User(username="bootstrap-admin", password_hash="x", role="admin", is_active=True))
            await session.commit()
            registered = await register(
                UserCreate(username="open-register-user", password="password123"),
                db=session,
            )

        self.assertEqual(registered.username, "open-register-user")
        self.assertEqual(registered.role, "user")

    async def test_get_invite_code_settings_recovers_legacy_system_settings_without_invite_columns(self):
        async with self.engine.begin() as conn:
            await conn.exec_driver_sql("DROP TABLE IF EXISTS system_settings")
            await conn.exec_driver_sql(
                """
                CREATE TABLE system_settings (
                    id BIGINT PRIMARY KEY,
                    smtp_enabled BOOLEAN,
                    smtp_host VARCHAR(255),
                    smtp_port INTEGER,
                    smtp_user VARCHAR(255),
                    smtp_password_encrypted VARCHAR(1024),
                    smtp_use_ssl BOOLEAN,
                    smtp_sender_name VARCHAR(255),
                    smtp_sender_email VARCHAR(255),
                    hyperion_device_id VARCHAR(64),
                    hyperion_device_fp VARCHAR(64),
                    hyperion_device_fp_updated_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
            await conn.exec_driver_sql(
                """
                INSERT INTO system_settings (
                    id, smtp_enabled, smtp_port, smtp_use_ssl, updated_at
                ) VALUES (1, 0, 465, 1, '2026-03-18 00:00:00')
                """
            )

        async with await self._new_session() as session:
            admin = User(username="legacy-invite-admin", password_hash="x", role="admin", is_active=True)
            session.add(admin)
            await session.commit()
            await session.refresh(admin)

            response = await get_invite_code_settings(admin=admin, db=session)
            result = await session.execute(select(SystemSetting))
            config = result.scalar_one()

        self.assertFalse(response.invite_code_enabled)
        self.assertEqual(response.invite_code, "")
        self.assertFalse(bool(config.invite_code_enabled))

    async def test_admin_broadcast_service_targets_only_active_users_with_bound_email_and_logs_summary(self):
        async with await self._new_session() as session:
            admin = User(username="broadcast-admin", password_hash="x", role="admin", is_active=True)
            eligible = User(
                username="eligible-user",
                password_hash="x",
                role="user",
                is_active=True,
                email=" eligible@example.com ",
                email_notify=False,
                notify_on="failure_only",
            )
            disabled = User(
                username="disabled-user",
                password_hash="x",
                role="user",
                is_active=False,
                email="disabled@example.com",
            )
            no_email = User(
                username="no-email-user",
                password_hash="x",
                role="user",
                is_active=True,
                email="   ",
            )
            session.add_all([admin, eligible, disabled, no_email])
            await session.commit()
            await session.refresh(admin)
            await session.refresh(eligible)

            service = AdminBroadcastService(session)
            service._send_one = AsyncMock(return_value=None)

            result = await service.broadcast_email(
                admin=admin,
                payload=AdminBroadcastEmailRequest(subject="系统维护通知", body="今晚维护"),
            )

            stored_log = (await session.execute(select(AdminOperationLog))).scalar_one()

        self.assertEqual(result.recipient_count, 1)
        self.assertEqual(result.sent_count, 1)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(result.operation_log_id, stored_log.id)
        service._send_one.assert_awaited_once()
        send_kwargs = service._send_one.await_args.kwargs
        self.assertEqual(send_kwargs["recipient"].id, eligible.id)
        self.assertEqual(send_kwargs["recipient"].email, " eligible@example.com ")
        self.assertEqual(send_kwargs["subject"], "系统维护通知")
        self.assertEqual(send_kwargs["body"], "今晚维护")
        self.assertEqual(stored_log.operator_user_id, admin.id)
        self.assertEqual(stored_log.action_type, "broadcast_email")
        self.assertEqual(stored_log.subject, "系统维护通知")
        self.assertEqual(stored_log.recipient_count, 1)
        self.assertEqual(stored_log.sent_count, 1)
        self.assertEqual(stored_log.failed_count, 0)
        self.assertEqual(stored_log.failure_details_json, "[]")

    async def test_admin_broadcast_service_rejects_when_no_eligible_recipient(self):
        async with await self._new_session() as session:
            admin = User(username="empty-broadcast-admin", password_hash="x", role="admin", is_active=True)
            session.add(admin)
            await session.commit()
            await session.refresh(admin)

            service = AdminBroadcastService(session)

            with self.assertRaises(ValueError) as ctx:
                await service.broadcast_email(
                    admin=admin,
                    payload=AdminBroadcastEmailRequest(subject="通知", body="正文"),
                )

        self.assertIn("当前没有已绑定邮箱且启用的用户", str(ctx.exception))

    async def test_notification_service_sends_admin_broadcast_email_with_prefixed_subject_and_escaped_body(self):
        async with await self._new_session() as session:
            del session
            service = NotificationService()
            smtp_config = {
                "hostname": "smtp.example.com",
                "port": 465,
                "username": "mailer@example.com",
                "password": "secret",
                "use_ssl": True,
                "sender_name": "签到助手",
                "sender_email": "mailer@example.com",
            }

            with patch("app.services.notifier.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
                await service.send_admin_broadcast_email(
                    to_email="notify@example.com",
                    subject="系统维护通知",
                    body="第一行\n<script>alert(1)</script>",
                    smtp_config=smtp_config,
                )

        msg = mock_send.await_args.args[0]
        html_part = msg.get_payload()[0].get_payload(decode=True).decode("utf-8")
        self.assertEqual(msg["Subject"], "[系统通知] 系统维护通知")
        self.assertIn("第一行<br>&lt;script&gt;alert(1)&lt;/script&gt;", html_part)
        self.assertIn("管理员通知", html_part)

    async def test_send_admin_broadcast_email_returns_aggregated_result(self):
        async with await self._new_session() as session:
            admin = User(username="api-broadcast-admin", password_hash="x", role="admin", is_active=True)
            session.add(admin)
            await session.commit()
            await session.refresh(admin)

            expected = AdminBroadcastEmailResponse(
                recipient_count=2,
                sent_count=1,
                failed_count=1,
                failures=[
                    AdminBroadcastEmailFailure(
                        user_id=2,
                        username="u2",
                        email="u2@example.com",
                        error="smtp timeout",
                    )
                ],
                operation_log_id=9,
            )

            with patch("app.api.admin.AdminBroadcastService") as mock_service_cls:
                mock_service = mock_service_cls.return_value
                mock_service.broadcast_email = AsyncMock(return_value=expected)

                result = await send_broadcast_email(
                    payload=AdminBroadcastEmailRequest(subject="通知", body="正文"),
                    admin=admin,
                    db=session,
                )

        self.assertEqual(result, expected)

    async def test_send_admin_broadcast_email_translates_validation_error_to_http_400(self):
        async with await self._new_session() as session:
            admin = User(username="api-broadcast-error-admin", password_hash="x", role="admin", is_active=True)
            session.add(admin)
            await session.commit()
            await session.refresh(admin)

            with patch("app.api.admin.AdminBroadcastService") as mock_service_cls:
                mock_service = mock_service_cls.return_value
                mock_service.broadcast_email = AsyncMock(
                    side_effect=ValueError("系统 SMTP 未配置，无法发送群发通知")
                )

                with self.assertRaises(HTTPException) as ctx:
                    await send_broadcast_email(
                        payload=AdminBroadcastEmailRequest(subject="通知", body="正文"),
                        admin=admin,
                        db=session,
                    )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("系统 SMTP 未配置", ctx.exception.detail)

    async def test_refresh_account_login_state_marks_valid_when_cookie_verifies(self):
        async with await self._new_session() as session:
            user = await self._create_user(session, "login-state-valid-user")
            account = MihoyoAccount(
                user_id=user.id,
                cookie_encrypted="encrypted-cookie",
                cookie_status="expired",
                # 这里显式补齐高权限根凭据，确保本用例验证的是
                # “已接入 Passport 根凭据的账号在 Cookie 校验成功时会回到 valid”，
                # 而不是被 Task 5 的旧网页登录账号升级逻辑提前短路成 reauth_required。
                stoken_encrypted="encrypted-stoken",
                stuid="10001",
                mid="mid-10001",
            )
            session.add(account)
            await session.commit()

            service = LoginStateService(session)
            service.verify_cookie = AsyncMock(return_value={"state": "valid", "message": "登录态有效"})

            with patch("app.services.login_state.notification_service.send_reauth_required_notification", new_callable=AsyncMock) as mock_notify, patch(
                "app.services.login_state.refresh_account_roles",
                new=AsyncMock(return_value={"roles_sync_status": "success", "roles_count": 0}),
            ):
                result = await service.refresh_account_login_state(account)

        self.assertEqual(result["cookie_status"], "valid")
        self.assertEqual(account.cookie_status, "valid")
        self.assertEqual(account.last_refresh_status, "valid")
        self.assertEqual(account.last_refresh_message, "登录态有效")
        mock_notify.assert_not_awaited()

    async def test_refresh_account_login_state_marks_reauth_required_and_notifies_once(self):
        async with await self._new_session() as session:
            user = User(
                username="reauth-user",
                password_hash="x",
                role="user",
                is_active=True,
                email="notify@example.com",
                email_notify=True,
                notify_on="always",
            )
            session.add(user)
            await session.flush()

            account = MihoyoAccount(
                user_id=user.id,
                cookie_encrypted="encrypted-cookie",
                cookie_status="expired",
            )
            session.add(account)
            await session.commit()

            service = LoginStateService(session)
            service.verify_cookie = AsyncMock(return_value={"state": "expired", "message": "Cookie 已过期"})

            with patch("app.services.login_state.notification_service.send_reauth_required_notification", new_callable=AsyncMock) as mock_notify:
                first = await service.refresh_account_login_state(account)
                second = await service.refresh_account_login_state(account)

        self.assertEqual(first["cookie_status"], "reauth_required")
        self.assertEqual(second["cookie_status"], "reauth_required")
        self.assertEqual(account.cookie_status, "reauth_required")
        self.assertEqual(mock_notify.await_count, 1)
        self.assertIsNotNone(account.reauth_notified_at)

    async def test_list_accounts_exposes_login_state_fields(self):
        async with await self._new_session() as session:
            user = User(username="account-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()

            account = MihoyoAccount(
                user_id=user.id,
                nickname="测试账号",
                mihoyo_uid="10001",
                cookie_encrypted="encrypted-cookie",
                cookie_status="reauth_required",
                last_refresh_status="reauth_required",
                last_refresh_message="Cookie 已过期，请重新扫码更新网页登录态",
                created_at=datetime(2026, 3, 16, 16, 30, 0),
                last_cookie_check=datetime(2026, 3, 16, 16, 30, 0),
                last_refresh_attempt_at=datetime(2026, 3, 16, 16, 30, 0),
            )
            session.add(account)
            await session.commit()

            response = await list_accounts(current_user=user, db=session)

        self.assertEqual(response.total, 1)
        self.assertEqual(response.accounts[0].last_refresh_status, "reauth_required")
        self.assertEqual(response.accounts[0].last_refresh_message, "Cookie 已过期，请重新扫码更新网页登录态")
        self.assertEqual(response.accounts[0].created_at.utcoffset(), timedelta(hours=8))
        self.assertEqual(response.accounts[0].created_at.hour, 0)
        self.assertEqual(response.accounts[0].last_cookie_check.hour, 0)
        self.assertEqual(response.accounts[0].last_refresh_attempt_at.hour, 0)
        account_payload = response.accounts[0].model_dump(mode="json")
        self.assertTrue(account_payload["created_at"].endswith("+08:00"))
        self.assertTrue(account_payload["last_cookie_check"].endswith("+08:00"))
        self.assertTrue(account_payload["last_refresh_attempt_at"].endswith("+08:00"))

    async def test_refresh_login_state_endpoint_returns_updated_status(self):
        async with await self._new_session() as session:
            user = User(username="refresh-endpoint-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()

            account = MihoyoAccount(
                user_id=user.id,
                cookie_encrypted="encrypted-cookie",
                cookie_status="expired",
            )
            session.add(account)
            await session.commit()

            with patch("app.api.accounts.LoginStateService") as mock_service_cls:
                mock_service = mock_service_cls.return_value
                mock_service.refresh_account_login_state = AsyncMock(return_value={
                    "account_id": account.id,
                    "cookie_status": "reauth_required",
                    "message": "Cookie 已过期，请重新扫码更新网页登录态",
                })

                response = await refresh_login_state(account.id, current_user=user, db=session)

        self.assertEqual(response["cookie_status"], "reauth_required")
        self.assertEqual(response["message"], "Cookie 已过期，请重新扫码更新网页登录态")

    async def test_notification_service_sends_reauth_required_email_once_until_recovered(self):
        async with await self._new_session() as session:
            user = User(
                username="reauth-mail-user",
                password_hash="x",
                role="user",
                is_active=True,
                email="notify@example.com",
                email_notify=True,
                notify_on="always",
            )
            session.add(user)
            session.add(
                SystemSetting(
                    smtp_enabled=True,
                    smtp_host="smtp.example.com",
                    smtp_port=465,
                    smtp_user="mailer@example.com",
                    smtp_password_encrypted=None,
                    smtp_use_ssl=True,
                    smtp_sender_name="签到助手",
                    smtp_sender_email="mailer@example.com",
                )
            )
            await session.flush()

            account = MihoyoAccount(
                user_id=user.id,
                nickname="测试账号",
                mihoyo_uid="10001",
                cookie_encrypted="encrypted-cookie",
                cookie_status="reauth_required",
            )
            session.add(account)
            await session.commit()

            service = NotificationService()
            service._send_login_state_email = AsyncMock()

            await service.send_reauth_required_notification(user.id, account, session)
            await service.send_reauth_required_notification(user.id, account, session)

            account.cookie_status = "valid"
            account.reauth_notified_at = None
            await session.commit()
            await service.send_reauth_required_notification(user.id, account, session)

        self.assertEqual(service._send_login_state_email.await_count, 2)

    async def test_notification_service_prefers_database_smtp_config(self):
        async with await self._new_session() as session:
            user = User(
                username="user1",
                password_hash="x",
                role="user",
                is_active=True,
                email="notify@example.com",
                email_notify=True,
                notify_on="always",
            )
            session.add(user)
            session.add(
                SystemSetting(
                    smtp_enabled=True,
                    smtp_host="smtp.example.com",
                    smtp_port=465,
                    smtp_user="mailer@example.com",
                    smtp_password_encrypted=None,
                    smtp_use_ssl=True,
                    smtp_sender_name="签到助手",
                    smtp_sender_email="mailer@example.com",
                )
            )
            await session.commit()

            service = NotificationService()
            service._send_email = AsyncMock()

            summary = CheckinSummary(
                total=1,
                success=1,
                failed=0,
                already_signed=0,
                risk=0,
                results=[CheckinResult(account_id=1, status="success", message="ok")],
            )

            await service.send_checkin_report(user.id, summary, session)

        args = service._send_email.await_args.args
        self.assertEqual(args[0], "notify@example.com")
        self.assertEqual(args[2]["hostname"], "smtp.example.com")
        self.assertEqual(args[2]["sender_email"], "mailer@example.com")

    async def test_notification_service_dedupes_identical_summary_within_window(self):
        async with await self._new_session() as session:
            user = User(
                username="user-dedupe",
                password_hash="x",
                role="user",
                is_active=True,
                email="notify@example.com",
                email_notify=True,
                notify_on="always",
            )
            session.add(user)
            session.add(
                SystemSetting(
                    smtp_enabled=True,
                    smtp_host="smtp.example.com",
                    smtp_port=465,
                    smtp_user="mailer@example.com",
                    smtp_password_encrypted=None,
                    smtp_use_ssl=True,
                    smtp_sender_name="签到助手",
                    smtp_sender_email="mailer@example.com",
                )
            )
            await session.commit()

            service = NotificationService()
            service._send_email = AsyncMock()
            summary = CheckinSummary(
                total=1,
                success=1,
                failed=0,
                already_signed=0,
                risk=0,
                results=[CheckinResult(account_id=1, status="success", message="ok")],
            )
            fixed_now = datetime(2026, 3, 17, 4, 0, 0, tzinfo=timezone.utc)

            with patch("app.services.notifier.utc_now", return_value=fixed_now):
                await service.send_checkin_report(user.id, summary, session, source="manual_execute")
                await service.send_checkin_report(user.id, summary, session, source="scheduled_checkin")

        service._send_email.assert_awaited_once()

    async def test_notification_service_allows_same_summary_after_dedupe_window(self):
        async with await self._new_session() as session:
            user = User(
                username="user-dedupe-window",
                password_hash="x",
                role="user",
                is_active=True,
                email="notify@example.com",
                email_notify=True,
                notify_on="always",
            )
            session.add(user)
            session.add(
                SystemSetting(
                    smtp_enabled=True,
                    smtp_host="smtp.example.com",
                    smtp_port=465,
                    smtp_user="mailer@example.com",
                    smtp_password_encrypted=None,
                    smtp_use_ssl=True,
                    smtp_sender_name="签到助手",
                    smtp_sender_email="mailer@example.com",
                )
            )
            await session.commit()

            service = NotificationService()
            service._send_email = AsyncMock()
            summary = CheckinSummary(
                total=1,
                success=1,
                failed=0,
                already_signed=0,
                risk=0,
                results=[CheckinResult(account_id=1, status="success", message="ok")],
            )
            first_now = datetime(2026, 3, 17, 4, 0, 0, tzinfo=timezone.utc)
            second_now = first_now + timedelta(seconds=NotificationService.DEDUPE_WINDOW_SECONDS + 1)

            with patch("app.services.notifier.utc_now", side_effect=[first_now, second_now]):
                await service.send_checkin_report(user.id, summary, session, source="manual_execute")
                await service.send_checkin_report(user.id, summary, session, source="manual_execute")

        self.assertEqual(service._send_email.await_count, 2)

    async def test_notification_service_does_not_dedupe_different_summary(self):
        async with await self._new_session() as session:
            user = User(
                username="user-dedupe-different",
                password_hash="x",
                role="user",
                is_active=True,
                email="notify@example.com",
                email_notify=True,
                notify_on="always",
            )
            session.add(user)
            session.add(
                SystemSetting(
                    smtp_enabled=True,
                    smtp_host="smtp.example.com",
                    smtp_port=465,
                    smtp_user="mailer@example.com",
                    smtp_password_encrypted=None,
                    smtp_use_ssl=True,
                    smtp_sender_name="签到助手",
                    smtp_sender_email="mailer@example.com",
                )
            )
            await session.commit()

            service = NotificationService()
            service._send_email = AsyncMock()
            success_summary = CheckinSummary(
                total=1,
                success=1,
                failed=0,
                already_signed=0,
                risk=0,
                results=[CheckinResult(account_id=1, status="success", message="ok")],
            )
            failed_summary = CheckinSummary(
                total=1,
                success=0,
                failed=1,
                already_signed=0,
                risk=0,
                results=[CheckinResult(account_id=1, status="failed", message="boom")],
            )
            fixed_now = datetime(2026, 3, 17, 4, 0, 0, tzinfo=timezone.utc)

            with patch("app.services.notifier.utc_now", return_value=fixed_now):
                await service.send_checkin_report(user.id, success_summary, session, source="manual_execute")
                await service.send_checkin_report(user.id, failed_summary, session, source="manual_execute")

        self.assertEqual(service._send_email.await_count, 2)

    async def test_notification_service_skips_when_user_notification_disabled(self):
        async with await self._new_session() as session:
            user = User(
                username="user-disabled",
                password_hash="x",
                role="user",
                is_active=True,
                email="notify@example.com",
                email_notify=False,
                notify_on="always",
            )
            session.add(user)
            session.add(
                SystemSetting(
                    smtp_enabled=True,
                    smtp_host="smtp.example.com",
                    smtp_port=465,
                    smtp_user="mailer@example.com",
                    smtp_password_encrypted=None,
                    smtp_use_ssl=True,
                    smtp_sender_name="签到助手",
                    smtp_sender_email="mailer@example.com",
                )
            )
            await session.commit()

            service = NotificationService()
            service._send_email = AsyncMock()

            summary = CheckinSummary(
                total=1,
                success=0,
                failed=1,
                already_signed=0,
                risk=0,
                results=[CheckinResult(account_id=1, status="failed", message="boom")],
            )

            await service.send_checkin_report(user.id, summary, session)

        service._send_email.assert_not_awaited()

    async def test_notification_service_skips_success_report_when_failure_only(self):
        async with await self._new_session() as session:
            user = User(
                username="user-failure-only",
                password_hash="x",
                role="user",
                is_active=True,
                email="notify@example.com",
                email_notify=True,
                notify_on="failure_only",
            )
            session.add(user)
            session.add(
                SystemSetting(
                    smtp_enabled=True,
                    smtp_host="smtp.example.com",
                    smtp_port=465,
                    smtp_user="mailer@example.com",
                    smtp_password_encrypted=None,
                    smtp_use_ssl=True,
                    smtp_sender_name="签到助手",
                    smtp_sender_email="mailer@example.com",
                )
            )
            await session.commit()

            service = NotificationService()
            service._send_email = AsyncMock()

            summary = CheckinSummary(
                total=1,
                success=1,
                failed=0,
                already_signed=0,
                risk=0,
                results=[CheckinResult(account_id=1, status="success", message="ok")],
            )

            await service.send_checkin_report(user.id, summary, session)

        service._send_email.assert_not_awaited()

    async def test_send_email_formats_chinese_sender_name_as_rfc_address(self):
        async with await self._new_session() as session:
            service = NotificationService()
            summary = CheckinSummary(
                total=1,
                success=1,
                failed=0,
                already_signed=0,
                risk=0,
                results=[CheckinResult(account_id=1, status="success", message="ok")],
            )
            smtp_config = {
                "hostname": "smtp.example.com",
                "port": 465,
                "username": "mailer@example.com",
                "password": "secret",
                "use_ssl": True,
                "sender_name": "米游社签到助手",
                "sender_email": "mailer@example.com",
            }

            with patch("app.services.notifier.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
                await service._send_email("notify@example.com", summary, smtp_config)

        msg = mock_send.await_args.args[0]
        serialized_from = next(
            line for line in msg.as_string().splitlines() if line.startswith("From:")
        )
        self.assertIn("<mailer@example.com>", serialized_from)
        self.assertNotIn("=?utf-8?b?57Gz5ri456S+562+5Yiw5Yqp5omLIDxtYWlsZXJAZXhhbXBsZS5jb20+", serialized_from)
        from_header = msg["From"]
        decoded_parts = []
        for value, charset in decode_header(from_header):
            if isinstance(value, bytes):
                decoded_parts.append(value.decode(charset or "utf-8"))
            else:
                decoded_parts.append(value)
        decoded_from = "".join(decoded_parts)
        self.assertEqual(decoded_from, "米游社签到助手 <mailer@example.com>")

    async def test_send_email_uses_plain_address_when_sender_name_is_empty(self):
        async with await self._new_session() as session:
            service = NotificationService()
            summary = CheckinSummary(
                total=1,
                success=1,
                failed=0,
                already_signed=0,
                risk=0,
                results=[CheckinResult(account_id=1, status="success", message="ok")],
            )
            smtp_config = {
                "hostname": "smtp.example.com",
                "port": 465,
                "username": "mailer@example.com",
                "password": "secret",
                "use_ssl": True,
                "sender_name": "",
                "sender_email": "mailer@example.com",
            }

            with patch("app.services.notifier.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
                await service._send_email("notify@example.com", summary, smtp_config)

        msg = mock_send.await_args.args[0]
        serialized_from = next(
            line for line in msg.as_string().splitlines() if line.startswith("From:")
        )
        self.assertEqual(serialized_from, "From: mailer@example.com")

    async def test_send_email_renders_account_and_role_context_in_html(self):
        async with await self._new_session() as session:
            service = NotificationService()
            summary = CheckinSummary(
                total=1,
                success=1,
                failed=0,
                already_signed=0,
                risk=0,
                results=[
                    CheckinResult(
                        account_id=1,
                        game_role_id=2,
                        account_nickname="测试账号",
                        game_biz="hk4e_cn",
                        game_nickname="胡桃",
                        status="success",
                        message="签到成功",
                        total_sign_days=123,
                        reward_name="原石",
                        reward_cnt=20,
                    )
                ],
            )
            smtp_config = {
                "hostname": "smtp.example.com",
                "port": 465,
                "username": "mailer@example.com",
                "password": "secret",
                "use_ssl": True,
                "sender_name": "签到助手",
                "sender_email": "mailer@example.com",
            }

            with patch("app.services.notifier.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
                await service._send_email("notify@example.com", summary, smtp_config)

        msg = mock_send.await_args.args[0]
        html_part = msg.get_payload()[0].get_payload(decode=True).decode("utf-8")
        self.assertIn("测试账号", html_part)
        self.assertIn("原神", html_part)
        self.assertIn("胡桃", html_part)
        self.assertIn("123", html_part)
        self.assertIn("原石 ×20", html_part)

    async def test_send_email_places_summary_before_details(self):
        async with await self._new_session() as session:
            service = NotificationService()
            summary = CheckinSummary(
                total=2,
                success=1,
                failed=1,
                already_signed=0,
                risk=0,
                results=[
                    CheckinResult(account_id=1, status="success", message="ok"),
                    CheckinResult(account_id=2, status="failed", message="boom"),
                ],
            )
            smtp_config = {
                "hostname": "smtp.example.com",
                "port": 465,
                "username": "mailer@example.com",
                "password": "secret",
                "use_ssl": True,
                "sender_name": "签到助手",
                "sender_email": "mailer@example.com",
            }

            with patch("app.services.notifier.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
                await service._send_email("notify@example.com", summary, smtp_config)

        html_part = mock_send.await_args.args[0].get_payload()[0].get_payload(decode=True).decode("utf-8")
        self.assertIn("执行总数", html_part)
        self.assertIn("结果详情", html_part)
        self.assertLess(html_part.index("执行总数"), html_part.index("结果详情"))

    async def test_send_email_orders_cards_with_success_first(self):
        async with await self._new_session() as session:
            service = NotificationService()
            summary = CheckinSummary(
                total=3,
                success=1,
                failed=1,
                already_signed=1,
                risk=0,
                results=[
                    CheckinResult(account_id=2, account_nickname="失败账号", status="failed", message="失败消息"),
                    CheckinResult(account_id=1, account_nickname="成功账号", status="success", message="成功消息"),
                    CheckinResult(account_id=3, account_nickname="已签账号", status="already_signed", message="今日已签到"),
                ],
            )
            smtp_config = {
                "hostname": "smtp.example.com",
                "port": 465,
                "username": "mailer@example.com",
                "password": "secret",
                "use_ssl": True,
                "sender_name": "签到助手",
                "sender_email": "mailer@example.com",
            }

            with patch("app.services.notifier.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
                await service._send_email("notify@example.com", summary, smtp_config)

        html_part = mock_send.await_args.args[0].get_payload()[0].get_payload(decode=True).decode("utf-8")
        self.assertLess(html_part.index("成功账号"), html_part.index("失败账号"))
        self.assertLess(html_part.index("已签账号"), html_part.index("失败账号"))

    async def test_manual_execute_checkin_triggers_notification_service(self):
        async with await self._new_session() as session:
            user = User(
                username="manual-user",
                password_hash="x",
                role="user",
                is_active=True,
                email="notify@example.com",
                email_notify=True,
                notify_on="always",
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

            expected_summary = CheckinSummary(
                total=1,
                success=1,
                failed=0,
                already_signed=0,
                risk=0,
                results=[CheckinResult(account_id=1, status="success", message="ok")],
            )

            with patch("app.api.tasks.CheckinService") as mock_checkin_cls, patch(
                "app.services.notifier.notification_service.send_checkin_report",
                new_callable=AsyncMock,
            ) as mock_send_report:
                mock_checkin = mock_checkin_cls.return_value
                mock_checkin.execute_for_user = AsyncMock(return_value=expected_summary)

                summary = await execute_checkin(current_user=user, db=session)

        self.assertEqual(summary, expected_summary)
        mock_checkin.execute_for_user.assert_awaited_once_with(user.id)
        mock_send_report.assert_awaited_once_with(
            user.id,
            expected_summary,
            session,
            source="manual_execute",
        )

    async def test_list_logs_filters_and_serializes_executed_at_by_east_eight_boundary(self):
        async with await self._new_session() as session:
            user = User(username="log-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()

            account = MihoyoAccount(user_id=user.id, nickname="测试账号", cookie_encrypted="encrypted", cookie_status="valid")
            session.add(account)
            await session.flush()

            session.add(
                TaskLog(
                    account_id=account.id,
                    task_type="checkin",
                    status="success",
                    message="ok",
                    executed_at=datetime(2026, 3, 16, 16, 30, 0),
                )
            )
            await session.commit()

            response = await list_logs(
                page=1,
                page_size=20,
                account_id=None,
                status=None,
                date_start="2026-03-17",
                date_end="2026-03-17",
                game=None,
                current_user=user,
                db=session,
            )

        self.assertEqual(response.total, 1)
        self.assertEqual(len(response.logs), 1)
        self.assertEqual(response.logs[0].executed_at.utcoffset(), timedelta(hours=8))
        self.assertEqual(response.logs[0].executed_at.hour, 0)
        self.assertEqual(response.logs[0].executed_at.minute, 30)
        self.assertTrue(response.logs[0].model_dump(mode="json")["executed_at"].endswith("+08:00"))

    async def test_list_logs_filters_by_game_family(self):
        async with await self._new_session() as session:
            user = User(username="log-game-filter-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()

            account = MihoyoAccount(
                user_id=user.id,
                nickname="测试账号",
                cookie_encrypted="encrypted",
                cookie_status="valid",
            )
            session.add(account)
            await session.flush()

            genshin_role = GameRole(
                account_id=account.id,
                game_biz="hk4e_cn",
                game_uid="10001",
                nickname="原神角色",
                region="cn_gf01",
                is_enabled=True,
            )
            genshin_bili_role = GameRole(
                account_id=account.id,
                game_biz="hk4e_bilibili",
                game_uid="10002",
                nickname="原神B服角色",
                region="cn_gf01",
                is_enabled=True,
            )
            zzz_role = GameRole(
                account_id=account.id,
                game_biz="nap_cn",
                game_uid="20001",
                nickname="绝区零角色",
                region="prod_gf_cn",
                is_enabled=True,
            )
            session.add_all([genshin_role, genshin_bili_role, zzz_role])
            await session.flush()

            session.add_all(
                [
                    TaskLog(
                        account_id=account.id,
                        game_role_id=genshin_role.id,
                        task_type="checkin",
                        status="success",
                        message="原神签到",
                    ),
                    TaskLog(
                        account_id=account.id,
                        game_role_id=genshin_bili_role.id,
                        task_type="checkin",
                        status="success",
                        message="原神B服签到",
                    ),
                    TaskLog(
                        account_id=account.id,
                        game_role_id=zzz_role.id,
                        task_type="checkin",
                        status="success",
                        message="绝区零签到",
                    ),
                ]
            )
            await session.commit()

            all_logs = await list_logs(
                page=1,
                page_size=20,
                account_id=None,
                status=None,
                date_start=None,
                date_end=None,
                game=None,
                current_user=user,
                db=session,
            )
            genshin_logs = await list_logs(
                page=1,
                page_size=20,
                account_id=None,
                status=None,
                date_start=None,
                date_end=None,
                game="hk4e",
                current_user=user,
                db=session,
            )
            zzz_logs = await list_logs(
                page=1,
                page_size=20,
                account_id=None,
                status=None,
                date_start=None,
                date_end=None,
                game="nap",
                current_user=user,
                db=session,
            )
            unknown_logs = await list_logs(
                page=1,
                page_size=20,
                account_id=None,
                status=None,
                date_start=None,
                date_end=None,
                game="unknown",
                current_user=user,
                db=session,
            )

        self.assertEqual(all_logs.total, 3)
        self.assertEqual(genshin_logs.total, 2)
        self.assertEqual({log.game_biz for log in genshin_logs.logs}, {"hk4e_cn", "hk4e_bilibili"})
        self.assertEqual(zzz_logs.total, 1)
        self.assertEqual(zzz_logs.logs[0].game_biz, "nap_cn")
        self.assertEqual(unknown_logs.total, 3)

    async def test_get_today_status_uses_east_eight_day_boundary(self):
        async with await self._new_session() as session:
            user = User(username="status-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()

            account = MihoyoAccount(user_id=user.id, nickname="测试账号", cookie_encrypted="encrypted", cookie_status="valid")
            session.add(account)
            await session.flush()

            role = GameRole(
                account_id=account.id,
                game_biz="hk4e_cn",
                game_uid="10001",
                region="cn_gf01",
                is_enabled=True,
            )
            session.add(role)
            await session.flush()

            session.add(
                TaskLog(
                    account_id=account.id,
                    game_role_id=role.id,
                    task_type="checkin",
                    status="success",
                    message="ok",
                    executed_at=datetime(2026, 3, 16, 16, 30, 0),
                )
            )
            await session.commit()

            with patch("app.api.tasks.get_shanghai_date", return_value=date(2026, 3, 17)):
                response = await get_today_status(current_user=user, db=session)

        self.assertEqual(response["signed_today"], 1)
        self.assertEqual(response["pending"], 0)

    async def test_get_sign_calendar_groups_logs_by_east_eight_date(self):
        async with await self._new_session() as session:
            user = User(username="calendar-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()

            account = MihoyoAccount(user_id=user.id, nickname="测试账号", cookie_encrypted="encrypted", cookie_status="valid")
            session.add(account)
            await session.flush()

            session.add(
                TaskLog(
                    account_id=account.id,
                    task_type="checkin",
                    status="success",
                    message="ok",
                    executed_at=datetime(2026, 3, 16, 16, 30, 0),
                )
            )
            await session.commit()

            with patch("app.api.logs.get_shanghai_date", return_value=date(2026, 3, 17)):
                response = await get_sign_calendar(days=1, current_user=user, db=session)

        self.assertEqual(len(response["calendar"]), 1)
        self.assertEqual(response["calendar"][0]["date"], "2026-03-17")
        self.assertEqual(response["calendar"][0]["success"], 1)
        self.assertEqual(response["calendar"][0]["total"], 1)

    async def test_system_settings_service_auto_creates_table_for_legacy_database(self):
        async with self.engine.begin() as conn:
            # 统一测试基座默认会先建出完整表结构；这里显式删除 `system_settings`，
            # 用来模拟“升级到新代码时旧部署里还没有这张表”的真实 MySQL 场景。
            await conn.exec_driver_sql("DROP TABLE IF EXISTS system_settings")

        async with await self._new_session() as session:
            service = CheckinService(session)
            config = await service.settings_service.get_or_create()
            self.assertFalse(config.smtp_enabled)

        async with await self._new_session() as verify_session:
            # `get_or_create()` 会在独立短事务里补建默认配置，避免把调用方 session 的其他脏数据一并提交。
            # MySQL 的当前事务快照不会自动看见那笔独立提交，因此这里必须用新 session 验证真实落库结果，
            # 否则测试测到的只是“旧事务还没刷新视图”，不是 system_settings 自愈失败。
            stored = (await verify_session.execute(select(SystemSetting))).scalar_one()

        self.assertEqual(stored.id, config.id)

    async def test_get_me_returns_visible_menu_keys_by_role(self):
        async with await self._new_session() as session:
            admin = User(username="menu-admin", password_hash="x", role="admin", is_active=True)
            user = User(username="menu-user", password_hash="x", role="user", is_active=True)
            session.add_all([admin, user])
            await session.commit()
            await session.refresh(admin)
            await session.refresh(user)

            admin_response = await get_me(current_user=admin, db=session)
            user_response = await get_me(current_user=user, db=session)

        self.assertIn("dashboard", admin_response.visible_menu_keys)
        self.assertIn("admin_users", admin_response.visible_menu_keys)
        self.assertIn("admin_menu_management", admin_response.visible_menu_keys)
        self.assertIn("dashboard", user_response.visible_menu_keys)
        self.assertNotIn("admin_users", user_response.visible_menu_keys)
        self.assertNotIn("admin_menu_management", user_response.visible_menu_keys)

    async def test_update_menu_visibility_persists_and_affects_visible_menu_keys(self):
        async with await self._new_session() as session:
            admin = User(username="visibility-admin", password_hash="x", role="admin", is_active=True)
            user = User(username="visibility-user", password_hash="x", role="user", is_active=True)
            session.add_all([admin, user])
            await session.commit()
            await session.refresh(admin)
            await session.refresh(user)

            updated = await update_menu_visibility(
                payload=AdminMenuVisibilityUpdate(
                    items=[
                        AdminMenuVisibilityItemUpdate(key="logs", user_visible=False, admin_visible=True),
                        AdminMenuVisibilityItemUpdate(key="admin_users", user_visible=False, admin_visible=False),
                    ]
                ),
                admin=admin,
                db=session,
            )
            read_back = await get_menu_visibility(admin=admin, db=session)
            admin_response = await get_me(current_user=admin, db=session)
            user_response = await get_me(current_user=user, db=session)

        by_key = {item.key: item for item in updated.items}
        self.assertFalse(by_key["logs"].user_visible)
        self.assertFalse(by_key["admin_users"].admin_visible)
        self.assertTrue(by_key["admin_menu_management"].admin_visible)
        self.assertFalse(by_key["admin_menu_management"].editable)
        self.assertEqual(len(read_back.items), len(updated.items))
        self.assertNotIn("logs", user_response.visible_menu_keys)
        self.assertIn("logs", admin_response.visible_menu_keys)
        self.assertNotIn("admin_users", admin_response.visible_menu_keys)
        self.assertIn("admin_menu_management", admin_response.visible_menu_keys)

    async def test_update_menu_visibility_rejects_unknown_or_guarded_keys(self):
        async with await self._new_session() as session:
            admin = User(username="guard-admin", password_hash="x", role="admin", is_active=True)
            session.add(admin)
            await session.commit()
            await session.refresh(admin)

            with self.assertRaises(HTTPException) as unknown_ctx:
                await update_menu_visibility(
                    payload=AdminMenuVisibilityUpdate(
                        items=[AdminMenuVisibilityItemUpdate(key="unknown_menu", user_visible=True, admin_visible=True)]
                    ),
                    admin=admin,
                    db=session,
                )

            with self.assertRaises(HTTPException) as guarded_ctx:
                await update_menu_visibility(
                    payload=AdminMenuVisibilityUpdate(
                        items=[
                            AdminMenuVisibilityItemUpdate(
                                key="admin_menu_management",
                                user_visible=False,
                                admin_visible=False,
                            )
                        ]
                    ),
                    admin=admin,
                    db=session,
                )

        self.assertEqual(unknown_ctx.exception.status_code, 400)
        self.assertIn("unknown_menu", unknown_ctx.exception.detail)
        self.assertEqual(guarded_ctx.exception.status_code, 400)
        self.assertIn("admin_menu_management", guarded_ctx.exception.detail)

    async def test_get_menu_visibility_recovers_legacy_system_settings_without_menu_column(self):
        async with self.engine.begin() as conn:
            await conn.exec_driver_sql("DROP TABLE IF EXISTS system_settings")
            await conn.exec_driver_sql(
                """
                CREATE TABLE system_settings (
                    id BIGINT PRIMARY KEY,
                    smtp_enabled BOOLEAN,
                    smtp_host VARCHAR(255),
                    smtp_port INTEGER,
                    smtp_user VARCHAR(255),
                    smtp_password_encrypted VARCHAR(1024),
                    smtp_use_ssl BOOLEAN,
                    smtp_sender_name VARCHAR(255),
                    smtp_sender_email VARCHAR(255),
                    hyperion_device_id VARCHAR(64),
                    hyperion_device_fp VARCHAR(64),
                    hyperion_device_fp_updated_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
            await conn.exec_driver_sql(
                """
                INSERT INTO system_settings (
                    id, smtp_enabled, smtp_port, smtp_use_ssl, updated_at
                ) VALUES (1, 0, 465, 1, '2026-03-18 00:00:00')
                """
            )

        async with await self._new_session() as session:
            admin = User(username="legacy-admin", password_hash="x", role="admin", is_active=True)
            session.add(admin)
            await session.commit()
            await session.refresh(admin)

            response = await get_menu_visibility(admin=admin, db=session)
            result = await session.execute(select(SystemSetting))
            config = result.scalar_one()

        self.assertTrue(any(item.key == "dashboard" for item in response.items))
        self.assertIsNotNone(config.menu_visibility_json)


if __name__ == "__main__":
    unittest.main()
