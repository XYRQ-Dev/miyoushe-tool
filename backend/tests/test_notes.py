import os
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import genshin
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.account import GameRole, MihoyoAccount
from app.models.user import User
from app.services.system_settings import SystemSettingsService
from app.utils.crypto import encrypt_cookie


def build_fake_genshin_notes(
    *,
    current_resin: int = 120,
    max_resin: int = 160,
    resin_seconds: int = 3600,
    current_realm_currency: int = 1800,
    max_realm_currency: int = 2400,
    realm_seconds: int = 7200,
    completed_commissions: int = 3,
    max_commissions: int = 4,
    claimed_commission_reward: bool = False,
    remaining_resin_discounts: int = 1,
    max_resin_discounts: int = 3,
    expedition_statuses: tuple[bool, ...] = (True, False),
):
    expeditions = [SimpleNamespace(finished=finished, status="Finished" if finished else "Ongoing") for finished in expedition_statuses]
    return SimpleNamespace(
        current_resin=current_resin,
        max_resin=max_resin,
        remaining_resin_recovery_time=timedelta(seconds=resin_seconds),
        current_realm_currency=current_realm_currency,
        max_realm_currency=max_realm_currency,
        remaining_realm_currency_recovery_time=timedelta(seconds=realm_seconds),
        completed_commissions=completed_commissions,
        max_commissions=max_commissions,
        claimed_commission_reward=claimed_commission_reward,
        remaining_resin_discounts=remaining_resin_discounts,
        max_resin_discounts=max_resin_discounts,
        expeditions=expeditions,
        max_expeditions=5,
    )


def build_fake_starrail_notes(
    *,
    current_stamina: int = 180,
    max_stamina: int = 240,
    stamina_seconds: int = 5400,
    current_reserve_stamina: int = 1200,
    is_reserve_stamina_full: bool = False,
    current_train_score: int = 400,
    max_train_score: int = 500,
    accepted_expedition_num: int = 3,
    total_expedition_num: int = 4,
    expedition_statuses: tuple[bool, ...] = (True, False),
    current_rogue_score: int = 70,
    max_rogue_score: int = 100,
    current_bonus_synchronicity_points: int = 50,
    max_bonus_synchronicity_points: int = 60,
    have_bonus_synchronicity_points: bool = True,
    remaining_weekly_discounts: int = 2,
    max_weekly_discounts: int = 3,
):
    expeditions = [SimpleNamespace(finished=finished, status="Finished" if finished else "Ongoing") for finished in expedition_statuses]
    return SimpleNamespace(
        current_stamina=current_stamina,
        max_stamina=max_stamina,
        stamina_recover_time=timedelta(seconds=stamina_seconds),
        current_reserve_stamina=current_reserve_stamina,
        is_reserve_stamina_full=is_reserve_stamina_full,
        current_train_score=current_train_score,
        max_train_score=max_train_score,
        accepted_expedition_num=accepted_expedition_num,
        total_expedition_num=total_expedition_num,
        expeditions=expeditions,
        current_rogue_score=current_rogue_score,
        max_rogue_score=max_rogue_score,
        current_bonus_synchronicity_points=current_bonus_synchronicity_points,
        max_bonus_synchronicity_points=max_bonus_synchronicity_points,
        have_bonus_synchronicity_points=have_bonus_synchronicity_points,
        remaining_weekly_discounts=remaining_weekly_discounts,
        max_weekly_discounts=max_weekly_discounts,
    )


def build_fake_zzz_notes():
    return SimpleNamespace(
        battery_charge=SimpleNamespace(current=120, max=240, seconds_till_full=1800),
        engagement=SimpleNamespace(current=300, max=500),
        scratch_card_completed=True,
        video_store_state="SaleStateDone",
        hollow_zero=SimpleNamespace(
            bounty_commission=SimpleNamespace(model_dump=lambda: {"num": 2, "total": 5}),
            investigation_point=SimpleNamespace(model_dump=lambda: {"num": 1200, "total": 2000}),
        ),
        card_sign="CardSignDone",
        member_card=SimpleNamespace(is_open=True, member_card_state="MemberCardStateACK", exp_time=timedelta(hours=8)),
        temple_running=SimpleNamespace(
            bench_state="BenchStateCanProduce",
            current_currency=1500,
            currency_next_refresh_ts=timedelta(minutes=30),
            expedition_state="ExpeditionStateEnd",
            level=4,
            shelve_state="ShelveStateCanSell",
            weekly_currency_max=10000,
        ),
        weekly_task=SimpleNamespace(cur_point=600, max_point=900, refresh_time=timedelta(days=2)),
    )


class NoteTests(unittest.IsolatedAsyncioTestCase):
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

    async def _seed_account(self, *, role: str = "user", cookie_status: str = "valid", with_cookie: bool = True):
        async with await self._new_session() as session:
            user = User(username=f"note-{role}-user", password_hash="x", role=role, is_active=True)
            session.add(user)
            await session.flush()

            account = MihoyoAccount(
                user_id=user.id,
                nickname="便笺账号",
                mihoyo_uid="123456789",
                cookie_status=cookie_status,
                cookie_encrypted=encrypt_cookie("ltuid=10001; cookie_token=test-token") if with_cookie else None,
            )
            session.add(account)
            await session.flush()
            await session.commit()
            await session.refresh(user)
            await session.refresh(account)
            return user, account

    async def _disable_notes_menu(self, *, session: AsyncSession, user_visible: bool, admin_visible: bool):
        config = await SystemSettingsService(session).get_or_create()
        config.menu_visibility_json = (
            '{"notes":{"user":'
            + ("true" if user_visible else "false")
            + ',"admin":'
            + ("true" if admin_visible else "false")
            + "}}"
        )
        session.add(config)
        await session.commit()

    async def test_get_note_accounts_only_returns_supported_accounts(self):
        from app.api.notes import get_note_accounts

        async with await self._new_session() as session:
            user = User(username="notes-account-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()

            supported = MihoyoAccount(user_id=user.id, nickname="支持账号", cookie_status="valid")
            unsupported = MihoyoAccount(user_id=user.id, nickname="未适配账号", cookie_status="valid")
            session.add_all([supported, unsupported])
            await session.flush()

            session.add_all([
                GameRole(account_id=supported.id, game_biz="hk4e_cn", game_uid="10001", nickname="旅行者", region="cn_gf01"),
                GameRole(account_id=unsupported.id, game_biz="nap_cn", game_uid="20001", nickname="绳匠", region="prod_gf_cn"),
            ])
            await session.commit()
            await session.refresh(user)

            response = await get_note_accounts(current_user=user, db=session)

        self.assertEqual(response.total, 2)
        self.assertEqual(response.accounts[0].nickname, "未适配账号")
        self.assertEqual(response.accounts[0].supported_games, ["zzz"])
        self.assertEqual(response.accounts[1].nickname, "支持账号")
        self.assertEqual(response.accounts[1].supported_games, ["genshin"])

    async def test_get_note_accounts_includes_zzz_supported_account(self):
        from app.api.notes import get_note_accounts

        async with await self._new_session() as session:
            user = User(username="notes-zzz-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()

            zzz_account = MihoyoAccount(user_id=user.id, nickname="绝区零账号", cookie_status="valid")
            session.add(zzz_account)
            await session.flush()

            session.add(
                GameRole(
                    account_id=zzz_account.id,
                    game_biz="nap_cn",
                    game_uid="90001",
                    nickname="绳匠",
                    region="prod_gf_cn",
                )
            )
            await session.commit()
            await session.refresh(user)

            response = await get_note_accounts(current_user=user, db=session)

        self.assertEqual(response.total, 1)
        self.assertEqual(response.accounts[0].nickname, "绝区零账号")
        self.assertEqual(response.accounts[0].supported_games, ["zzz"])

    async def test_get_note_accounts_skips_accounts_without_enabled_note_roles(self):
        from app.api.notes import get_note_accounts

        async with await self._new_session() as session:
            user = User(username="notes-enabled-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()

            disabled_only = MihoyoAccount(user_id=user.id, nickname="禁用角色账号", cookie_status="valid")
            enabled_account = MihoyoAccount(user_id=user.id, nickname="启用角色账号", cookie_status="valid")
            session.add_all([disabled_only, enabled_account])
            await session.flush()

            session.add_all([
                GameRole(
                    account_id=disabled_only.id,
                    game_biz="hk4e_cn",
                    game_uid="30001",
                    nickname="旅行者",
                    region="cn_gf01",
                    is_enabled=False,
                ),
                GameRole(
                    account_id=enabled_account.id,
                    game_biz="hk4e_cn",
                    game_uid="30002",
                    nickname="派蒙",
                    region="cn_gf01",
                    is_enabled=True,
                ),
            ])
            await session.commit()
            await session.refresh(user)

            response = await get_note_accounts(current_user=user, db=session)

        self.assertEqual(response.total, 1)
        self.assertEqual(response.accounts[0].nickname, "启用角色账号")

    async def test_get_note_accounts_returns_403_when_notes_disabled(self):
        from app.api.notes import get_note_accounts

        user, _ = await self._seed_account(role="user")

        async with await self._new_session() as session:
            await self._disable_notes_menu(session=session, user_visible=False, admin_visible=False)

            mock_list_supported_accounts = AsyncMock()
            with patch("app.api.notes.NoteService.list_supported_accounts", mock_list_supported_accounts):
                with self.assertRaises(HTTPException) as ctx:
                    await get_note_accounts(current_user=user, db=session)

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("实时便笺功能已被管理员禁用", ctx.exception.detail)
        mock_list_supported_accounts.assert_not_awaited()

    async def test_get_realtime_notes_returns_normalized_cards_for_supported_roles(self):
        from app.api.notes import get_realtime_notes

        user, account = await self._seed_account()

        async with await self._new_session() as session:
            session.add_all([
                GameRole(account_id=account.id, game_biz="hk4e_cn", game_uid="10001", nickname="旅行者", region="cn_gf01", level=60),
                GameRole(account_id=account.id, game_biz="hkrpg_cn", game_uid="20001", nickname="开拓者", region="prod_gf_cn", level=70),
            ])
            await session.commit()

            fetch_mock = AsyncMock(
                side_effect=[
                    (None, build_fake_genshin_notes()),
                    (None, build_fake_starrail_notes()),
                ]
            )
            with patch("app.services.notes.NoteService._build_genshin_client", return_value=object()), patch(
                "app.services.notes.NoteService._fetch_role_note_payload",
                fetch_mock,
            ):
                response = await get_realtime_notes(account_id=account.id, current_user=user, db=session)

        self.assertEqual(response.total_cards, 2)
        self.assertEqual(response.available_cards, 2)
        self.assertEqual(response.failed_cards, 0)
        self.assertEqual(response.schema_version, 2)
        self.assertEqual(response.provider, "genshin.py")
        self.assertEqual({card.game for card in response.cards}, {"genshin", "starrail"})

        genshin_card = next(card for card in response.cards if card.game == "genshin")
        starrail_card = next(card for card in response.cards if card.game == "starrail")

        self.assertEqual(genshin_card.status, "available")
        self.assertEqual(genshin_card.detail_kind, "genshin")
        self.assertEqual(genshin_card.detail["current_resin"], 120)
        self.assertIn("树脂", [metric.label for metric in genshin_card.metrics])
        self.assertEqual(starrail_card.status, "available")
        self.assertEqual(starrail_card.detail_kind, "starrail")
        self.assertEqual(starrail_card.detail["current_stamina"], 180)
        self.assertIn("开拓力", [metric.label for metric in starrail_card.metrics])

    async def test_get_realtime_notes_returns_zzz_detail_card(self):
        from app.api.notes import get_realtime_notes

        user, account = await self._seed_account()

        async with await self._new_session() as session:
            session.add(
                GameRole(
                    account_id=account.id,
                    game_biz="nap_cn",
                    game_uid="30001",
                    nickname="绳匠",
                    region="prod_gf_cn",
                    level=50,
                )
            )
            await session.commit()

            fetch_mock = AsyncMock(side_effect=[(None, build_fake_zzz_notes())])
            with patch("app.services.notes.NoteService._build_genshin_client", return_value=object()), patch(
                "app.services.notes.NoteService._fetch_role_note_payload",
                fetch_mock,
            ):
                response = await get_realtime_notes(account_id=account.id, current_user=user, db=session)

        self.assertEqual(response.total_cards, 1)
        self.assertEqual(response.cards[0].game, "zzz")
        self.assertEqual(response.cards[0].detail_kind, "zzz")
        self.assertIsInstance(response.cards[0].detail, dict)

    async def test_get_realtime_notes_marks_invalid_cookie_without_upstream_request(self):
        from app.api.notes import get_realtime_notes

        user, account = await self._seed_account(cookie_status="expired", with_cookie=False)

        async with await self._new_session() as session:
            session.add(
                GameRole(account_id=account.id, game_biz="hk4e_cn", game_uid="10001", nickname="旅行者", region="cn_gf01")
            )
            await session.commit()

            build_client_mock = unittest.mock.Mock()
            fetch_mock = AsyncMock()
            with patch("app.services.notes.NoteService._build_genshin_client", build_client_mock), patch(
                "app.services.notes.NoteService._fetch_role_note_payload",
                fetch_mock,
            ):
                response = await get_realtime_notes(account_id=account.id, current_user=user, db=session)

        self.assertEqual(response.total_cards, 1)
        self.assertEqual(response.available_cards, 0)
        self.assertEqual(response.failed_cards, 1)
        self.assertEqual(response.cards[0].status, "invalid_cookie")
        self.assertIn("登录态", response.cards[0].message)
        build_client_mock.assert_not_called()
        fetch_mock.assert_not_awaited()

    async def test_get_realtime_notes_still_queries_upstream_when_cookie_status_is_expired_but_cookie_exists(self):
        from app.api.notes import get_realtime_notes

        user, account = await self._seed_account(cookie_status="expired", with_cookie=True)

        async with await self._new_session() as session:
            session.add(
                GameRole(account_id=account.id, game_biz="hk4e_cn", game_uid="10001", nickname="旅行者", region="cn_gf01")
            )
            await session.commit()

            fetch_mock = AsyncMock(side_effect=[(None, build_fake_genshin_notes(current_resin=80, completed_commissions=4, remaining_resin_discounts=0, expedition_statuses=(False,)))])
            with patch("app.services.notes.NoteService._build_genshin_client", return_value=object()), patch(
                "app.services.notes.NoteService._fetch_role_note_payload",
                fetch_mock,
            ):
                response = await get_realtime_notes(account_id=account.id, current_user=user, db=session)

        self.assertEqual(fetch_mock.await_count, 1)
        self.assertEqual(response.available_cards, 1)
        self.assertEqual(response.cards[0].status, "available")

    async def test_get_realtime_notes_maps_upstream_verification_codes_to_actionable_status(self):
        from app.api.notes import get_realtime_notes

        user, account = await self._seed_account()

        async with await self._new_session() as session:
            session.add_all([
                GameRole(account_id=account.id, game_biz="hk4e_cn", game_uid="10001", nickname="旅行者", region="cn_gf01"),
                GameRole(account_id=account.id, game_biz="hkrpg_cn", game_uid="20001", nickname="开拓者", region="prod_gf_cn"),
            ])
            await session.commit()

            fetch_mock = AsyncMock(
                side_effect=[
                    genshin.GenshinException({"retcode": 5003, "message": ""}),
                    genshin.GenshinException({"retcode": 10041, "message": ""}),
                ]
            )
            with patch("app.services.notes.NoteService._build_genshin_client", return_value=object()), patch(
                "app.services.notes.NoteService._fetch_role_note_payload",
                fetch_mock,
            ):
                response = await get_realtime_notes(account_id=account.id, current_user=user, db=session)

        self.assertEqual(response.total_cards, 2)
        self.assertEqual(response.available_cards, 0)
        self.assertEqual(response.failed_cards, 2)
        self.assertEqual({card.status for card in response.cards}, {"verification_required"})
        self.assertTrue(all("验证" in (card.message or "") for card in response.cards))

    async def test_get_realtime_notes_does_not_map_cross_game_verification_codes(self):
        from app.api.notes import get_realtime_notes

        user, account = await self._seed_account()

        async with await self._new_session() as session:
            session.add_all([
                GameRole(account_id=account.id, game_biz="hk4e_cn", game_uid="10001", nickname="旅行者", region="cn_gf01"),
                GameRole(account_id=account.id, game_biz="hkrpg_cn", game_uid="20001", nickname="开拓者", region="prod_gf_cn"),
            ])
            await session.commit()

            fetch_mock = AsyncMock(
                side_effect=[
                    genshin.GenshinException({"retcode": 10041, "message": "genshin-wrong-code"}),
                    genshin.GenshinException({"retcode": 5003, "message": "starrail-wrong-code"}),
                ]
            )
            with patch("app.services.notes.NoteService._build_genshin_client", return_value=object()), patch(
                "app.services.notes.NoteService._fetch_role_note_payload",
                fetch_mock,
            ):
                response = await get_realtime_notes(account_id=account.id, current_user=user, db=session)

        status_by_game = {card.game: card.status for card in response.cards}
        message_by_game = {card.game: card.message for card in response.cards}
        self.assertEqual(status_by_game, {"genshin": "upstream_error", "starrail": "upstream_error"})
        self.assertEqual(message_by_game["genshin"], "genshin-wrong-code")
        self.assertEqual(message_by_game["starrail"], "starrail-wrong-code")

    async def test_get_realtime_notes_keeps_unknown_retcode_as_error(self):
        from app.api.notes import get_realtime_notes

        user, account = await self._seed_account()

        async with await self._new_session() as session:
            session.add(
                GameRole(account_id=account.id, game_biz="hk4e_cn", game_uid="10001", nickname="旅行者", region="cn_gf01")
            )
            await session.commit()

            fetch_mock = AsyncMock(
                side_effect=[genshin.GenshinException({"retcode": 12345, "message": "unexpected-upstream-error"})]
            )
            with patch("app.services.notes.NoteService._build_genshin_client", return_value=object()), patch(
                "app.services.notes.NoteService._fetch_role_note_payload",
                fetch_mock,
            ):
                response = await get_realtime_notes(account_id=account.id, current_user=user, db=session)

        self.assertEqual(response.cards[0].status, "upstream_error")
        self.assertEqual(response.cards[0].message, "unexpected-upstream-error")

    async def test_get_realtime_notes_maps_verification_for_whitelisted_retcode_even_if_message_mentions_app(self):
        from app.api.notes import get_realtime_notes

        user, account = await self._seed_account()

        async with await self._new_session() as session:
            session.add(
                GameRole(
                    account_id=account.id,
                    game_biz="hk4e_cn",
                    game_uid="10001",
                    nickname="旅行者",
                    region="cn_gf01",
                )
            )
            await session.commit()

            fetch_mock = AsyncMock(
                side_effect=[genshin.GenshinException({"retcode": 5003, "message": "app triggered verification"})]
            )
            with patch("app.services.notes.NoteService._build_genshin_client", return_value=object()), patch(
                "app.services.notes.NoteService._fetch_role_note_payload",
                fetch_mock,
            ):
                response = await get_realtime_notes(account_id=account.id, current_user=user, db=session)

        self.assertEqual(response.cards[0].status, "verification_required")
        self.assertTrue("验证" in (response.cards[0].message or ""))

    async def test_get_realtime_notes_does_not_treat_plain_app_keyword_as_verification(self):
        from app.api.notes import get_realtime_notes

        user, account = await self._seed_account()

        async with await self._new_session() as session:
            session.add(
                GameRole(
                    account_id=account.id,
                    game_biz="hk4e_cn",
                    game_uid="10001",
                    nickname="旅行者",
                    region="cn_gf01",
                )
            )
            await session.commit()

            fetch_mock = AsyncMock(
                side_effect=[genshin.GenshinException({"retcode": 12345, "message": "app"})]
            )
            with patch("app.services.notes.NoteService._build_genshin_client", return_value=object()), patch(
                "app.services.notes.NoteService._fetch_role_note_payload",
                fetch_mock,
            ):
                response = await get_realtime_notes(account_id=account.id, current_user=user, db=session)

        self.assertEqual(response.cards[0].status, "upstream_error")
        self.assertEqual(response.cards[0].message, "app")

    async def test_get_realtime_notes_returns_403_for_admin_when_notes_disabled(self):
        from app.api.notes import get_realtime_notes

        admin, account = await self._seed_account(role="admin")

        async with await self._new_session() as session:
            await self._disable_notes_menu(session=session, user_visible=False, admin_visible=False)

            mock_get_owned_account = AsyncMock()
            mock_get_summary = AsyncMock()
            with patch("app.api.notes.NoteService.get_owned_account", mock_get_owned_account), patch(
                "app.api.notes.NoteService.get_summary",
                mock_get_summary,
            ):
                with self.assertRaises(HTTPException) as ctx:
                    await get_realtime_notes(account_id=account.id, current_user=admin, db=session)

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("实时便笺功能已被管理员禁用", ctx.exception.detail)
        mock_get_owned_account.assert_not_awaited()
        mock_get_summary.assert_not_awaited()

    async def test_fetch_role_note_card_does_not_mask_detail_mapping_bug_as_upstream_error(self):
        """
        回归测试：本地 detail/metrics 映射属于服务层实现，异常必须向上抛出。

        长期维护说明（避免误改）：
        - provider（genshin.py / 上游接口）失败应转为用户可见状态卡片（upstream_error / invalid_cookie / verification_required 等），
          以保证前端聚合协议稳定。
        - 但 detail/metrics 的映射逻辑是本地实现；一旦出错属于代码缺陷，不应伪装成上游不可用，否则会掩盖回归并误导排障。
        """

        from app.services.notes import NoteService

        service = NoteService(db=AsyncMock(spec=AsyncSession))
        role = GameRole(
            account_id=1,
            game_biz="hk4e_cn",
            game_uid="10001",
            nickname="旅行者",
            region="cn_gf01",
        )
        # 仅用于构造 NoteCardResponse 的必填字段；此测试关注的是“映射异常是否被吞为 upstream_error”，
        # 不应因为未持久化的 role.id=None 引入 pydantic 校验噪声而掩盖断言意图。
        role.id = 1
        client = object()

        fetch_mock = AsyncMock(return_value=(service._get_config_for_role(role), build_fake_genshin_notes()))
        with patch("app.services.notes.NoteService._fetch_role_note_payload", fetch_mock), patch(
            "app.services.notes.NoteService._build_detail_and_metrics",
            side_effect=ValueError("detail-mapping-bug"),
        ):
            with self.assertRaises(ValueError) as ctx:
                await service._fetch_role_note_card(client, role)

        self.assertEqual(str(ctx.exception), "detail-mapping-bug")

    async def test_get_realtime_notes_maps_provider_adapter_exception_to_upstream_error_card(self):
        """
        回归测试：provider/integration 边界（payload 获取 + 适配层）发生非 genshin.* 异常时，
        也必须返回 upstream_error 状态卡片，不能把请求打穿成 500。

        说明：
        - 这类异常通常来自“适配层/解析层”实现问题（例如 getattr/类型转换/model 解析），
          对用户而言表现为上游不可用或服务暂不可用，应降级为 upstream_error 卡；
        - 本地 detail/metrics 映射异常仍必须上抛，不能被这层兜底吞掉（由另一条测试覆盖）。
        """

        from app.api.notes import get_realtime_notes

        user, account = await self._seed_account()

        async with await self._new_session() as session:
            session.add(
                GameRole(
                    account_id=account.id,
                    game_biz="hk4e_cn",
                    game_uid="10001",
                    nickname="旅行者",
                    region="cn_gf01",
                    level=60,
                )
            )
            await session.commit()

            fetch_mock = AsyncMock(side_effect=ValueError("provider-adapter-bug"))
            with patch("app.services.notes.NoteService._build_genshin_client", return_value=object()), patch(
                "app.services.notes.NoteService._fetch_role_note_payload",
                fetch_mock,
            ):
                response = await get_realtime_notes(account_id=account.id, current_user=user, db=session)

        self.assertEqual(response.total_cards, 1)
        self.assertEqual(response.cards[0].status, "upstream_error")

    async def test_fetch_role_note_payload_uses_explicit_server_for_bilibili_role(self):
        """
        高风险区服（例如 B 服）不能只靠 UID 推断 server。

        genshin.py 的高层 get_*_notes 会默认通过 uid -> recognize_*_server() 推断 server，
        但 B 服与官服在同一 UID 号段内（至少在国内服场景），仅靠 uid 无法区分 cn_gf01 / cn_qd01。
        因此服务层必须在这些高风险角色上改走底层 request_game_record，并显式携带 role.region 作为 server。

        该测试用于“锁死契约”：
        - hk4e_bilibili 必须走显式 server 路径
        - request_game_record 的 params.server 必须等于 role.region
        """

        from app.services.notes import NoteService

        service = NoteService(db=AsyncMock(spec=AsyncSession))
        role = GameRole(
            account_id=1,
            game_biz="hk4e_bilibili",
            game_uid="10001",
            nickname="旅行者",
            region="cn_qd01",
        )

        client = SimpleNamespace(
            # 旧路径会走 get_genshin_notes；新契约要求对 B 服改走 request_game_record。
            get_genshin_notes=AsyncMock(return_value=build_fake_genshin_notes()),
            update_settings=AsyncMock(),
            request_game_record=AsyncMock(return_value={"data": {"mock": "payload"}}),
        )

        sentinel = object()
        with patch("app.services.notes.genshin.models.Notes", autospec=True) as model_mock:
            model_mock.return_value = sentinel
            config, payload = await service._fetch_role_note_payload(client, role)

        self.assertIsNotNone(config)
        self.assertEqual(config.game, "genshin")
        self.assertIs(payload, sentinel)

        client.get_genshin_notes.assert_not_awaited()
        client.request_game_record.assert_awaited_once()

        called = client.request_game_record.await_args
        self.assertEqual(called.args[0], "dailyNote")
        self.assertEqual(called.kwargs.get("game"), genshin.Game.GENSHIN)
        self.assertEqual(called.kwargs.get("region"), genshin.Region.CHINESE)
        params = called.kwargs.get("params") or {}
        self.assertEqual(params.get("server"), role.region)
        self.assertEqual(params.get("role_id"), role.game_uid)

    async def test_request_notes_with_explicit_server_retries_after_autoauth_for_bilibili_role(self):
        """
        显式 server helper 必须保留与 genshin.py 高层 API 等价的 autoauth 语义：
        - 首次请求若抛出 DataNotPublic（上游提示“数据未公开”）
        - 且允许 autoauth 时：update_settings(3, True, game=...) 后重试一次
        - 重试成功后返回解析后的 model
        """

        from app.services.notes import NoteService

        service = NoteService(db=AsyncMock(spec=AsyncSession))
        role = GameRole(
            account_id=1,
            game_biz="hk4e_bilibili",
            game_uid="10001",
            nickname="旅行者",
            region="cn_qd01",
        )
        config = service._get_config_for_role(role)
        self.assertIsNotNone(config)

        client = SimpleNamespace(
            update_settings=AsyncMock(),
            request_game_record=AsyncMock(
                side_effect=[
                    genshin.DataNotPublic({"retcode": -1, "message": "Data not public"}),
                    {"data": {"mock": "payload"}},
                ]
            ),
        )

        sentinel = object()
        with patch("app.services.notes.genshin.models.Notes", autospec=True) as model_mock:
            model_mock.return_value = sentinel
            payload = await service._request_notes_with_explicit_server(
                client,
                config=config,
                role=role,
                lang="zh-cn",
                autoauth=True,
            )

        self.assertIs(payload, sentinel)

        client.request_game_record.assert_awaited()
        self.assertEqual(client.request_game_record.await_count, 2)
        client.update_settings.assert_awaited_once()

        called = client.update_settings.await_args
        self.assertEqual(called.args[0], 3)
        self.assertEqual(called.args[1], True)
        self.assertEqual(called.kwargs.get("game"), genshin.Game.GENSHIN)

    async def test_fetch_role_note_payload_uses_explicit_server_for_starrail_bilibili_role(self):
        """
        覆盖星铁 B 服显式 server 契约：
        - endpoint 必须是 note
        - game 必须是 genshin.Game.STARRAIL
        - model 必须是 genshin.models.StarRailNote
        """

        from app.services.notes import NoteService

        service = NoteService(db=AsyncMock(spec=AsyncSession))
        role = GameRole(
            account_id=1,
            game_biz="hkrpg_bilibili",
            game_uid="20001",
            nickname="开拓者",
            region="prod_qd_cn",
        )

        client = SimpleNamespace(
            get_starrail_notes=AsyncMock(return_value=build_fake_starrail_notes()),
            update_settings=AsyncMock(),
            request_game_record=AsyncMock(return_value={"data": {"mock": "payload"}}),
        )

        sentinel = object()
        with patch("app.services.notes.genshin.models.StarRailNote", autospec=True) as model_mock:
            model_mock.return_value = sentinel
            config, payload = await service._fetch_role_note_payload(client, role)

        self.assertIsNotNone(config)
        self.assertEqual(config.game, "starrail")
        self.assertIs(payload, sentinel)

        client.get_starrail_notes.assert_not_awaited()
        client.request_game_record.assert_awaited_once()

        called = client.request_game_record.await_args
        self.assertEqual(called.args[0], "note")
        self.assertEqual(called.kwargs.get("game"), genshin.Game.STARRAIL)
        self.assertEqual(called.kwargs.get("region"), genshin.Region.CHINESE)
        params = called.kwargs.get("params") or {}
        self.assertEqual(params.get("server"), role.region)
        self.assertEqual(params.get("role_id"), role.game_uid)

    async def test_fetch_role_note_payload_keeps_high_level_method_for_non_bilibili_role(self):
        """
        负向用例：非 *_bilibili 角色应继续走 genshin.py 高层 get_*_notes(autoauth=True) 路径，
        避免误把常规角色也强制迁移到底层 request_game_record。
        """

        from app.services.notes import NoteService

        service = NoteService(db=AsyncMock(spec=AsyncSession))
        role = GameRole(
            account_id=1,
            game_biz="hk4e_cn",
            game_uid="10001",
            nickname="旅行者",
            region="cn_gf01",
        )

        sentinel = object()
        client = SimpleNamespace(
            get_genshin_notes=AsyncMock(return_value=sentinel),
            request_game_record=AsyncMock(),
            update_settings=AsyncMock(),
        )

        config, payload = await service._fetch_role_note_payload(client, role)

        self.assertIsNotNone(config)
        self.assertEqual(config.game, "genshin")
        self.assertIs(payload, sentinel)

        client.get_genshin_notes.assert_awaited_once_with(uid=10001, lang="zh-cn", autoauth=True)
        client.request_game_record.assert_not_awaited()
        client.update_settings.assert_not_awaited()

    async def test_notes_contract_calls_genshin_high_level_api_for_non_bilibili_hk4e_cn_role(self):
        """
        接入层契约测试（不再 patch 内部 helper）：
        - 必须通过 `genshin.Client(cookies=..., lang='zh-cn')` 构造真实接入层 client
        - 常规（非 *_bilibili）原神角色必须调用高层 `get_genshin_notes(uid=..., lang='zh-cn', autoauth=True)`

        该测试的目的不是覆盖业务映射细节，而是“锁死服务层与 genshin.py 的高层 API 契约”，
        防止后续重构误改为 patch helper 或误走显式 server 分支。
        """

        from app.services.notes import NoteService

        _, account = await self._seed_account()

        async with await self._new_session() as session:
            session.add(
                GameRole(
                    account_id=account.id,
                    game_biz="hk4e_cn",
                    game_uid="10001",
                    nickname="旅行者",
                    region="cn_gf01",
                )
            )
            await session.commit()

            client_instance = SimpleNamespace(
                get_genshin_notes=AsyncMock(return_value=build_fake_genshin_notes()),
                get_starrail_notes=AsyncMock(),
                get_zzz_notes=AsyncMock(),
                request_game_record=AsyncMock(),
                update_settings=AsyncMock(),
            )

            with patch("app.services.notes.genshin.Client") as client_cls:
                client_cls.return_value = client_instance
                service = NoteService(db=session)
                response = await service.get_summary(account=account)

        self.assertEqual(response.total_cards, 1)
        client_cls.assert_called_once_with(cookies="ltuid=10001; cookie_token=test-token", lang="zh-cn")
        client_instance.get_genshin_notes.assert_awaited_once_with(uid=10001, lang="zh-cn", autoauth=True)

    async def test_notes_contract_calls_starrail_high_level_api_for_non_bilibili_hkrpg_cn_role(self):
        """
        接入层契约测试：常规（非 *_bilibili）星铁角色应调用高层 `get_starrail_notes(...)`，
        且参数至少包含 uid/lang/autoauth（固定 lang='zh-cn'、autoauth=True）。
        """

        from app.services.notes import NoteService

        _, account = await self._seed_account()

        async with await self._new_session() as session:
            session.add(
                GameRole(
                    account_id=account.id,
                    game_biz="hkrpg_cn",
                    game_uid="20001",
                    nickname="开拓者",
                    region="prod_gf_cn",
                )
            )
            await session.commit()

            client_instance = SimpleNamespace(
                get_genshin_notes=AsyncMock(),
                get_starrail_notes=AsyncMock(return_value=build_fake_starrail_notes()),
                get_zzz_notes=AsyncMock(),
                request_game_record=AsyncMock(),
                update_settings=AsyncMock(),
            )

            with patch("app.services.notes.genshin.Client") as client_cls:
                client_cls.return_value = client_instance
                service = NoteService(db=session)
                response = await service.get_summary(account=account)

        self.assertEqual(response.total_cards, 1)
        client_cls.assert_called_once_with(cookies="ltuid=10001; cookie_token=test-token", lang="zh-cn")
        client_instance.get_starrail_notes.assert_awaited_once_with(uid=20001, lang="zh-cn", autoauth=True)

    async def test_notes_contract_calls_zzz_high_level_api_for_non_bilibili_nap_cn_role(self):
        """
        接入层契约测试：常规（非 *_bilibili）绝区零角色应调用高层 `get_zzz_notes(...)`，
        且参数至少包含 uid/lang/autoauth（固定 lang='zh-cn'、autoauth=True）。
        """

        from app.services.notes import NoteService

        _, account = await self._seed_account()

        async with await self._new_session() as session:
            session.add(
                GameRole(
                    account_id=account.id,
                    game_biz="nap_cn",
                    game_uid="90001",
                    nickname="绳匠",
                    region="prod_gf_cn",
                )
            )
            await session.commit()

            client_instance = SimpleNamespace(
                get_genshin_notes=AsyncMock(),
                get_starrail_notes=AsyncMock(),
                get_zzz_notes=AsyncMock(return_value=build_fake_zzz_notes()),
                request_game_record=AsyncMock(),
                update_settings=AsyncMock(),
            )

            with patch("app.services.notes.genshin.Client") as client_cls:
                client_cls.return_value = client_instance
                service = NoteService(db=session)
                response = await service.get_summary(account=account)

        self.assertEqual(response.total_cards, 1)
        client_cls.assert_called_once_with(cookies="ltuid=10001; cookie_token=test-token", lang="zh-cn")
        client_instance.get_zzz_notes.assert_awaited_once_with(uid=90001, lang="zh-cn", autoauth=True)
