import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "mysql+asyncmy://demo:demo@127.0.0.1:3306/miyoushe?charset=utf8mb4"

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import GameRole, MihoyoAccount
from app.models.task_log import TaskLog
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


class AccountCredentialHelperUnitTests(unittest.TestCase):
    def _build_account(
        self,
        *,
        stuid: str | None = "10001",
        mid: str | None = "mid-10001",
        stoken: str | None = "v2_test_stoken",
    ) -> MihoyoAccount:
        account = MihoyoAccount(user_id=1, stuid=stuid, mid=mid)
        if stoken is not None:
            account.stoken_encrypted = encrypt_text(stoken)
        return account

    def test_get_root_credential_snapshot_returns_stuid_mid_stoken(self):
        from app.services.account_credentials import AccountCredentialService

        service = AccountCredentialService(db=None)
        account = self._build_account()

        snapshot = service.get_root_credential_snapshot(account)
        self.assertEqual(snapshot.stuid, "10001")
        self.assertEqual(snapshot.mid, "mid-10001")
        self.assertEqual(snapshot.stoken, "v2_test_stoken")

    def test_build_stoken_cookie_for_root_api_contains_stoken_variants_and_mid(self):
        from app.services.account_credentials import AccountCredentialService

        service = AccountCredentialService(db=None)
        account = self._build_account()

        cookie = service.build_stoken_cookie_for_root_api(account)
        self.assertIn("stuid=10001", cookie)
        self.assertIn("stoken=v2_test_stoken", cookie)
        self.assertIn("stoken_v2=v2_test_stoken", cookie)
        self.assertIn("mid=mid-10001", cookie)

    def test_build_stoken_cookie_for_authkey_keeps_minimal_stoken_shape(self):
        from app.services.account_credentials import AccountCredentialService

        service = AccountCredentialService(db=None)
        account = self._build_account()

        cookie = service.build_stoken_cookie_for_authkey(account)
        self.assertEqual(cookie, "mid=mid-10001; stoken=v2_test_stoken; stuid=10001")
        self.assertNotIn("stoken_v2=", cookie)
        self.assertNotIn("ltuid=", cookie)
        self.assertIn("mid=mid-10001", cookie)

    def test_get_root_credential_snapshot_raises_when_stoken_missing(self):
        from app.services.account_credentials import (
            ROOT_CREDENTIAL_REAUTH_MESSAGE,
            AccountCredentialService,
            RootCredentialRefreshError,
        )

        service = AccountCredentialService(db=None)
        account = self._build_account(stoken=None)

        with self.assertRaises(RootCredentialRefreshError) as ctx:
            service.get_root_credential_snapshot(account)
        self.assertIn(ROOT_CREDENTIAL_REAUTH_MESSAGE, str(ctx.exception))

    def test_build_stoken_cookie_for_root_api_raises_when_stuid_missing(self):
        from app.services.account_credentials import (
            ROOT_CREDENTIAL_REAUTH_MESSAGE,
            AccountCredentialService,
            RootCredentialRefreshError,
        )

        service = AccountCredentialService(db=None)
        account = self._build_account(stuid=None)

        with self.assertRaises(RootCredentialRefreshError) as ctx:
            service.build_stoken_cookie_for_root_api(account)
        self.assertIn(ROOT_CREDENTIAL_REAUTH_MESSAGE, str(ctx.exception))


class _CookieShapeSensitiveAsyncClient:
    def __init__(self):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None):
        self.calls.append({"method": "GET", "url": url, "headers": headers})
        cookie = str((headers or {}).get("Cookie") or "")
        if "stoken=" not in cookie:
            return _FakeResponse({"retcode": -100, "message": "登录状态失效，请重新登录", "data": {}})

        if "getLTokenBySToken" in url:
            return _FakeResponse({"retcode": 0, "message": "OK", "data": {"ltoken": "test-ltoken"}})

        return _FakeResponse(
            {
                "retcode": 0,
                "message": "OK",
                "data": {"uid": "10001", "cookie_token": "test-cookie-token"},
            }
        )

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

    async def test_refresh_root_tokens_sends_stoken_cookie_key_for_official_exchange(self):
        from app.services.account_credentials import AccountCredentialService

        async with await self._new_session() as session:
            user = await self._create_user(session, "credential-cookie-shape-user")
            account = MihoyoAccount(
                user_id=user.id,
                stoken_encrypted=encrypt_text("v2_test_stoken"),
                stuid="10001",
                mid="mid-10001",
                credential_source="passport_qr",
                credential_status="valid",
            )
            session.add(account)
            await session.commit()

            fake_client = _CookieShapeSensitiveAsyncClient()

            with patch("app.services.account_credentials.httpx.AsyncClient", new=lambda *args, **kwargs: fake_client):
                service = AccountCredentialService(session)
                result = await service.refresh_root_tokens(account)

        self.assertEqual(result["state"], "valid")
        first_cookie = fake_client.calls[0]["headers"]["Cookie"]
        self.assertIn("stoken=v2_test_stoken", first_cookie)
        self.assertIn("stoken_v2=v2_test_stoken", first_cookie)
        self.assertEqual(decrypt_text(account.ltoken_encrypted), "test-ltoken")
        self.assertEqual(decrypt_text(account.cookie_token_encrypted), "test-cookie-token")

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
        self.assertEqual(account.last_token_refresh_message, "高权限根凭据已失效，请重新扫码升级高权限登录")


class LegacyAccountUpgradeTests(MySqlIsolatedAsyncioTestCase):
    async def test_old_cookie_only_account_requires_upgrade_in_account_list(self):
        from app.api.accounts import list_accounts

        async with await self._new_session() as session:
            user = User(username="legacy-account-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()

            legacy_account = MihoyoAccount(
                user_id=user.id,
                nickname="旧网页登录账号",
                mihoyo_uid="10003",
                cookie_encrypted=encrypt_cookie("ltuid=10003; cookie_token=legacy-cookie-token"),
                cookie_status="valid",
                # 这里刻意模拟线上旧数据被历史逻辑写成 `valid` 的脏状态。
                # 无论旧值看起来多正常，只要账号仍停留在 Cookie-only 形态，
                # 列表都必须强制收口为“需要升级登录”。
                credential_status="valid",
            )
            session.add(legacy_account)
            await session.commit()

            response = await list_accounts(current_user=user, db=session)

        self.assertEqual(response.total, 1)
        self.assertTrue(response.accounts[0].upgrade_required)
        self.assertEqual(response.accounts[0].credential_status, "reauth_required")
        self.assertFalse(response.accounts[0].has_high_privilege_auth)

    async def test_refresh_login_state_requires_legacy_account_to_upgrade_high_privilege_auth(self):
        async with await self._new_session() as session:
            user = User(username="legacy-refresh-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()

            legacy_account = MihoyoAccount(
                user_id=user.id,
                nickname="旧网页登录账号",
                mihoyo_uid="10004",
                cookie_encrypted=encrypt_cookie("ltuid=10004; cookie_token=legacy-cookie-token"),
                cookie_status="valid",
            )
            session.add(legacy_account)
            await session.commit()

            service = LoginStateService(session)
            service.verify_cookie = AsyncMock(return_value={"state": "valid", "message": "登录态有效"})

            with patch(
                "app.services.login_state.notification_service.send_reauth_required_notification",
                new_callable=AsyncMock,
            ) as mock_notify:
                response = await service.refresh_account_login_state(legacy_account)

            await session.refresh(legacy_account)

        self.assertEqual(response["cookie_status"], "reauth_required")
        self.assertEqual(legacy_account.cookie_status, "reauth_required")
        self.assertEqual(legacy_account.credential_status, "reauth_required")
        self.assertEqual(legacy_account.last_refresh_status, "reauth_required")
        self.assertIn("升级高权限", response["message"])
        mock_notify.assert_awaited_once()


class AccountRoleSyncTests(MySqlIsolatedAsyncioTestCase):
    async def test_sync_account_roles_preserves_identity_and_checkin_logs(self):
        from sqlalchemy import select

        from app.services.account_role_sync import sync_account_roles

        async with await self._new_session() as session:
            user = User(username="role-sync-owner", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()

            account = MihoyoAccount(
                user_id=user.id,
                nickname="可刷新账号",
                mihoyo_uid="30001",
                cookie_status="valid",
                cookie_encrypted=encrypt_cookie("ltuid=30001; cookie_token=test-token"),
            )
            session.add(account)
            await session.flush()

            role = GameRole(
                account_id=account.id,
                game_biz="hk4e_cn",
                game_uid="80001",
                nickname="旧旅行者",
                region="cn_gf01",
                level=55,
                is_enabled=False,
            )
            session.add(role)
            await session.flush()

            session.add(TaskLog(
                account_id=account.id,
                game_role_id=role.id,
                task_type="checkin",
                status="success",
                message="刷新前已签到",
            ))
            await session.commit()
            await session.refresh(role)

            synced_roles = await sync_account_roles(
                db=session,
                account_id=account.id,
                role_payloads=[
                    {
                        "game_biz": "hk4e_cn",
                        "game_uid": "80001",
                        "nickname": "新旅行者",
                        "region": "cn_gf01",
                        "level": 60,
                    },
                ],
            )
            await session.commit()

            preserved_log = (
                await session.execute(
                    select(TaskLog).where(
                        TaskLog.account_id == account.id,
                        TaskLog.game_role_id == role.id,
                        TaskLog.task_type == "checkin",
                    )
                )
            ).scalar_one()

        self.assertEqual(len(synced_roles), 1)
        self.assertEqual(synced_roles[0].id, role.id)
        self.assertEqual(synced_roles[0].nickname, "新旅行者")
        self.assertFalse(synced_roles[0].is_enabled)
        self.assertEqual(preserved_log.status, "success")
        self.assertEqual(preserved_log.message, "刷新前已签到")


if __name__ == "__main__":
    unittest.main()
