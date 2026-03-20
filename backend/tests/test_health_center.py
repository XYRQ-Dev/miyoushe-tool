import os
import unittest
from datetime import timedelta

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.account import GameRole, MihoyoAccount
from app.models.task_log import TaskLog
from app.models.user import User
from app.utils.crypto import encrypt_cookie
from app.utils.timezone import utc_now_naive


class HealthCenterTests(unittest.IsolatedAsyncioTestCase):
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

    async def _create_user(self, session: AsyncSession, username: str) -> User:
        user = User(username=username, password_hash="x", role="user", is_active=True)
        session.add(user)
        await session.flush()
        await session.refresh(user)
        return user

    async def _create_account(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        nickname: str,
        mihoyo_uid: str,
        cookie_status: str = "valid",
        with_cookie: bool = True,
        last_refresh_status: str | None = None,
        last_refresh_message: str | None = None,
        last_refresh_attempt_days_ago: int | None = None,
    ) -> MihoyoAccount:
        now = utc_now_naive()
        account = MihoyoAccount(
            user_id=user_id,
            nickname=nickname,
            mihoyo_uid=mihoyo_uid,
            cookie_status=cookie_status,
            cookie_encrypted=encrypt_cookie("ltuid=10001; cookie_token=test-token") if with_cookie else None,
            last_refresh_status=last_refresh_status,
            last_refresh_message=last_refresh_message,
            last_refresh_attempt_at=(
                now - timedelta(days=last_refresh_attempt_days_ago)
                if last_refresh_attempt_days_ago is not None
                else None
            ),
            last_cookie_check=now,
        )
        session.add(account)
        await session.flush()
        await session.refresh(account)
        return account

    async def test_get_health_center_overview_returns_empty_state_for_user_without_accounts(self):
        from app.api.health_center import get_health_center_overview

        async with await self._new_session() as session:
            user = await self._create_user(session, "health-empty-user")
            await session.commit()
            await session.refresh(user)

            response = await get_health_center_overview(current_user=user, db=session)

        self.assertEqual(response.summary.total_accounts, 0)
        self.assertEqual(response.summary.healthy_accounts, 0)
        self.assertEqual(response.summary.reauth_required_accounts, 0)
        self.assertEqual(response.summary.warning_accounts, 0)
        self.assertEqual(response.summary.failed_accounts_7d, 0)
        self.assertEqual(response.accounts, [])
        self.assertEqual(response.recent_events, [])

    async def test_get_health_center_overview_aggregates_levels_assets_and_recent_events(self):
        from app.api.health_center import get_health_center_overview

        now = utc_now_naive()
        async with await self._new_session() as session:
            user = await self._create_user(session, "health-owner")
            stranger = await self._create_user(session, "health-stranger")

            healthy_account = await self._create_account(
                session,
                user_id=user.id,
                nickname="稳定账号",
                mihoyo_uid="10001",
                last_refresh_status="success",
                last_refresh_message="登录态校验通过",
                last_refresh_attempt_days_ago=1,
            )
            warning_account = await self._create_account(
                session,
                user_id=user.id,
                nickname="预警账号",
                mihoyo_uid="10002",
                last_refresh_status="network_error",
                last_refresh_message="网络波动，暂未确认失效",
                last_refresh_attempt_days_ago=2,
            )
            danger_account = await self._create_account(
                session,
                user_id=user.id,
                nickname="危险账号",
                mihoyo_uid="10003",
                cookie_status="reauth_required",
                last_refresh_status="reauth_required",
                last_refresh_message="Cookie 已过期，请重新扫码更新网页登录态",
                last_refresh_attempt_days_ago=0,
            )
            foreign_account = await self._create_account(
                session,
                user_id=stranger.id,
                nickname="外部账号",
                mihoyo_uid="20001",
                last_refresh_status="warning",
                last_refresh_attempt_days_ago=0,
            )
            unknown_account = await self._create_account(
                session,
                user_id=user.id,
                nickname="待判定账号",
                mihoyo_uid="10004",
            )

            session.add_all([
                GameRole(account_id=healthy_account.id, game_biz="hk4e_cn", game_uid="30001", nickname="原神角色", region="cn_gf01", is_enabled=True),
                GameRole(account_id=warning_account.id, game_biz="nap_cn", game_uid="30002", nickname="绝区零角色", region="prod_gf_cn", is_enabled=True),
                GameRole(account_id=danger_account.id, game_biz="hkrpg_cn", game_uid="30003", nickname="星铁角色", region="prod_gf_cn", is_enabled=True),
                GameRole(account_id=foreign_account.id, game_biz="hk4e_cn", game_uid="40001", nickname="外部角色", region="cn_gf01", is_enabled=True),
                GameRole(account_id=unknown_account.id, game_biz="hk4e_cn", game_uid="30004", nickname="待判定角色", region="cn_gf01", is_enabled=True),
            ])
            session.add_all([
                TaskLog(
                    account_id=healthy_account.id,
                    task_type="checkin",
                    status="success",
                    message="签到成功",
                    executed_at=now - timedelta(days=1),
                ),
                TaskLog(
                    account_id=warning_account.id,
                    task_type="checkin",
                    status="failed",
                    message="上游风控",
                    executed_at=now - timedelta(hours=10),
                ),
                TaskLog(
                    account_id=foreign_account.id,
                    task_type="checkin",
                    status="failed",
                    message="不应串入其他用户",
                    executed_at=now - timedelta(hours=1),
                ),
            ])
            await session.commit()
            await session.refresh(user)

            response = await get_health_center_overview(current_user=user, db=session)

        self.assertEqual(response.summary.total_accounts, 4)
        self.assertEqual(response.summary.healthy_accounts, 1)
        self.assertEqual(response.summary.reauth_required_accounts, 1)
        self.assertEqual(response.summary.warning_accounts, 1)
        self.assertEqual(response.summary.failed_accounts_7d, 1)

        account_map = {item.account_id: item for item in response.accounts}
        self.assertEqual(account_map[healthy_account.id].health_level, "healthy")
        self.assertEqual(account_map[warning_account.id].health_level, "warning")
        self.assertEqual(account_map[danger_account.id].health_level, "danger")
        self.assertEqual(account_map[unknown_account.id].health_level, "unknown")

        self.assertEqual(account_map[healthy_account.id].supported_assets, ["checkin", "gacha", "redeem"])
        self.assertEqual(account_map[warning_account.id].supported_assets, ["checkin"])
        self.assertEqual(account_map[danger_account.id].supported_assets, ["checkin", "gacha", "redeem"])
        self.assertEqual(account_map[unknown_account.id].supported_assets, ["checkin", "gacha", "redeem"])

        self.assertEqual(account_map[warning_account.id].recent_checkin.failed_count_7d, 1)
        self.assertEqual(account_map[healthy_account.id].recent_checkin.success_count_7d, 1)
        self.assertIn("重新扫码", account_map[danger_account.id].health_reason)
        self.assertIn("登录态校验记录", account_map[unknown_account.id].health_reason)

        self.assertGreaterEqual(len(response.recent_events), 2)
        self.assertEqual(response.recent_events[0].account_id, danger_account.id)
        self.assertEqual(response.recent_events[0].event_type, "login_state")
        self.assertNotIn(foreign_account.id, {item.account_id for item in response.recent_events})
