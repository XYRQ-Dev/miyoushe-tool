import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "mysql+asyncmy://demo:demo@127.0.0.1:3306/miyoushe?charset=utf8mb4"

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import MihoyoAccount
from app.models.user import User
from app.services.login_state import LoginStateService
from app.utils.crypto import decrypt_cookie, decrypt_text, encrypt_cookie, encrypt_text
from tests.mysql_test_case import MySqlIsolatedAsyncioTestCase


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None):
        self.calls.append({"method": "GET", "url": url, "headers": headers})
        if not self._responses:
            raise AssertionError("测试桩未提供足够的响应")
        return _FakeResponse(self._responses.pop(0))


class AccountCredentialTests(MySqlIsolatedAsyncioTestCase):
    async def _create_user(self, session: AsyncSession, username: str) -> User:
        # MySQL-only 后 `mihoyo_accounts.user_id -> users.id` 的真实外键会参与提交校验。
        # 这里若偷懒写死 `user_id=1` 而不先落父记录，测试失败点会从“登录态逻辑是否正确”
        # 退化成“测试数据本身不合法”，掩盖我们真正想验证的凭据刷新行为。
        user = User(username=username, password_hash="x", role="user", is_active=True)
        session.add(user)
        await session.flush()
        await session.refresh(user)
        return user

    async def test_persist_login_result_fetches_root_tokens_and_rebuilds_cookie(self):
        from app.services.account_credentials import AccountCredentialService

        async with await self._new_session() as session:
            user = await self._create_user(session, "credential-persist-user")
            account = MihoyoAccount(user_id=user.id)
            session.add(account)
            await session.commit()

            fake_client = _FakeAsyncClient([
                {"retcode": 0, "message": "OK", "data": {"ltoken": "test-ltoken"}},
                {
                    "retcode": 0,
                    "message": "OK",
                    "data": {"uid": "10001", "cookie_token": "test-cookie-token"},
                },
            ])

            with patch("app.services.account_credentials.httpx.AsyncClient", new=lambda *args, **kwargs: fake_client):
                service = AccountCredentialService(session)
                await service.persist_login_result(
                    account,
                    {
                        "stoken": "v2_test_stoken",
                        "stuid": "10001",
                        "mid": "mid-10001",
                        "login_ticket": "ticket-1",
                        "credential_source": "passport_qr",
                    },
                )

        self.assertEqual(decrypt_text(account.stoken_encrypted), "v2_test_stoken")
        self.assertEqual(decrypt_text(account.login_ticket_encrypted), "ticket-1")
        self.assertEqual(decrypt_text(account.ltoken_encrypted), "test-ltoken")
        self.assertEqual(decrypt_text(account.cookie_token_encrypted), "test-cookie-token")
        self.assertEqual(account.credential_status, "valid")
        self.assertEqual(account.cookie_status, "valid")
        rebuilt_cookie = decrypt_cookie(account.cookie_encrypted)
        self.assertIn("ltoken_v2=test-ltoken", rebuilt_cookie)
        self.assertIn("cookie_token=test-cookie-token", rebuilt_cookie)
        self.assertIn("stoken_v2=v2_test_stoken", rebuilt_cookie)
        self.assertIn("ltuid=10001", rebuilt_cookie)
        self.assertEqual(fake_client.calls[0]["url"], "https://passport-api.mihoyo.com/account/auth/api/getLTokenBySToken")
        self.assertEqual(fake_client.calls[1]["url"], "https://passport-api.mihoyo.com/account/auth/api/getCookieAccountInfoBySToken")

    async def test_refresh_account_login_state_self_heals_when_root_credentials_are_still_valid(self):
        async with await self._new_session() as session:
            user = await self._create_user(session, "credential-refresh-user")
            account = MihoyoAccount(
                user_id=user.id,
                cookie_encrypted=encrypt_cookie("ltuid=10001; cookie_token=expired-cookie-token"),
                cookie_status="expired",
                stoken_encrypted=encrypt_text("v2_test_stoken"),
                login_ticket_encrypted=encrypt_text("ticket-1"),
                stuid="10001",
                mid="mid-10001",
                credential_source="passport_qr",
                credential_status="valid",
            )
            session.add(account)
            await session.commit()

            fake_client = _FakeAsyncClient([
                {"retcode": 0, "message": "OK", "data": {"ltoken": "test-ltoken"}},
                {
                    "retcode": 0,
                    "message": "OK",
                    "data": {"uid": "10001", "cookie_token": "test-cookie-token"},
                },
            ])

            service = LoginStateService(session)
            service.verify_cookie = AsyncMock(return_value={"state": "expired", "message": "Cookie 已过期"})

            with patch("app.services.account_credentials.httpx.AsyncClient", new=lambda *args, **kwargs: fake_client), patch(
                "app.services.login_state.notification_service.send_reauth_required_notification",
                new_callable=AsyncMock,
            ) as mock_notify:
                result = await service.refresh_account_login_state(account)

        self.assertEqual(result["cookie_status"], "valid")
        self.assertEqual(account.cookie_status, "valid")
        self.assertEqual(account.credential_status, "valid")
        self.assertEqual(account.last_refresh_status, "valid")
        self.assertIn("自愈", account.last_refresh_message)
        rebuilt_cookie = decrypt_cookie(account.cookie_encrypted)
        self.assertIn("cookie_token=test-cookie-token", rebuilt_cookie)
        mock_notify.assert_not_awaited()

    async def test_ensure_work_cookie_marks_reauth_required_when_root_credentials_refresh_fails(self):
        from app.services.account_credentials import AccountCredentialService

        async with await self._new_session() as session:
            user = await self._create_user(session, "credential-ensure-user")
            account = MihoyoAccount(
                user_id=user.id,
                cookie_encrypted=encrypt_cookie("ltuid=10001; cookie_token=expired-cookie-token"),
                cookie_status="expired",
                stoken_encrypted=encrypt_text("v2_test_stoken"),
                login_ticket_encrypted=encrypt_text("ticket-1"),
                stuid="10001",
                mid="mid-10001",
                credential_source="passport_qr",
                credential_status="valid",
            )
            session.add(account)
            await session.commit()

            fake_client = _FakeAsyncClient([
                {"retcode": -100, "message": "登录失效", "data": {}},
            ])

            with patch("app.services.account_credentials.httpx.AsyncClient", new=lambda *args, **kwargs: fake_client):
                service = AccountCredentialService(session)
                result = await service.ensure_work_cookie(account)

        self.assertEqual(result["state"], "reauth_required")
        self.assertEqual(account.credential_status, "reauth_required")
        self.assertEqual(account.cookie_status, "reauth_required")
        self.assertEqual(account.last_token_refresh_status, "reauth_required")
        self.assertIn("重新扫码", account.last_token_refresh_message)


if __name__ == "__main__":
    unittest.main()
