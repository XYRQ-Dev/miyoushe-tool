import json
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.admin import get_email_settings, update_email_settings
from app.database import Base
from app.models.account import GameRole, MihoyoAccount
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.schemas.system_setting import AdminEmailSettingsUpdate
from app.schemas.task_log import CheckinSummary, CheckinResult
from app.services.checkin import CheckinApiError, CheckinGameConfig, CheckinService
from app.services.notifier import NotificationService
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

    async def test_do_sign_sends_uid_as_string_and_recognizes_risk(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            role = GameRole(id=2, account_id=1, game_biz="hkrpg_cn", game_uid="10001", region="prod_gf_cn")
            client = FakeClient(post_payload={"retcode": 0, "data": {"is_risk": True, "gt": "captcha"}})

            result = await service._do_sign(
                client,
                "ltuid=1;",
                CheckinGameConfig(act_id="e202304121516551", sign_game="hkrpg"),
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


if __name__ == "__main__":
    unittest.main()
