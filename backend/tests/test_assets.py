import os
import unittest

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.account import GameRole, MihoyoAccount
from app.models.gacha import GachaRecord
from app.models.task_log import TaskLog
from app.models.user import User
from app.utils.crypto import encrypt_cookie


class RoleAssetOverviewTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_get_role_asset_overview_returns_empty_state_for_user_without_accounts(self):
        from app.api.assets import get_role_asset_overview

        async with await self._new_session() as session:
            user = User(username="assets-empty", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.commit()
            await session.refresh(user)

            response = await get_role_asset_overview(current_user=user, db=session)

        self.assertEqual(response.summary.total_accounts, 0)
        self.assertEqual(response.summary.total_roles, 0)
        self.assertEqual(response.summary.note_supported_roles, 0)
        self.assertEqual(response.summary.gacha_archived_games, 0)
        self.assertEqual(response.accounts, [])

    async def test_get_role_asset_overview_aggregates_roles_assets_and_recent_status(self):
        from app.api.assets import get_role_asset_overview

        async with await self._new_session() as session:
            user = User(username="assets-owner", password_hash="x", role="user", is_active=True)
            stranger = User(username="assets-stranger", password_hash="x", role="user", is_active=True)
            session.add_all([user, stranger])
            await session.flush()

            stable_account = MihoyoAccount(
                user_id=user.id,
                nickname="主账号",
                mihoyo_uid="10001",
                cookie_status="valid",
                cookie_encrypted=encrypt_cookie("ltuid=10001; cookie_token=test-token"),
            )
            reauth_account = MihoyoAccount(
                user_id=user.id,
                nickname="待重登账号",
                mihoyo_uid="10002",
                cookie_status="reauth_required",
                cookie_encrypted=None,
            )
            foreign_account = MihoyoAccount(
                user_id=stranger.id,
                nickname="外部账号",
                mihoyo_uid="20001",
                cookie_status="valid",
                cookie_encrypted=encrypt_cookie("ltuid=20001; cookie_token=foreign-token"),
            )
            session.add_all([stable_account, reauth_account, foreign_account])
            await session.flush()

            stable_genshin = GameRole(
                account_id=stable_account.id,
                game_biz="hk4e_cn",
                game_uid="30001",
                nickname="旅行者",
                region="cn_gf01",
                level=60,
                is_enabled=True,
            )
            stable_starrail = GameRole(
                account_id=stable_account.id,
                game_biz="hkrpg_cn",
                game_uid="30002",
                nickname="开拓者",
                region="prod_gf_cn",
                level=70,
                is_enabled=True,
            )
            reauth_starrail = GameRole(
                account_id=reauth_account.id,
                game_biz="hkrpg_cn",
                game_uid="30003",
                nickname="姬子",
                region="prod_gf_cn",
                level=80,
                is_enabled=True,
            )
            unsupported_role = GameRole(
                account_id=reauth_account.id,
                game_biz="nap_cn",
                game_uid="30004",
                nickname="绳匠",
                region="prod_gf_cn",
                level=50,
                is_enabled=True,
            )
            foreign_role = GameRole(
                account_id=foreign_account.id,
                game_biz="hk4e_cn",
                game_uid="40001",
                nickname="外部角色",
                region="cn_gf01",
                level=90,
                is_enabled=True,
            )
            session.add_all([stable_genshin, stable_starrail, reauth_starrail, unsupported_role, foreign_role])
            await session.flush()

            session.add_all([
                TaskLog(
                    account_id=stable_account.id,
                    game_role_id=stable_genshin.id,
                    task_type="checkin",
                    status="success",
                    message="签到成功",
                ),
                TaskLog(
                    account_id=reauth_account.id,
                    game_role_id=reauth_starrail.id,
                    task_type="checkin",
                    status="failed",
                    message="登录失效",
                ),
                TaskLog(
                    account_id=foreign_account.id,
                    game_role_id=foreign_role.id,
                    task_type="checkin",
                    status="success",
                    message="不应串入外部用户",
                ),
                GachaRecord(
                    account_id=stable_account.id,
                    game="genshin",
                    record_id="5000001",
                    pool_type="301",
                    pool_name="角色活动祈愿",
                    item_name="刻晴",
                    item_type="角色",
                    rank_type="5",
                    time_text="2026-03-18 12:00:00",
                ),
                GachaRecord(
                    account_id=foreign_account.id,
                    game="genshin",
                    record_id="9000001",
                    pool_type="301",
                    pool_name="角色活动祈愿",
                    item_name="不应串入",
                    item_type="角色",
                    rank_type="5",
                    time_text="2026-03-18 12:01:00",
                ),
            ])
            await session.commit()
            await session.refresh(user)

            response = await get_role_asset_overview(current_user=user, db=session)

        self.assertEqual(response.summary.total_accounts, 2)
        self.assertEqual(response.summary.total_roles, 4)
        self.assertEqual(response.summary.note_supported_roles, 3)
        self.assertEqual(response.summary.gacha_archived_games, 1)

        account_map = {account.account_id: account for account in response.accounts}
        self.assertNotIn(foreign_account.id, account_map)

        stable_role_map = {role.role_id: role for role in account_map[stable_account.id].roles}
        self.assertEqual(stable_role_map[stable_genshin.id].game, "genshin")
        self.assertEqual(stable_role_map[stable_genshin.id].game_name, "原神")
        self.assertEqual(stable_role_map[stable_genshin.id].supported_assets, ["checkin", "notes", "gacha", "redeem"])
        self.assertEqual(stable_role_map[stable_genshin.id].notes_status, "available")
        self.assertTrue(stable_role_map[stable_genshin.id].has_gacha_archive)
        self.assertEqual(stable_role_map[stable_genshin.id].recent_checkin.last_status, "success")

        self.assertEqual(stable_role_map[stable_starrail.id].game, "starrail")
        self.assertFalse(stable_role_map[stable_starrail.id].has_gacha_archive)
        self.assertIsNone(stable_role_map[stable_starrail.id].recent_checkin.last_status)

        reauth_role_map = {role.role_id: role for role in account_map[reauth_account.id].roles}
        self.assertEqual(reauth_role_map[reauth_starrail.id].notes_status, "login_required")
        self.assertEqual(reauth_role_map[reauth_starrail.id].recent_checkin.last_status, "failed")
        self.assertEqual(reauth_role_map[unsupported_role.id].game, "nap_cn")
        self.assertEqual(reauth_role_map[unsupported_role.id].game_name, "绝区零")
        self.assertEqual(reauth_role_map[unsupported_role.id].supported_assets, ["checkin"])
        self.assertEqual(reauth_role_map[unsupported_role.id].notes_status, "unsupported")

    async def test_get_role_asset_overview_keeps_recent_checkin_after_role_sync_preserves_identity(self):
        from app.api.assets import get_role_asset_overview
        from app.services.account_role_sync import sync_account_roles

        async with await self._new_session() as session:
            user = User(username="assets-refresh-owner", password_hash="x", role="user", is_active=True)
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
            await session.refresh(user)
            await session.refresh(account)
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

            response = await get_role_asset_overview(current_user=user, db=session)

        self.assertEqual(len(synced_roles), 1)
        self.assertEqual(synced_roles[0].id, role.id)
        self.assertEqual(synced_roles[0].nickname, "新旅行者")
        self.assertFalse(synced_roles[0].is_enabled)

        refreshed_role = response.accounts[0].roles[0]
        self.assertEqual(refreshed_role.role_id, role.id)
        self.assertEqual(refreshed_role.recent_checkin.last_status, "success")
        self.assertEqual(refreshed_role.recent_checkin.last_message, "刷新前已签到")
