import os
import unittest
from unittest.mock import AsyncMock, patch

if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
else:
    os.environ.setdefault(
        "DATABASE_URL",
        "mysql+asyncmy://root:root@127.0.0.1:3306/miyoushe_test?charset=utf8mb4",
    )

from app.models.account import GameRole, MihoyoAccount
from app.models.gacha import GachaRecord
from app.models.task_log import TaskLog
from app.models.user import User
from app.utils.crypto import encrypt_cookie, encrypt_text
from tests.mysql_test_case import MySqlIsolatedAsyncioTestCase


class RoleAssetOverviewTests(MySqlIsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        async with self.engine.begin() as conn:
            await conn.run_sync(self._drop_and_create_all)

    @staticmethod
    def _drop_and_create_all(sync_conn) -> None:
        from app.database import Base

        Base.metadata.drop_all(sync_conn)
        Base.metadata.create_all(sync_conn)

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
        self.assertEqual(response.summary.gacha_archived_games, 0)
        self.assertEqual(response.accounts, [])

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
                # Task 5 的目标不是“只有空值时兜底”，而是无论旧值看起来多正常，
                # 只要账号仍停留在 Cookie-only 形态，列表都必须强制收口为“需要升级登录”。
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
        from app.services.login_state import LoginStateService

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
                stoken_encrypted=encrypt_text("v2_test_stoken"),
                ltoken_encrypted=encrypt_text("v2_test_ltoken"),
                cookie_token_encrypted=encrypt_text("test_cookie_token"),
                login_ticket_encrypted=encrypt_text("test_login_ticket"),
                stuid="10001",
                mid="mid-10001",
                credential_source="passport_qr",
                credential_status="valid",
                last_token_refresh_status="valid",
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
            stable_genshin_alt = GameRole(
                account_id=stable_account.id,
                game_biz="hk4e_cn",
                game_uid="30005",
                nickname="旅行者小号",
                region="cn_gf01",
                level=58,
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
            session.add_all(
                [stable_genshin, stable_starrail, stable_genshin_alt, reauth_starrail, unsupported_role, foreign_role]
            )
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
                    game_uid="30001",
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
                    game_uid="40001",
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
        self.assertEqual(response.summary.total_roles, 5)
        self.assertEqual(response.summary.gacha_archived_games, 1)

        # 这里显式给账号灌入新的高权限根凭据字段，目的是锁定一个兼容约束：
        # 角色资产总览仍然只读取它真正关心的账号/角色/日志/抽卡聚合信息，
        # 不能因为账号模型新增了根凭据状态字段，就意外改变总览统计或卡片聚合行为。
        # 如果后续有人把这些新字段直接耦合进资产聚合主逻辑，最容易出现的回归就是
        # “登录能力升级了，但资产页统计、角色卡片或入口显隐反而被改坏”。
        self.assertEqual(stable_account.credential_status, "valid")
        self.assertEqual(stable_account.credential_source, "passport_qr")

        account_map = {account.account_id: account for account in response.accounts}
        self.assertNotIn(foreign_account.id, account_map)

        stable_role_map = {role.role_id: role for role in account_map[stable_account.id].roles}
        self.assertEqual(stable_role_map[stable_genshin.id].game, "genshin")
        self.assertEqual(stable_role_map[stable_genshin.id].game_name, "原神")
        self.assertEqual(stable_role_map[stable_genshin.id].supported_assets, ["checkin", "gacha", "redeem"])
        self.assertTrue(stable_role_map[stable_genshin.id].has_gacha_archive)
        self.assertEqual(stable_role_map[stable_genshin.id].recent_checkin.last_status, "success")
        # 同账号同游戏的另一个 UID 没有任何归档记录时，角色卡必须保持未归档。
        # 否则前端会把账号级导入误展示成“该游戏全部角色都已归档”，用户选错 UID 后还以为数据已经完整。
        self.assertFalse(stable_role_map[stable_genshin_alt.id].has_gacha_archive)

        self.assertEqual(stable_role_map[stable_starrail.id].game, "starrail")
        self.assertFalse(stable_role_map[stable_starrail.id].has_gacha_archive)
        self.assertIsNone(stable_role_map[stable_starrail.id].recent_checkin.last_status)

        reauth_role_map = {role.role_id: role for role in account_map[reauth_account.id].roles}
        self.assertEqual(reauth_role_map[reauth_starrail.id].supported_assets, ["checkin", "gacha", "redeem"])
        self.assertEqual(reauth_role_map[reauth_starrail.id].recent_checkin.last_status, "failed")
        self.assertEqual(reauth_role_map[unsupported_role.id].game, "nap_cn")
        self.assertEqual(reauth_role_map[unsupported_role.id].game_name, "绝区零")
        # 绝区零当前仅保留签到能力；这里必须锁定响应协议，避免前端误展示不存在的兑换入口。
        self.assertEqual(reauth_role_map[unsupported_role.id].supported_assets, ["checkin"])

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




