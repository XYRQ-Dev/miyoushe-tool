"""扫码授权回归：模拟数据库与上游，不启动应用生命周期或访问真实数据库。"""

import asyncio
import os
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["DATABASE_URL"] = "mysql+asyncmy://demo:demo@127.0.0.1:3306/miyoushe?charset=utf8mb4"

from fastapi import HTTPException, WebSocketDisconnect
from fastapi.testclient import TestClient

from app import main
from app.api import accounts
from app.models.account import MihoyoAccount
from app.services.passport_login import PassportQrLoginManager
from app.services.account_role_sync import RoleFetchError
from app.utils.crypto import encrypt_cookie


def fake_db(rows):
    db = MagicMock()
    results = []
    for row in rows:
        result = MagicMock()
        result.scalar_one_or_none.return_value = row
        results.append(result)
    db.execute = AsyncMock(side_effect=results)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


class QrAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = PassportQrLoginManager()
        self.manager_patch = patch.object(main, "passport_login_manager", self.manager)
        self.manager_patch.start()

    async def asyncTearDown(self):
        self.manager_patch.stop()
        for session in list(self.manager._sessions.values()):
            await self.manager.remove_session(session)

    def issue(self, target=None):
        grant = self.manager.issue_session(11, target)
        session = self.manager.get_session(grant["session_id"])
        session.start = AsyncMock()
        session.get_qr_image = AsyncMock(return_value="image")
        session.poll_login_status = AsyncMock(return_value="success")
        session.login_result = {"stoken": "test-secret", "stuid": "11", "mid": "test-mid"}
        return grant, session

    async def connect(self, grant, rows, frame=None, receive_error=None, *, role_error=None, cookie_state="valid", account_busy=False):
        socket = MagicMock()
        socket.accept = AsyncMock()
        socket.receive_json = AsyncMock(
            return_value=frame if frame is not None else {
                "type": "authenticate", "credential": grant["credential"],
                "user_id": 999, "account_id": 999,
            },
            side_effect=receive_error,
        )
        socket.send_json = AsyncMock()
        socket.close = AsyncMock()
        dbs = [fake_db(items) for items in rows]
        contexts = []
        for db in dbs:
            context = MagicMock()
            context.__aenter__ = AsyncMock(return_value=db)
            context.__aexit__ = AsyncMock(return_value=False)
            contexts.append(context)
        original_persist = main.AccountCredentialService.persist_login_result

        async def persist_result(account, login_result):
            return await original_persist(main.AccountCredentialService(dbs[-1]), account, login_result)

        async def ensure_cookie(account):
            if cookie_state == "valid":
                account.cookie_status = "valid"
                account.cookie_encrypted = encrypt_cookie("test-cookie")
            return {"state": cookie_state, "message": "工作 Cookie 补齐结果"}

        persist = AsyncMock(side_effect=persist_result)

        @asynccontextmanager
        async def fake_account_operation(db, account_id):
            # 此套件只验证扫码协议，真实 MySQL 互斥由数据库回归用例覆盖
            if account_busy:
                raise HTTPException(status_code=409, detail="账号正在签到或维护中，请稍后重试")
            yield

        with (
            patch.object(main, "account_operation", fake_account_operation),
            patch.object(main, "async_session", side_effect=contexts),
            patch.object(main.asyncio, "sleep", new=AsyncMock()),
            patch.object(main.AccountCredentialService, "persist_login_result", persist),
            patch.object(main.AccountCredentialService, "ensure_work_cookie", new=AsyncMock(side_effect=ensure_cookie)),
            patch("app.services.account_role_sync.fetch_game_roles", new=AsyncMock(return_value=[{}], side_effect=role_error)),
            patch("app.services.account_role_sync.sync_account_roles", new=AsyncMock(return_value=[object(), object()])),
        ):
            await main.qr_login_websocket(socket, grant["session_id"])
        return socket, dbs, persist

    async def test_busy_account_rejects_qr_save_with_retry_message(self):
        grant, session = self.issue(target=22)
        account = MihoyoAccount(id=22, user_id=11)
        socket, dbs, persist = await self.connect(
            grant, [[object(), account], [object(), account]], account_busy=True,
        )
        persist.assert_not_awaited()
        dbs[-1].commit.assert_not_awaited()
        message = socket.send_json.call_args.args[0]
        self.assertEqual(message["type"], "error")
        self.assertIn("稍后重试", message["message"])

    async def test_http_entrypoints_require_authentication(self):
        # 不进入 TestClient 上下文，避免运行初始化数据库及调度器的 lifespan
        client = TestClient(main.app)
        try:
            for path in ("/api/accounts/qr-login", "/api/accounts/22/refresh-cookie"):
                self.assertIn(client.post(path).status_code, (401, 403))
        finally:
            client.close()

    async def test_http_refresh_checks_owner_before_issuing(self):
        db = fake_db([None])
        with patch.object(accounts, "passport_login_manager", self.manager):
            with self.assertRaises(HTTPException) as error:
                await accounts.refresh_cookie(22, SimpleNamespace(id=11), db)
        self.assertEqual(error.exception.status_code, 404)
        self.assertFalse(self.manager._sessions)
        params = db.execute.call_args.args[0].compile().params
        self.assertEqual(params, {"id_1": 22, "user_id_1": 11})

    async def test_http_binding_and_refresh_issue_server_owned_grants(self):
        with patch.object(accounts, "passport_login_manager", self.manager):
            new = await accounts.start_qr_login(SimpleNamespace(id=11))
            refresh = await accounts.refresh_cookie(22, SimpleNamespace(id=11), fake_db([object()]))
        self.assertIsNone(self.manager.claim_session(new.session_id, new.credential).account_id)
        session = self.manager.claim_session(refresh.session_id, refresh.credential)
        self.assertEqual((session.user_id, session.account_id), (11, 22))

    async def test_missing_and_forged_first_frames_do_not_start_login(self):
        for frame in ({}, {"type": "authenticate", "credential": "forged"}):
            grant, session = self.issue()
            socket, _, persist = await self.connect(grant, [], frame=frame)
            session.start.assert_not_awaited()
            persist.assert_not_awaited()
            self.assertEqual(socket.send_json.call_args.args[0]["type"], "error")

    async def test_handshake_timeout_and_disconnect_do_not_consume_grant(self):
        for error in (asyncio.TimeoutError(), WebSocketDisconnect()):
            grant, session = self.issue()
            await self.connect(grant, [], receive_error=error)
            session.start.assert_not_awaited()
            self.assertIs(self.manager.claim_session(grant["session_id"], grant["credential"]), session)

    async def test_duplicate_connection_does_not_remove_live_session(self):
        grant, session = self.issue()
        self.manager.claim_session(grant["session_id"], grant["credential"])
        await self.connect(grant, [])
        self.assertIs(self.manager.get_session(grant["session_id"]), session)
        session.start.assert_not_awaited()

    async def test_disabled_user_at_claim_does_not_start_login(self):
        grant, session = self.issue()
        _, _, persist = await self.connect(grant, [[None]])
        session.start.assert_not_awaited()
        persist.assert_not_awaited()
        self.assertIsNone(self.manager.get_session(grant["session_id"]))

    async def test_user_disabled_while_scanning_prevents_save(self):
        grant, _ = self.issue()
        socket, dbs, persist = await self.connect(grant, [[object()], [None]])
        persist.assert_not_awaited()
        dbs[-1].commit.assert_not_awaited()
        self.assertIn("用户已停用", socket.send_json.call_args.args[0]["message"])

    async def test_target_deleted_or_transferred_while_scanning_prevents_save(self):
        grant, _ = self.issue(22)
        socket, dbs, persist = await self.connect(grant, [[object(), object()], [object(), None]])
        persist.assert_not_awaited()
        dbs[-1].commit.assert_not_awaited()
        query = dbs[-1].execute.call_args.args[0]
        self.assertEqual(query.compile().params, {"id_1": 22, "user_id_1": 11})
        self.assertIn("FOR UPDATE", str(query))
        self.assertIn("待刷新的账号", socket.send_json.call_args.args[0]["message"])

    async def test_legitimate_binding_ignores_client_owner_and_target(self):
        grant, _ = self.issue()
        socket, dbs, persist = await self.connect(grant, [[object()], [object()]])
        saved = persist.call_args.args[0]
        self.assertEqual(saved.user_id, 11)
        dbs[-1].add.assert_called_once_with(saved)
        dbs[-1].commit.assert_awaited_once()
        self.assertEqual(socket.send_json.call_args.args[0]["type"], "success")
        self.assertEqual(socket.send_json.call_args.args[0]["roles_count"], 2)
        self.assertEqual(socket.send_json.call_args.args[0]["roles_sync_status"], "success")

    async def test_legitimate_refresh_saves_only_server_target(self):
        grant, _ = self.issue(22)
        account = MihoyoAccount(id=22, user_id=11, mihoyo_uid="11", stuid="11")
        socket, dbs, persist = await self.connect(grant, [[object(), account], [object(), account]])
        self.assertIs(persist.call_args.args[0], account)
        dbs[-1].add.assert_not_called()
        dbs[-1].commit.assert_awaited_once()
        self.assertEqual(socket.send_json.call_args.args[0]["account_id"], 22)

    async def test_different_uid_refresh_rejects_before_credentials_change(self):
        grant, _ = self.issue(22)
        account = MihoyoAccount(id=22, user_id=11, mihoyo_uid="99", stuid="99", stoken_encrypted="old-secret")
        socket, dbs, _ = await self.connect(grant, [[object(), account], [object(), account]])
        self.assertEqual(account.mihoyo_uid, "99")
        self.assertEqual(account.stoken_encrypted, "old-secret")
        dbs[-1].commit.assert_not_awaited()
        message = socket.send_json.call_args.args[0]
        self.assertEqual(message["type"], "error")
        self.assertIn("添加账号", message["message"])

    async def test_role_request_failure_keeps_binding_and_reports_pending(self):
        grant, _ = self.issue()
        socket, dbs, persist = await self.connect(grant, [[object()], [object()]], role_error=RoleFetchError("失败"))
        dbs[-1].commit.assert_awaited_once()
        self.assertEqual(persist.call_args.args[0].credential_status, "valid")
        self.assertEqual(persist.call_args.args[0].cookie_status, "valid")
        result = socket.send_json.call_args.args[0]
        self.assertEqual(result["type"], "success")
        self.assertEqual(result["roles_sync_status"], "pending")
        self.assertIsNone(result["roles_count"])
        self.assertIn("账号已绑定", result["message"])
        self.assertIn("校验登录态", result["message"])

    async def test_cookie_completion_failure_reports_pending_without_losing_root_credentials(self):
        grant, _ = self.issue()
        socket, dbs, persist = await self.connect(grant, [[object()], [object()]], cookie_state="network_error")
        dbs[-1].commit.assert_awaited_once()
        self.assertEqual(persist.call_args.args[0].credential_status, "valid")
        self.assertEqual(persist.call_args.args[0].cookie_status, "unknown")
        result = socket.send_json.call_args.args[0]
        self.assertEqual(result["roles_sync_status"], "pending")
        self.assertIsNone(result["roles_count"])


if __name__ == "__main__":
    unittest.main()
