import os
import unittest
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.account import GameRole, MihoyoAccount
from app.models.user import User
from app.utils.crypto import encrypt_cookie


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, payload_map):
        self.payload_map = payload_map
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        for keyword, payload in self.payload_map.items():
            if keyword in url:
                return FakeResponse(payload)
        raise AssertionError(f"unexpected request url: {url}")


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

    async def _seed_account(self, *, cookie_status: str = "valid", with_cookie: bool = True):
        async with await self._new_session() as session:
            user = User(username="note-user", password_hash="x", role="user", is_active=True)
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

        self.assertEqual(response.total, 1)
        self.assertEqual(response.accounts[0].nickname, "支持账号")
        self.assertEqual(response.accounts[0].supported_games, ["genshin"])

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

    async def test_get_realtime_notes_returns_normalized_cards_for_supported_roles(self):
        from app.api.notes import get_realtime_notes

        user, account = await self._seed_account()

        async with await self._new_session() as session:
            session.add_all([
                GameRole(account_id=account.id, game_biz="hk4e_cn", game_uid="10001", nickname="旅行者", region="cn_gf01", level=60),
                GameRole(account_id=account.id, game_biz="hkrpg_cn", game_uid="20001", nickname="开拓者", region="prod_gf_cn", level=70),
            ])
            await session.commit()

            payloads = {
                "/genshin/api/dailyNote": {
                    "retcode": 0,
                    "message": "OK",
                    "data": {
                        "current_resin": 120,
                        "max_resin": 160,
                        "resin_recovery_time": "3600",
                        "finished_task_num": 3,
                        "total_task_num": 4,
                        "current_home_coin": 1800,
                        "max_home_coin": 2400,
                        "home_coin_recovery_time": "7200",
                        "remain_resin_discount_num": 1,
                        "resin_discount_num_limit": 3,
                        "current_expedition_num": 2,
                        "max_expedition_num": 5,
                        "expeditions": [
                            {"status": "Finished", "remained_time": "0"},
                            {"status": "Ongoing", "remained_time": "1800"},
                        ],
                    },
                },
                "/hkrpg/api/note": {
                    "retcode": 0,
                    "message": "OK",
                    "data": {
                        "current_stamina": 180,
                        "max_stamina": 240,
                        "stamina_recover_time": "5400",
                        "current_reserve_stamina": 1200,
                        "accepted_epedition_num": 3,
                        "total_expedition_num": 4,
                        "current_train_score": 400,
                        "max_train_score": 500,
                        "expeditions": [
                            {"status": "Finished", "remaining_time": "0"},
                            {"status": "Ongoing", "remaining_time": "3600"},
                        ],
                    },
                },
            }

            with patch("app.services.notes.httpx.AsyncClient", return_value=FakeAsyncClient(payloads)):
                response = await get_realtime_notes(account_id=account.id, current_user=user, db=session)

        self.assertEqual(response.total_cards, 2)
        self.assertEqual(response.available_cards, 2)
        self.assertEqual(response.failed_cards, 0)
        self.assertEqual({card.game for card in response.cards}, {"genshin", "starrail"})

        genshin_card = next(card for card in response.cards if card.game == "genshin")
        starrail_card = next(card for card in response.cards if card.game == "starrail")

        self.assertEqual(genshin_card.status, "available")
        self.assertIn("树脂", [metric.label for metric in genshin_card.metrics])
        self.assertEqual(starrail_card.status, "available")
        self.assertIn("开拓力", [metric.label for metric in starrail_card.metrics])

    async def test_get_realtime_notes_marks_invalid_cookie_without_upstream_request(self):
        from app.api.notes import get_realtime_notes

        user, account = await self._seed_account(cookie_status="expired", with_cookie=False)

        async with await self._new_session() as session:
            session.add(
                GameRole(account_id=account.id, game_biz="hk4e_cn", game_uid="10001", nickname="旅行者", region="cn_gf01")
            )
            await session.commit()

            client = FakeAsyncClient({})
            with patch("app.services.notes.httpx.AsyncClient", return_value=client):
                response = await get_realtime_notes(account_id=account.id, current_user=user, db=session)

        self.assertEqual(response.total_cards, 1)
        self.assertEqual(response.available_cards, 0)
        self.assertEqual(response.failed_cards, 1)
        self.assertEqual(response.cards[0].status, "invalid_cookie")
        self.assertIn("登录态", response.cards[0].message)
        self.assertEqual(client.calls, [])

    async def test_get_realtime_notes_still_queries_upstream_when_cookie_status_is_expired_but_cookie_exists(self):
        from app.api.notes import get_realtime_notes

        user, account = await self._seed_account(cookie_status="expired", with_cookie=True)

        async with await self._new_session() as session:
            session.add(
                GameRole(account_id=account.id, game_biz="hk4e_cn", game_uid="10001", nickname="旅行者", region="cn_gf01")
            )
            await session.commit()

            payloads = {
                "/genshin/api/dailyNote": {
                    "retcode": 0,
                    "message": "OK",
                    "data": {
                        "current_resin": 80,
                        "max_resin": 160,
                        "resin_recovery_time": "1800",
                        "finished_task_num": 4,
                        "total_task_num": 4,
                        "current_home_coin": 1200,
                        "max_home_coin": 2400,
                        "home_coin_recovery_time": "5400",
                        "remain_resin_discount_num": 0,
                        "resin_discount_num_limit": 3,
                        "current_expedition_num": 1,
                        "max_expedition_num": 5,
                        "expeditions": [
                            {"status": "Ongoing", "remained_time": "600"},
                        ],
                    },
                },
            }

            client = FakeAsyncClient(payloads)
            with patch("app.services.notes.httpx.AsyncClient", return_value=client):
                response = await get_realtime_notes(account_id=account.id, current_user=user, db=session)

        self.assertEqual(len(client.calls), 1)
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

            payloads = {
                "/genshin/api/dailyNote": {
                    "retcode": 5003,
                    "message": "",
                    "data": None,
                },
                "/hkrpg/api/note": {
                    "retcode": 10041,
                    "message": "",
                    "data": None,
                },
            }

            with patch("app.services.notes.httpx.AsyncClient", return_value=FakeAsyncClient(payloads)):
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

            payloads = {
                "/genshin/api/dailyNote": {
                    "retcode": 10041,
                    "message": "genshin-wrong-code",
                    "data": None,
                },
                "/hkrpg/api/note": {
                    "retcode": 5003,
                    "message": "starrail-wrong-code",
                    "data": None,
                },
            }

            with patch("app.services.notes.httpx.AsyncClient", return_value=FakeAsyncClient(payloads)):
                response = await get_realtime_notes(account_id=account.id, current_user=user, db=session)

        status_by_game = {card.game: card.status for card in response.cards}
        message_by_game = {card.game: card.message for card in response.cards}
        self.assertEqual(status_by_game, {"genshin": "error", "starrail": "error"})
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

            payloads = {
                "/genshin/api/dailyNote": {
                    "retcode": 12345,
                    "message": "unexpected-upstream-error",
                    "data": None,
                },
            }

            with patch("app.services.notes.httpx.AsyncClient", return_value=FakeAsyncClient(payloads)):
                response = await get_realtime_notes(account_id=account.id, current_user=user, db=session)

        self.assertEqual(response.cards[0].status, "error")
        self.assertEqual(response.cards[0].message, "unexpected-upstream-error")
