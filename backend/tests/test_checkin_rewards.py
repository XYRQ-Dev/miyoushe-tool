import json
import os
import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "mysql+asyncmy://demo:demo@127.0.0.1:3306/miyoushe?charset=utf8mb4"

from app.api.logs import get_reward_calendar
from app.models.account import GameRole, MihoyoAccount
from app.models.checkin_reward_catalog import CheckinRewardCatalog
from app.models.task_log import TaskLog
from app.models.user import User
from app.schemas.task_log import CheckinResult, CheckinSummary
from app.services.checkin import SIGN_INFO_URL, SIGN_REWARDS_URL, CheckinGameConfig, CheckinService
from app.services.checkin_rewards import (
    ParsedAward,
    build_month_award_items,
    build_reward_game_options,
    format_reward_text,
    parse_home_awards,
    pick_default_family,
    pick_default_role_id,
    preview_reward_index,
    resolve_claimed_reward_index,
)
from app.services.notifier import NotificationService
from tests.mysql_test_case import MySqlIsolatedAsyncioTestCase


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, *, get_payload=None, post_payload=None, get_payloads_by_url=None):
        self.get_payload = get_payload
        self.post_payload = post_payload
        self.get_payloads_by_url = get_payloads_by_url or {}
        self.last_get = None
        self.last_post = None
        self.get_calls = []
        self.post_calls = []

    async def get(self, url, **kwargs):
        self.last_get = {"url": url, **kwargs}
        self.get_calls.append(self.last_get)
        payload = self.get_payloads_by_url.get(url, self.get_payload)
        return FakeResponse(payload)

    async def post(self, url, **kwargs):
        self.last_post = {"url": url, **kwargs}
        self.post_calls.append(self.last_post)
        return FakeResponse(self.post_payload)


class CheckinRewardParseTests(unittest.TestCase):
    def test_parse_home_awards_keeps_empty_name_slots_and_prefers_icon(self):
        awards = parse_home_awards(
            {
                "retcode": 0,
                "data": {
                    "awards": [
                        {"name": "原石", "cnt": "20", "icon": "https://a"},
                        {"name": "  ", "cnt": 1, "img": "https://b"},
                        {"name": "摩拉", "cnt": 10000, "icon": "", "img": "https://c"},
                    ]
                },
            }
        )

        self.assertEqual(awards[0], ParsedAward(name="原石", cnt=20, icon="https://a"))
        self.assertEqual(awards[1], ParsedAward(name="", cnt=1, icon="https://b"))
        self.assertEqual(awards[2], ParsedAward(name="摩拉", cnt=10000, icon="https://c"))

    def test_parse_home_awards_returns_none_on_nonzero_retcode(self):
        self.assertIsNone(parse_home_awards({"retcode": -1, "data": {"awards": [{"name": "原石", "cnt": 1}]}}))

    def test_resolve_claimed_reward_index_uses_result_total_minus_one(self):
        self.assertEqual(
            resolve_claimed_reward_index(signed_from_info=True, result_total=12, query_total=11),
            11,
        )
        self.assertEqual(
            resolve_claimed_reward_index(signed_from_info=False, result_total=12, query_total=11),
            11,
        )

    def test_resolve_claimed_reward_index_falls_back_to_query_total_after_sign(self):
        self.assertEqual(
            resolve_claimed_reward_index(signed_from_info=False, result_total=None, query_total=11),
            11,
        )
        self.assertIsNone(
            resolve_claimed_reward_index(signed_from_info=True, result_total=None, query_total=11)
        )

    def test_preview_reward_index_takes_max_of_official_and_local_counts(self):
        self.assertEqual(preview_reward_index(12, 5), 12)
        self.assertEqual(preview_reward_index(None, 5), 5)

    def test_build_month_award_items_skips_missed_before_first_activity(self):
        awards = [ParsedAward(name=f"奖{day}", cnt=day) for day in range(1, 32)]
        items = build_month_award_items(
            awards=awards,
            today=date(2026, 9, 10),
            claimed_days={5, 7},
            first_activity_day=5,
        )

        self.assertEqual(items[0]["status"], "empty")
        self.assertEqual(items[3]["status"], "empty")
        self.assertEqual(items[4]["status"], "claimed")
        self.assertEqual(items[5]["status"], "missed")
        self.assertEqual(items[6]["status"], "claimed")
        self.assertEqual(items[8]["status"], "missed")
        self.assertEqual(items[9]["status"], "today")
        self.assertEqual(items[10]["status"], "future")

    def test_pick_default_family_prefers_catalog_then_activity(self):
        families = ["hk4e", "hkrpg", "nap"]
        self.assertEqual(
            pick_default_family(families, {"hkrpg"}, {"hk4e"}),
            "hkrpg",
        )
        self.assertEqual(
            pick_default_family(families, set(), {"nap"}),
            "nap",
        )
        self.assertEqual(
            pick_default_family(families, set(), set()),
            "hk4e",
        )
        self.assertIsNone(pick_default_family([], set(), set()))

    def test_pick_default_role_id_prefers_claimed(self):
        self.assertEqual(pick_default_role_id([1, 2, 3], {3, 2}), 2)
        self.assertEqual(pick_default_role_id([1, 2], set()), 1)
        self.assertIsNone(pick_default_role_id([], {1}))

    def test_build_reward_game_options_uses_first_seen_family_order(self):
        class Role:
            def __init__(self, game_biz):
                self.game_biz = game_biz

        options = build_reward_game_options(
            [
                Role("hk4e_cn"),
                Role("hkrpg_cn"),
                Role("hk4e_bilibili"),
                Role("nap_cn"),
            ],
            {"hkrpg", "nap"},
        )
        self.assertEqual(
            options,
            [
                {"game": "hk4e", "catalog_available": False, "role_count": 2},
                {"game": "hkrpg", "catalog_available": True, "role_count": 1},
                {"game": "nap", "catalog_available": True, "role_count": 1},
            ],
        )

    def test_build_month_award_items_does_not_mark_missed_without_logs(self):
        awards = [ParsedAward(name="原石", cnt=20)]
        items = build_month_award_items(
            awards=awards,
            today=date(2026, 9, 10),
            claimed_days=set(),
            first_activity_day=None,
        )

        self.assertEqual(items[0]["status"], "empty")
        self.assertEqual(items[8]["status"], "empty")
        self.assertEqual(items[9]["status"], "today")

    def test_today_only_risk_is_not_claimed(self):
        items = build_month_award_items(
            awards=[ParsedAward(name="原石", cnt=20) for _ in range(10)],
            today=date(2026, 9, 10),
            claimed_days=set(),
            first_activity_day=8,
        )
        self.assertEqual(items[8]["status"], "missed")
        self.assertEqual(items[9]["status"], "today")

    def test_format_reward_text(self):
        self.assertEqual(format_reward_text("原石", 20), "原石 ×20")
        self.assertIsNone(format_reward_text(None, 20))


class CheckinRewardFlowTests(MySqlIsolatedAsyncioTestCase):
    async def test_checkin_role_maps_already_signed_reward_from_home(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            service._sleep_between_info_and_sign = AsyncMock()
            service._sleep_between_roles = AsyncMock()
            awards = [{"name": f"奖{i}", "cnt": i, "icon": None} for i in range(1, 13)]
            client = FakeClient(
                get_payloads_by_url={
                    SIGN_INFO_URL: {"retcode": 0, "data": {"is_sign": True, "total_sign_day": 12}},
                    SIGN_REWARDS_URL: {"retcode": 0, "data": {"awards": awards}},
                }
            )
            account = MihoyoAccount(id=1, user_id=1, nickname="测试账号")
            role = GameRole(id=2, account_id=1, game_biz="hkrpg_cn", game_uid="10001", region="prod_gf_cn")

            result = await service._checkin_role(
                account,
                role,
                "ltuid=1;",
                client,
                ("device-id", "device-fp"),
            )

        self.assertEqual(result.status, "already_signed")
        self.assertEqual(result.reward_name, "奖12")
        self.assertEqual(result.reward_cnt, 12)
        self.assertEqual(len(client.post_calls), 0)

    async def test_checkin_role_uses_query_total_when_sign_omits_total_sign_day(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            service._sleep_between_info_and_sign = AsyncMock()
            service._sleep_between_roles = AsyncMock()
            awards = [{"name": f"奖{i}", "cnt": i, "icon": None} for i in range(1, 13)]
            client = FakeClient(
                get_payloads_by_url={
                    SIGN_INFO_URL: {"retcode": 0, "data": {"is_sign": False, "total_sign_day": 11}},
                    SIGN_REWARDS_URL: {"retcode": 0, "data": {"awards": awards}},
                },
                post_payload={"retcode": 0, "data": {"success": 0, "is_risk": False}},
            )
            account = MihoyoAccount(id=1, user_id=1, nickname="测试账号")
            role = GameRole(id=2, account_id=1, game_biz="hkrpg_cn", game_uid="10001", region="prod_gf_cn")

            result = await service._checkin_role(
                account,
                role,
                "ltuid=1;",
                client,
                ("device-id", "device-fp"),
            )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.reward_name, "奖12")
        self.assertEqual(result.reward_cnt, 12)

    async def test_home_failure_does_not_fail_sign(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            service._sleep_between_info_and_sign = AsyncMock()
            service._sleep_between_roles = AsyncMock()
            client = FakeClient(
                get_payloads_by_url={
                    SIGN_INFO_URL: {"retcode": 0, "data": {"is_sign": False, "total_sign_day": 3}},
                    SIGN_REWARDS_URL: {"retcode": -1, "message": "busy"},
                },
                post_payload={"retcode": 0, "data": {"success": 0, "total_sign_day": 4}},
            )
            account = MihoyoAccount(id=1, user_id=1, nickname="测试账号")
            role = GameRole(id=2, account_id=1, game_biz="hkrpg_cn", game_uid="10001", region="prod_gf_cn")

            result = await service._checkin_role(
                account,
                role,
                "ltuid=1;",
                client,
                ("device-id", "device-fp"),
            )

        self.assertEqual(result.status, "success")
        self.assertIsNone(result.reward_name)

    async def test_same_act_id_fetches_home_once(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            service._sleep_between_info_and_sign = AsyncMock()
            service._sleep_between_roles = AsyncMock()
            awards = [{"name": "原石", "cnt": 20, "icon": None} for _ in range(12)]
            client = FakeClient(
                get_payloads_by_url={
                    SIGN_INFO_URL: {"retcode": 0, "data": {"is_sign": True, "total_sign_day": 1}},
                    SIGN_REWARDS_URL: {"retcode": 0, "data": {"awards": awards}},
                }
            )
            account = MihoyoAccount(id=1, user_id=1, nickname="测试账号")
            role_a = GameRole(id=2, account_id=1, game_biz="hkrpg_cn", game_uid="10001", region="prod_gf_cn")
            role_b = GameRole(id=3, account_id=1, game_biz="hkrpg_cn", game_uid="10002", region="prod_gf_cn")

            await service._checkin_role(account, role_a, "ltuid=1;", client, ("device-id", "device-fp"))
            await service._checkin_role(account, role_b, "ltuid=1;", client, ("device-id", "device-fp"))

        home_calls = [call for call in client.get_calls if call["url"] == SIGN_REWARDS_URL]
        self.assertEqual(len(home_calls), 1)

    async def test_bh3_home_omits_signgame_and_zzz_uses_nap_home(self):
        async with await self._new_session() as session:
            service = CheckinService(session)
            bh3_client = FakeClient(get_payload={"retcode": 0, "data": {"awards": []}})
            zzz_client = FakeClient(get_payload={"retcode": 0, "data": {"awards": []}})
            bh3_role = GameRole(id=3, account_id=1, game_biz="bh3_cn", game_uid="30001", region="android01")
            zzz_role = GameRole(id=4, account_id=1, game_biz="nap_cn", game_uid="20001", region="prod_gf_cn")

            await service._fetch_monthly_rewards(
                bh3_client,
                "ltuid=1;",
                CheckinGameConfig(
                    act_id="e202306201626331",
                    sign_game="bh3",
                    send_sign_game=False,
                    referer="https://webstatic.mihoyo.com/bbs/event/signin/bh3/index.html",
                ),
                bh3_role,
                ("device-id", "device-fp"),
            )
            await service._fetch_monthly_rewards(
                zzz_client,
                "ltuid=1;",
                CheckinGameConfig(
                    act_id="e202406242138391",
                    sign_game="zzz",
                    info_url="https://act-nap-api.mihoyo.com/event/luna/zzz/info",
                    sign_url="https://act-nap-api.mihoyo.com/event/luna/zzz/sign",
                    rewards_url="https://act-nap-api.mihoyo.com/event/luna/zzz/home",
                ),
                zzz_role,
                ("device-id", "device-fp"),
            )

        self.assertNotIn("x-rpc-signgame", bh3_client.last_get["headers"])
        self.assertEqual(zzz_client.last_get["url"], "https://act-nap-api.mihoyo.com/event/luna/zzz/home")
        self.assertEqual(zzz_client.last_get["headers"]["x-rpc-signgame"], "zzz")

    async def test_reward_calendar_marks_missed_and_rejects_foreign_role(self):
        async with await self._new_session() as session:
            owner = User(username="reward-owner", password_hash="x", role="user", is_active=True)
            other = User(username="reward-other", password_hash="x", role="user", is_active=True)
            session.add_all([owner, other])
            await session.flush()

            account = MihoyoAccount(user_id=owner.id, nickname="我的账号", cookie_encrypted="encrypted")
            foreign_account = MihoyoAccount(user_id=other.id, nickname="别人的账号", cookie_encrypted="encrypted")
            session.add_all([account, foreign_account])
            await session.flush()

            role = GameRole(
                account_id=account.id,
                game_biz="hk4e_cn",
                game_uid="10001",
                nickname="旅行者",
                region="cn_gf01",
            )
            foreign_role = GameRole(
                account_id=foreign_account.id,
                game_biz="hk4e_cn",
                game_uid="20001",
                nickname="别人",
                region="cn_gf01",
            )
            session.add_all([role, foreign_role])
            await session.flush()

            awards = [{"name": f"奖{i}", "cnt": i, "icon": None} for i in range(1, 32)]
            session.add(
                CheckinRewardCatalog(
                    act_id="e202311201442471",
                    game_family="hk4e",
                    month="2026-09",
                    awards_json=json.dumps(awards, ensure_ascii=False),
                    fetched_at=datetime(2026, 9, 5, 1, 0, 0),
                )
            )
            session.add_all(
                [
                    TaskLog(
                        account_id=account.id,
                        game_role_id=role.id,
                        task_type="checkin",
                        status="success",
                        message="ok",
                        total_sign_days=1,
                        reward_name="奖5",
                        reward_cnt=5,
                        executed_at=datetime(2026, 9, 4, 16, 0, 0),
                    ),
                    TaskLog(
                        account_id=account.id,
                        game_role_id=role.id,
                        task_type="checkin",
                        status="risk",
                        message="风控",
                        executed_at=datetime(2026, 9, 5, 16, 0, 0),
                    ),
                ]
            )
            await session.commit()

            with patch("app.api.logs.get_shanghai_date", return_value=date(2026, 9, 10)):
                calendar = await get_reward_calendar(
                    game="hk4e",
                    game_role_id=role.id,
                    current_user=owner,
                    db=session,
                )
                denied = await get_reward_calendar(
                    game="hk4e",
                    game_role_id=foreign_role.id,
                    current_user=owner,
                    db=session,
                )

        self.assertTrue(calendar.catalog_available)
        self.assertEqual(calendar.awards[3].status, "empty")
        self.assertEqual(calendar.awards[4].status, "claimed")
        self.assertEqual(calendar.awards[5].status, "missed")
        self.assertEqual(calendar.awards[9].status, "today")
        self.assertFalse(denied.catalog_available)
        self.assertEqual(denied.awards, [])

    async def test_reward_calendar_without_catalog_returns_empty_awards(self):
        async with await self._new_session() as session:
            user = User(username="reward-empty", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()
            account = MihoyoAccount(user_id=user.id, nickname="账号", cookie_encrypted="encrypted")
            session.add(account)
            await session.flush()
            session.add(
                GameRole(
                    account_id=account.id,
                    game_biz="hkrpg_cn",
                    game_uid="10001",
                    nickname="星",
                    region="prod_gf_cn",
                )
            )
            await session.commit()

            with patch("app.api.logs.get_shanghai_date", return_value=date(2026, 9, 10)):
                calendar = await get_reward_calendar(
                    game=None,
                    game_role_id=None,
                    current_user=user,
                    db=session,
                )

        self.assertFalse(calendar.catalog_available)
        self.assertEqual(calendar.awards, [])
        self.assertEqual(calendar.game, "hkrpg")
        self.assertEqual(calendar.empty_reason, "no_catalog")
        self.assertEqual(len(calendar.games), 1)
        self.assertEqual(calendar.games[0].game, "hkrpg")
        self.assertFalse(calendar.games[0].catalog_available)

    async def test_reward_calendar_defaults_to_family_with_catalog(self):
        async with await self._new_session() as session:
            user = User(username="reward-default", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()
            account = MihoyoAccount(user_id=user.id, nickname="账号", cookie_encrypted="encrypted")
            session.add(account)
            await session.flush()
            genshin = GameRole(
                account_id=account.id,
                game_biz="hk4e_cn",
                game_uid="10001",
                nickname="旅行者",
                region="cn_gf01",
            )
            starrail = GameRole(
                account_id=account.id,
                game_biz="hkrpg_cn",
                game_uid="20001",
                nickname="星",
                region="prod_gf_cn",
            )
            session.add_all([genshin, starrail])
            await session.flush()
            starrail_id = starrail.id
            awards = [{"name": f"奖{i}", "cnt": i, "icon": None} for i in range(1, 32)]
            session.add(
                CheckinRewardCatalog(
                    act_id="e202304121516551",
                    game_family="hkrpg",
                    month="2026-09",
                    awards_json=json.dumps(awards, ensure_ascii=False),
                    fetched_at=datetime(2026, 9, 5, 1, 0, 0),
                )
            )
            await session.commit()

            with patch("app.api.logs.get_shanghai_date", return_value=date(2026, 9, 10)):
                defaulted = await get_reward_calendar(
                    game=None,
                    game_role_id=None,
                    current_user=user,
                    db=session,
                )
                explicit_empty = await get_reward_calendar(
                    game="hk4e",
                    game_role_id=None,
                    current_user=user,
                    db=session,
                )
                dirty = await get_reward_calendar(
                    game="genshin",
                    game_role_id=None,
                    current_user=user,
                    db=session,
                )

        self.assertEqual(defaulted.game, "hkrpg")
        self.assertTrue(defaulted.catalog_available)
        self.assertIsNone(defaulted.empty_reason)
        self.assertEqual([item.game for item in defaulted.games], ["hk4e", "hkrpg"])
        self.assertFalse(defaulted.games[0].catalog_available)
        self.assertTrue(defaulted.games[1].catalog_available)
        self.assertEqual([role.game_role_id for role in defaulted.roles], [starrail_id])

        self.assertEqual(explicit_empty.game, "hk4e")
        self.assertFalse(explicit_empty.catalog_available)
        self.assertEqual(explicit_empty.empty_reason, "no_catalog")
        self.assertEqual([item.game for item in explicit_empty.games], ["hk4e", "hkrpg"])

        self.assertFalse(dirty.catalog_available)
        self.assertEqual(dirty.empty_reason, "no_role")
        self.assertIsNone(dirty.game)
        self.assertEqual([item.game for item in dirty.games], ["hk4e", "hkrpg"])

    async def test_reward_calendar_prefers_claimed_role_in_family(self):
        async with await self._new_session() as session:
            user = User(username="reward-role-pick", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()
            account = MihoyoAccount(user_id=user.id, nickname="账号", cookie_encrypted="encrypted")
            session.add(account)
            await session.flush()
            first = GameRole(
                account_id=account.id,
                game_biz="hkrpg_cn",
                game_uid="20001",
                nickname="一号",
                region="prod_gf_cn",
            )
            second = GameRole(
                account_id=account.id,
                game_biz="hkrpg_cn",
                game_uid="20002",
                nickname="二号",
                region="prod_gf_cn",
            )
            session.add_all([first, second])
            await session.flush()
            second_id = second.id
            session.add(
                TaskLog(
                    account_id=account.id,
                    game_role_id=second.id,
                    task_type="checkin",
                    status="success",
                    message="ok",
                    total_sign_days=1,
                    executed_at=datetime(2026, 9, 4, 16, 0, 0),
                )
            )
            await session.commit()

            with patch("app.api.logs.get_shanghai_date", return_value=date(2026, 9, 10)):
                calendar = await get_reward_calendar(
                    game=None,
                    game_role_id=None,
                    current_user=user,
                    db=session,
                )

        self.assertEqual(calendar.game_role_id, second_id)
        self.assertEqual(len(calendar.roles), 2)

    async def test_notification_fingerprint_includes_reward_fields(self):
        service = NotificationService()
        base = CheckinResult(account_id=1, status="success", message="ok", total_sign_days=12)
        with_reward = base.model_copy(update={"reward_name": "原石", "reward_cnt": 20})
        first = service._build_summary_fingerprint(
            CheckinSummary(total=1, success=1, failed=0, already_signed=0, risk=0, results=[base])
        )
        second = service._build_summary_fingerprint(
            CheckinSummary(total=1, success=1, failed=0, already_signed=0, risk=0, results=[with_reward])
        )
        self.assertNotEqual(first, second)
