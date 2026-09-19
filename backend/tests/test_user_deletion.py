"""永久删除回归；数据库用例仅允许显式授权的独立 MySQL 测试库"""

import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "mysql+asyncmy://demo:demo@127.0.0.1:3306/miyoushe?charset=utf8mb4"

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, select

from app.api.admin import delete_user
from app.api.auth import create_token_pair, get_current_user, refresh_token, require_admin
from app.models.account import GameRole, MihoyoAccount
from app.models.admin_operation_log import AdminOperationLog
from app.models.task_log import TaskConfig, TaskLog
from app.models.user import User
from app.schemas.admin_notification import AdminBroadcastEmailRequest
from app.services.account_operations import account_operation
from app.services.admin_broadcast import AdminBroadcastService
from app.services.notifier import NotificationService
from app.services.passport_login import PassportQrLoginManager
from app.services.scheduler import SchedulerService
from app.services.user_deletion import UserDeletionService
from app.services.user_operations import user_deletion, user_operation
from app.utils.timezone import utc_now
from tests.mysql_test_case import MySqlIsolatedAsyncioTestCase


class UserDeletionTests(MySqlIsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.scheduler = SchedulerService()
        self.manager = PassportQrLoginManager()
        self.notifier = NotificationService()
        for name, value in (
            ("scheduler_service", self.scheduler),
            ("passport_login_manager", self.manager),
            ("notification_service", self.notifier),
        ):
            patcher = patch(f"app.services.user_deletion.{name}", value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def asyncTearDown(self):
        for session in list(self.manager._sessions.values()):
            await self.manager.remove_session(session)
        self.scheduler.stop()
        await super().asyncTearDown()

    async def fixture(self):
        async with await self._new_session() as db:
            admin = User(username="keeper", password_hash="test", role="admin", is_active=True)
            victim = User(username="removed", password_hash="test", role="admin", is_active=True, email="removed@example.com")
            db.add_all([admin, victim])
            await db.flush()
            accounts = [MihoyoAccount(user_id=victim.id, cookie_encrypted="test-cipher", stoken_encrypted="test-root") for _ in range(2)]
            survivor = MihoyoAccount(user_id=admin.id)
            db.add_all([*accounts, survivor])
            await db.flush()
            role = GameRole(account_id=accounts[0].id, game_biz="hk4e_cn", game_uid="test-uid")
            db.add(role)
            await db.flush()
            db.add_all([
                TaskLog(account_id=accounts[0].id, game_role_id=role.id, status="success"),
                TaskLog(account_id=accounts[1].id, status="failed"),
                TaskLog(account_id=survivor.id, status="success"),
                TaskConfig(user_id=victim.id), TaskConfig(user_id=admin.id),
                AdminOperationLog(operator_user_id=victim.id, subject="removed audit"),
                AdminOperationLog(
                    operator_user_id=admin.id, subject="shared audit", recipient_count=2, failed_count=2,
                    failure_details_json=json.dumps([
                        {"user_id": victim.id, "username": victim.username, "email": victim.email, "error": "test"},
                        {"user_id": admin.id, "username": admin.username, "email": "keeper@example.com", "error": "test"},
                    ]),
                ),
            ])
            await db.commit()
            self.admin_id, self.victim_id = admin.id, victim.id
            self.account_id = accounts[0].id
            self.tokens = create_token_pair(victim)

    async def call_delete(self):
        async with await self._new_session() as db:
            admin = await db.get(User, self.admin_id)
            return await delete_user(self.victim_id, admin=admin, db=db)

    async def test_delete_other_admin_removes_all_records_and_revokes_tokens(self):
        await self.fixture()
        grant = self.manager.issue_session(self.victim_id)
        self.notifier._recent_notifications[(self.victim_id, "test")] = utc_now()
        self.notifier._recent_notifications[(self.admin_id, "keep")] = utc_now()
        self.scheduler._schedule_errors[self.victim_id] = "test error"
        self.assertTrue((await self.call_delete())["deleted"])
        self.assertIsNone(self.manager.get_session(grant["session_id"]))
        self.assertNotIn((self.victim_id, "test"), self.notifier._recent_notifications)
        self.assertIn((self.admin_id, "keep"), self.notifier._recent_notifications)
        self.assertNotIn(self.victim_id, self.scheduler._schedule_errors)
        async with await self._new_session() as db:
            for model, expected in ((User, 1), (MihoyoAccount, 1), (GameRole, 0), (TaskLog, 1), (TaskConfig, 1), (AdminOperationLog, 1)):
                self.assertEqual(await db.scalar(select(func.count(model.id))), expected)
            audit = (await db.scalars(select(AdminOperationLog))).one()
            self.assertEqual([item["user_id"] for item in json.loads(audit.failure_details_json)], [self.admin_id])
            self.assertEqual(audit.failed_count, 2)
            for endpoint, token in ((get_current_user, self.tokens.access_token), (refresh_token, self.tokens.refresh_token)):
                with self.assertRaises(HTTPException) as caught:
                    await endpoint(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), db)
                self.assertEqual(caught.exception.status_code, 401)
        self.assertFalse((await self.call_delete())["deleted"])

    async def test_statement_failure_rolls_back_children_and_keeps_runtime(self):
        await self.fixture()
        grant = self.manager.issue_session(self.victim_id)
        async with await self._new_session() as db:
            original = db.execute

            async def fail_roles(statement, *args, **kwargs):
                if getattr(statement, "is_delete", False) and statement.table.name == "game_roles":
                    raise RuntimeError("injected failure")
                return await original(statement, *args, **kwargs)

            with patch.object(db, "execute", side_effect=fail_roles):
                with self.assertRaisesRegex(RuntimeError, "injected failure"):
                    await UserDeletionService(db).delete(self.victim_id)
        async with await self._new_session() as db:
            self.assertIsNotNone(await db.get(User, self.victim_id))
            self.assertEqual(await db.scalar(select(func.count(TaskLog.id))), 3)
            self.assertEqual(await db.scalar(select(func.count(GameRole.id))), 1)
        self.assertIsNotNone(self.manager.get_session(grant["session_id"]))
        self.assertTrue((await self.call_delete())["deleted"])

    async def test_commit_failure_restores_audit_details(self):
        await self.fixture()
        async with await self._new_session() as db:
            with patch.object(db, "commit", side_effect=RuntimeError("commit failed")):
                with self.assertRaisesRegex(RuntimeError, "commit failed"):
                    await UserDeletionService(db).delete(self.victim_id)
        async with await self._new_session() as db:
            audit = (await db.scalars(select(AdminOperationLog).where(AdminOperationLog.subject == "shared audit"))).one()
            self.assertEqual(len(json.loads(audit.failure_details_json)), 2)
            self.assertIsNotNone(await db.get(User, self.victim_id))
            self.assertEqual(await db.scalar(select(func.count(MihoyoAccount.id))), 3)

    async def test_account_operation_blocks_deletion_across_commit(self):
        await self.fixture()
        async with await self._new_session() as db:
            async with account_operation(db, self.account_id):
                await db.commit()
                with self.assertRaises(HTTPException) as caught:
                    await self.call_delete()
                self.assertEqual(caught.exception.status_code, 409)
        self.assertTrue((await self.call_delete())["deleted"])

    async def test_cleanup_failure_can_be_retried_after_database_commit(self):
        await self.fixture()
        grant = self.manager.issue_session(self.victim_id)
        with patch.object(self.scheduler, "remove_user_runtime", side_effect=RuntimeError("cleanup failed")):
            with self.assertRaises(HTTPException) as caught:
                await self.call_delete()
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIsNone(self.manager.get_session(grant["session_id"]))
        async with await self._new_session() as db:
            self.assertIsNone(await db.get(User, self.victim_id))
        self.assertFalse((await self.call_delete())["deleted"])

    async def test_broadcast_protects_recipient_until_audit_is_committed(self):
        await self.fixture()
        entered, release = asyncio.Event(), asyncio.Event()

        async def send_one(**kwargs):
            entered.set()
            await release.wait()
            raise RuntimeError("test delivery failure")

        async def broadcast():
            async with await self._new_session() as db:
                service = AdminBroadcastService(db)
                with patch.object(service, "_send_one", side_effect=send_one), patch.object(
                    service.notification_service, "_load_smtp_config", return_value={"host": "test"},
                ):
                    await service.broadcast_email(
                        admin=await db.get(User, self.admin_id),
                        payload=AdminBroadcastEmailRequest(subject="test", body="test"),
                    )

        task = asyncio.create_task(broadcast())
        try:
            await asyncio.wait_for(entered.wait(), 5)
            with self.assertRaises(HTTPException) as caught:
                await self.call_delete()
            self.assertEqual(caught.exception.status_code, 409)
        finally:
            release.set()
            await asyncio.wait_for(task, 5)
        await self.call_delete()
        async with await self._new_session() as db:
            for audit in (await db.scalars(select(AdminOperationLog))).all():
                self.assertNotIn("removed@example.com", audit.failure_details_json or "")


class UserDeletionRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_permissions_and_self_deletion(self):
        with self.assertRaises(HTTPException) as caught:
            await require_admin(User(id=1, role="user"))
        self.assertEqual(caught.exception.status_code, 403)
        with self.assertRaises(HTTPException) as caught:
            await delete_user(1, admin=User(id=1, role="admin"), db=AsyncMock())
        self.assertEqual(caught.exception.status_code, 400)

    async def test_normal_operations_can_overlap_and_guards_release_on_error(self):
        with user_operation(100), user_operation(100):
            with self.assertRaises(HTTPException):
                with user_deletion(100):
                    pass
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with user_deletion(100):
                with self.assertRaises(HTTPException):
                    with user_operation(100):
                        pass
                raise RuntimeError("rollback")
        with user_operation(100):
            pass

    async def test_qr_cleanup_cancels_owner_and_clears_credentials_only_for_target(self):
        manager = PassportQrLoginManager()
        grant = manager.issue_session(100)
        other = manager.issue_session(101)
        session = manager.get_session(grant["session_id"])
        session.login_result = {"stoken": "test-secret"}
        started = asyncio.Event()

        async def connection():
            session.task = asyncio.current_task()
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await manager.remove_session(session)

        task = asyncio.create_task(connection())
        try:
            await asyncio.wait_for(started.wait(), 5)
            await manager.remove_user_sessions(100)
            self.assertTrue(task.cancelled())
            self.assertIsNone(session.login_result)
            self.assertIsNone(manager.get_session(grant["session_id"]))
            self.assertNotIn(grant["session_id"], manager._grants)
            self.assertIsNotNone(manager.get_session(other["session_id"]))
        finally:
            await manager.remove_user_sessions(100)
            await manager.remove_user_sessions(101)

    async def test_delayed_checkin_and_schedule_are_removed(self):
        scheduler = SchedulerService()
        started = asyncio.Event()

        async def delayed(user_id):
            started.set()
            await asyncio.Event().wait()

        scheduler.scheduler.add_job(scheduler._execute_checkin, "interval", hours=1, args=[100], id="checkin_user_100")
        with patch.object(scheduler, "_run_checkin", side_effect=delayed):
            task = asyncio.create_task(scheduler._execute_checkin(100))
            try:
                await asyncio.wait_for(started.wait(), 5)
                await scheduler.remove_user_runtime(100)
                self.assertTrue(task.cancelled())
                self.assertNotIn(100, scheduler._checkin_tasks)
                self.assertIsNone(scheduler.scheduler.get_job("checkin_user_100"))
            finally:
                await scheduler.remove_user_runtime(100)
