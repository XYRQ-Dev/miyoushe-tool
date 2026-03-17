import json
import unittest
from datetime import datetime, timedelta, timezone, date
from email.header import decode_header
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.admin import get_email_settings, update_email_settings
from app.api.logs import get_sign_calendar, list_logs
from app.api.tasks import execute_checkin, get_today_status
from app.database import Base
from app.models.account import GameRole, MihoyoAccount
from app.models.system_setting import SystemSetting
from app.models.task_log import TaskLog
from app.models.user import User
from app.schemas.system_setting import AdminEmailSettingsUpdate
from app.schemas.task_log import CheckinSummary, CheckinResult
from app.services.checkin import CHECKIN_GAME_CONFIGS, CheckinApiError, CheckinGameConfig, CheckinService
from app.services.notifier import NotificationService
from app.utils.timezone import utc_now, utc_now_naive
from app.utils.crypto import decrypt_text
from app.utils.device import HYPERION_APP_VERSION


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, *, get_payload=None, post_payload=None):
        self.get_payload = get_payload
        self.post_payload = post_payload
        self.last_get = None
        self.last_post = None

    async def get(self, url, **kwargs):
        self.last_get = {"url": url, **kwargs}
        return FakeResponse(self.get_payload)

    async def post(self, url, **kwargs):
        self.last_post = {"url": url, **kwargs}
        return FakeResponse(self.post_payload)


class CheckinAndAdminTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _new_session(self):
        return self.session_factory()

    async def test_build_checkin_headers_include_starward_required_fields(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            headers = service._build_checkin_headers(
                "ltuid=1;",
                device_id="device-id",
                device_fp="device-fp",
                sign_game="hkrpg",
            )

        self.assertEqual(headers["x-rpc-signgame"], "hkrpg")
        self.assertEqual(headers["x-rpc-device_id"], "device-id")
        self.assertEqual(headers["x-rpc-device_fp"], "device-fp")
        self.assertEqual(headers["x-rpc-app_version"], HYPERION_APP_VERSION)
        self.assertIn("miHoYoBBS", headers["User-Agent"])
        self.assertTrue(headers["DS"])

    async def test_build_checkin_headers_supports_bh3_signgame(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            headers = service._build_checkin_headers(
                "ltuid=1;",
                device_id="device-id",
                device_fp="device-fp",
                sign_game="bh3",
            )

        self.assertEqual(headers["x-rpc-signgame"], "bh3")

    async def test_bh3_cn_uses_expected_checkin_game_config(self):
        config = CHECKIN_GAME_CONFIGS.get("bh3_cn")

        self.assertIsNotNone(config)
        self.assertEqual(config.act_id, "e202207181446311")
        self.assertEqual(config.sign_game, "bh3")

    async def test_utc_now_helpers_return_utc_with_and_without_tzinfo(self):
        aware_now = utc_now()
        naive_now = utc_now_naive()

        self.assertEqual(aware_now.tzinfo, timezone.utc)
        self.assertIsNone(naive_now.tzinfo)
        self.assertLess(abs((aware_now.replace(tzinfo=None) - naive_now).total_seconds()), 2)

    async def test_do_sign_sends_uid_as_string_and_recognizes_risk(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            role = GameRole(id=2, account_id=1, game_biz="hkrpg_cn", game_uid="10001", region="prod_gf_cn")
            client = FakeClient(post_payload={"retcode": 0, "data": {"is_risk": True, "gt": "captcha"}})

            result = await service._do_sign(
                client,
                "ltuid=1;",
                CheckinGameConfig(act_id="e202304121516551", sign_game="hkrpg"),
                MihoyoAccount(id=1, user_id=1, nickname="测试账号"),
                role,
                ("device-id", "device-fp"),
            )

        sent_body = json.loads(client.last_post["content"])
        self.assertEqual(sent_body["uid"], "10001")
        self.assertEqual(result.status, "risk")

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
            account = MihoyoAccount(user_id=1, cookie_encrypted="encrypted", cookie_status="valid")
            session.add(account)
            await session.flush()
            role = GameRole(account_id=account.id, game_biz="hkrpg_cn", game_uid="10001", region="prod_gf_cn", is_enabled=True)
            session.add(role)
            await session.commit()

            service = CheckinService(session)
            service._ensure_device_state = AsyncMock(return_value=("device-id", "device-fp"))
            service._get_sign_info = AsyncMock(return_value={"is_sign": False, "total_sign_day": 12})
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
                summary = await service.execute_for_user(1)

        self.assertEqual(summary.success, 1)
        service._sleep_between_info_and_sign.assert_awaited_once()
        service._sleep_between_roles.assert_awaited_once()

    async def test_execute_for_user_runs_bh3_cn_checkin(self):
        async with await self._new_session() as session:
            account = MihoyoAccount(user_id=1, cookie_encrypted="encrypted", cookie_status="valid")
            session.add(account)
            await session.flush()
            role = GameRole(account_id=account.id, game_biz="bh3_cn", game_uid="30001", region="android01", is_enabled=True)
            session.add(role)
            await session.commit()

            service = CheckinService(session)
            service._ensure_device_state = AsyncMock(return_value=("device-id", "device-fp"))
            service._get_sign_info = AsyncMock(return_value={"is_sign": False, "total_sign_day": 8})
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
                summary = await service.execute_for_user(1)

        self.assertEqual(summary.total, 1)
        self.assertEqual(summary.success, 1)
        service._get_sign_info.assert_awaited_once()
        service._do_sign.assert_awaited_once()

    async def test_execute_for_user_still_skips_unsupported_games_without_logging_failure(self):
        async with await self._new_session() as session:
            account = MihoyoAccount(user_id=1, cookie_encrypted="encrypted", cookie_status="valid")
            session.add(account)
            await session.flush()
            session.add(GameRole(account_id=account.id, game_biz="nap_cn", game_uid="20001", region="prod_gf_jp", is_enabled=True))
            await session.commit()

            service = CheckinService(session)
            service._ensure_device_state = AsyncMock(return_value=("device-id", "device-fp"))
            service._get_sign_info = AsyncMock()
            service._do_sign = AsyncMock()

            with patch("app.services.checkin.decrypt_cookie", return_value="ltuid=1;"):
                summary = await service.execute_for_user(1)

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
                CheckinGameConfig(act_id="e202207181446311", sign_game="bh3"),
                role,
                ("device-id", "device-fp"),
            )

        self.assertEqual(client.last_get["params"]["act_id"], "e202207181446311")
        self.assertEqual(client.last_get["headers"]["x-rpc-signgame"], "bh3")

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
                current_user=user,
                db=session,
            )

        self.assertEqual(response.total, 1)
        self.assertEqual(len(response.logs), 1)
        self.assertEqual(response.logs[0].executed_at.utcoffset(), timedelta(hours=8))
        self.assertEqual(response.logs[0].executed_at.hour, 0)
        self.assertEqual(response.logs[0].executed_at.minute, 30)

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

            with patch("app.api.tasks.get_current_app_date", return_value=date(2026, 3, 17)):
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

            with patch("app.api.logs.get_current_app_date", return_value=date(2026, 3, 17)):
                response = await get_sign_calendar(days=1, current_user=user, db=session)

        self.assertEqual(len(response["calendar"]), 1)
        self.assertEqual(response["calendar"][0]["date"], "2026-03-17")
        self.assertEqual(response["calendar"][0]["success"], 1)
        self.assertEqual(response["calendar"][0]["total"], 1)

    async def test_system_settings_service_auto_creates_table_for_legacy_database(self):
        legacy_engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with legacy_engine.begin() as conn:
            # 只创建旧版本已有的表，刻意不创建 system_settings，用来模拟线上旧库升级场景。
            await conn.run_sync(User.__table__.create)
            await conn.run_sync(MihoyoAccount.__table__.create)
            await conn.run_sync(GameRole.__table__.create)

        LegacySession = async_sessionmaker(legacy_engine, class_=AsyncSession, expire_on_commit=False)
        async with LegacySession() as session:
            service = CheckinService(session)
            config = await service.settings_service.get_or_create()
            self.assertFalse(config.smtp_enabled)

            stored = (await session.execute(select(SystemSetting))).scalar_one()
            self.assertEqual(stored.id, config.id)

        await legacy_engine.dispose()


if __name__ == "__main__":
    unittest.main()
