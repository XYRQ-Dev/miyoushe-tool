import json
import os
import unittest
from urllib.parse import urlencode
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy import func, select

# 抽卡测试必须与 MySQL-only 运行时使用同一方言初始化 ORM。
# 否则模块导入阶段会重新退回 SQLite 语义，导致这里验证到的唯一键、字段长度与正式运行时不一致。
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
else:
    os.environ.setdefault(
        "DATABASE_URL",
        "mysql+asyncmy://root:root@127.0.0.1:3306/miyoushe_test?charset=utf8mb4",
    )

from app.api.gacha import (
    export_gacha_records_uigf,
    get_gacha_accounts,
    get_gacha_records,
    get_gacha_summary,
    import_gacha_records,
    import_gacha_records_from_account,
    import_gacha_records_from_uigf,
    reset_gacha_records,
    router as gacha_router,
)
from app.models.account import GameRole, MihoyoAccount
from app.models.gacha import GachaImportJob, GachaRecord
from app.models.user import User
from app.schemas.gacha import (
    GachaAccountOption,
    GachaImportFromAccountRequest,
    GachaImportRequest,
    GachaImportResponse,
    GachaImportUIGFRequest,
    GachaRecordResponse,
    GachaResetResponse,
    GachaRoleOption,
    GachaSummaryResponse,
)
from app.services.genshin_authkey import GENSHIN_AUTHKEY_API_URL
from app.utils.crypto import encrypt_cookie, encrypt_text
from tests.mysql_test_case import MySqlIsolatedAsyncioTestCase


class FakeResponse:
    def __init__(self, payload, *, json_error=None):
        self._payload = payload
        self._json_error = json_error

    def raise_for_status(self):
        return None

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class FakeAsyncClient:
    def __init__(self, payloads):
        self._payloads = payloads
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, headers=None):
        index = len(self.calls)
        self.calls.append(
            {
                "method": "GET",
                "url": url,
                "params": params,
                "headers": headers,
                "json": None,
            }
        )
        payload = self._payloads[min(index, len(self._payloads) - 1)]
        return FakeResponse(payload)

    async def post(self, url, params=None, headers=None, json=None):
        index = len(self.calls)
        self.calls.append(
            {
                "method": "POST",
                "url": url,
                "params": params,
                "headers": headers,
                "json": json,
            }
        )
        payload = self._payloads[min(index, len(self._payloads) - 1)]
        return FakeResponse(payload)


class FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value

    def scalar_one(self):
        return self._value


class FakeBeginContext:
    def __init__(self, connection):
        self._connection = connection

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self, connection):
        self._connection = connection

    def begin(self):
        return FakeBeginContext(self._connection)


class FakeAsyncConnection:
    def __init__(self):
        async def _exec_driver_sql(sql, params=None):
            if "GET_LOCK" in sql or "RELEASE_LOCK" in sql:
                return FakeScalarResult(1)
            return None

        self.exec_driver_sql = AsyncMock(side_effect=_exec_driver_sql)
        self.run_sync = AsyncMock()
        self.execute = AsyncMock()


class FakeLockConnection:
    def __init__(self):
        self.exec_driver_sql = AsyncMock(return_value=FakeScalarResult(1))
        self.close = AsyncMock()


class FakeLockEngine:
    def __init__(self, connection):
        self._connection = connection
        self.connect = AsyncMock(return_value=connection)


class DummyGachaDb:
    def __init__(self):
        self.added = []
        self.commit = AsyncMock()
        self.refresh = AsyncMock(side_effect=self._refresh)

    def add(self, obj):
        self.added.append(obj)

    async def _refresh(self, obj):
        obj.id = 9001


class GachaContractTests(unittest.TestCase):
    def _build_genshin_import_url(self, *, game_uid: str | None = None) -> str:
        params = {
            "authkey": "test-key",
            "authkey_ver": "1",
            "sign_type": "2",
            "lang": "zh-cn",
            "gacha_type": "301",
        }
        if game_uid is not None:
            params["game_uid"] = game_uid
        return (
            "https://public-operation-hk4e.mihoyo.com/gacha_info/api/getGachaLog?"
            f"{urlencode(params)}"
        )

    def _build_starrail_import_url(
        self,
        *,
        game_uid: str | None = None,
        gacha_type: str | None = None,
    ) -> str:
        params = {
            "authkey": "test-key",
            "authkey_ver": "1",
            "sign_type": "2",
            "auth_appid": "webview_gacha",
            "lang": "zh-cn",
            "game_biz": "hkrpg_cn",
        }
        if game_uid is not None:
            params["game_uid"] = game_uid
        if gacha_type is not None:
            params["gacha_type"] = gacha_type
        return (
            "https://public-operation-hkrpg.mihoyo.com/common/gacha_record/api/getGachaLog?"
            f"{urlencode(params)}"
        )

    def _build_uigf_payload(self) -> dict:
        return {
            "info": {
                "export_timestamp": 1710000000,
                "export_app": "test-suite",
                "export_app_version": "1.0.0",
                "version": "v4.2",
            },
            "hk4e": [
                {
                    "uid": "10001",
                    "timezone": 8,
                    "lang": "zh-cn",
                    "list": [
                        {
                            "uigf_gacha_type": "301",
                            "gacha_type": "301",
                            "item_id": "",
                            "count": "1",
                            "time": "2026-03-18 12:00:00",
                            "name": "刻晴",
                            "item_type": "角色",
                            "rank_type": "5",
                            "id": "5000001",
                        }
                    ],
                },
                {
                    "uid": "10002",
                    "timezone": 8,
                    "lang": "zh-cn",
                    "list": [
                        {
                            "uigf_gacha_type": "301",
                            "gacha_type": "301",
                            "item_id": "",
                            "count": "1",
                            "time": "2026-03-18 11:59:00",
                            "name": "迪卢克",
                            "item_type": "角色",
                            "rank_type": "5",
                            "id": "5000002",
                        }
                    ],
                },
            ],
        }

    def test_models_and_schemas_lock_game_uid_contract(self):
        record_constraint = next(
            constraint
            for constraint in GachaRecord.__table__.constraints
            if getattr(constraint, "name", "") == "uq_gacha_record_account_game_uid_record"
        )

        self.assertTrue(hasattr(GachaImportJob, "game_uid"))
        self.assertEqual(
            list(record_constraint.columns.keys()),
            ["account_id", "game", "game_uid", "record_id"],
        )
        self.assertIn("game_uid", GachaImportResponse.model_fields)
        self.assertIn("game_uid", GachaSummaryResponse.model_fields)
        self.assertIn("game_uid", GachaRecordResponse.model_fields)
        self.assertIn("game_uid", GachaResetResponse.model_fields)
        self.assertTrue(issubclass(GachaRoleOption, object))
        self.assertIn("gacha_roles", GachaAccountOption.model_fields)

    def test_request_models_require_game_uid(self):
        with self.assertRaises(ValidationError):
            GachaImportRequest(
                account_id=1,
                game="genshin",
                import_url=self._build_genshin_import_url(game_uid="10001"),
            )

        with self.assertRaises(ValidationError):
            GachaImportFromAccountRequest(
                account_id=1,
                game="genshin",
            )

        with self.assertRaises(ValidationError):
            GachaImportUIGFRequest(
                account_id=1,
                game="genshin",
                source_name="backup.uigf.json",
                uigf_json=self._build_uigf_payload(),
            )

    def test_query_routes_require_game_uid_query_param(self):
        route_map = {
            route.path: route
            for route in gacha_router.routes
            if isinstance(route, APIRoute)
        }

        for path in (
            "/api/gacha/summary",
            "/api/gacha/records",
            "/api/gacha/export-uigf",
            "/api/gacha/reset",
        ):
            with self.subTest(path=path):
                game_uid_param = next(
                    (
                        param
                        for param in route_map[path].dependant.query_params
                        if param.name == "game_uid"
                    ),
                    None,
                )
                self.assertIsNotNone(game_uid_param)
                self.assertTrue(game_uid_param.required)


class MySqlIsolatedAsyncioTestCaseContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_reset_schema_recreates_tables_once_when_opted_in(self):
        class RebuildCase(MySqlIsolatedAsyncioTestCase):
            recreate_schema = True

            def runTest(self):
                return None

        case = RebuildCase(methodName="runTest")
        conn = FakeAsyncConnection()
        case.engine = FakeEngine(conn)

        await case._reset_schema()

        run_sync_call_names = [call.args[0].__name__ for call in conn.run_sync.await_args_list]
        self.assertEqual(run_sync_call_names, ["drop_all", "create_all"])
        conn.execute.assert_not_awaited()
        sql_calls = [call.args[0] for call in conn.exec_driver_sql.await_args_list]
        self.assertEqual(sql_calls, ["SET FOREIGN_KEY_CHECKS = 0", "SET FOREIGN_KEY_CHECKS = 1"])

    async def test_database_lock_wraps_each_mysql_test_case(self):
        class DummyCase(MySqlIsolatedAsyncioTestCase):
            def runTest(self):
                return None

        case = DummyCase(methodName="runTest")
        lock_connection = FakeLockConnection()
        case.engine = FakeLockEngine(lock_connection)

        await case._acquire_database_lock()
        self.assertIn("SELECT GET_LOCK", lock_connection.exec_driver_sql.await_args.args[0])
        self.assertIn(case._lock_name, lock_connection.exec_driver_sql.await_args.args[0])
        self.assertIs(case._lock_connection, lock_connection)

        await case._release_database_lock()
        sql_calls = [call.args[0] for call in lock_connection.exec_driver_sql.await_args_list]
        self.assertIn("SELECT RELEASE_LOCK", sql_calls[-1])
        lock_connection.close.assert_awaited_once()
        self.assertIsNone(case._lock_connection)


class GachaRateLimitTests(unittest.IsolatedAsyncioTestCase):
    def _build_genshin_import_url(self) -> str:
        return GachaContractTests()._build_genshin_import_url(game_uid="10001")

    def _build_starrail_import_url(self, *, gacha_type: str | None = None) -> str:
        return GachaContractTests()._build_starrail_import_url(game_uid="80001", gacha_type=gacha_type)

    async def test_import_records_retries_rate_limit_then_succeeds(self):
        from app.services.gacha import GachaService

        db = DummyGachaDb()
        service = GachaService(db)
        service._save_page_records = AsyncMock(return_value=(20, 0))
        account = type("Account", (), {"id": 1})()
        page_items = [
            {
                "id": "1770132000002009065",
                "name": "刻晴",
                "item_type": "角色",
                "rank_type": "5",
                "gacha_type": "301",
                "time": "2026-03-18 12:00:00",
            }
        ] * 20
        fake_client = FakeAsyncClient(
            [
                {"retcode": 0, "message": "OK", "data": {"list": page_items}},
                {"retcode": -100, "message": "visit too frequently", "data": None},
                {"retcode": 0, "message": "OK", "data": {"list": []}},
            ]
        )
        sleep_mock = AsyncMock()

        with (
            patch("app.services.gacha.httpx.AsyncClient", return_value=fake_client),
            patch("app.services.gacha.asyncio.sleep", sleep_mock),
            patch("app.services.gacha.random.randint", side_effect=[1200, 2500]),
        ):
            response = await service.import_records(
                account=account,
                game="genshin",
                game_uid="10001",
                import_url=self._build_genshin_import_url(),
            )

        self.assertEqual(response.inserted_count, 20)
        self.assertEqual(len(fake_client.calls), 3)
        self.assertEqual(fake_client.calls[1]["params"]["page"], "2")
        self.assertEqual(fake_client.calls[2]["params"]["page"], "2")
        self.assertEqual(sleep_mock.await_count, 2)
        self.assertEqual(sleep_mock.await_args_list[0].args[0], 1.2)
        self.assertEqual(sleep_mock.await_args_list[1].args[0], 2.5)
        db.commit.assert_awaited_once()

    async def test_import_records_fails_after_rate_limit_retries_exhausted_without_commit(self):
        from app.services.gacha import GachaService

        db = DummyGachaDb()
        service = GachaService(db)
        service._save_page_records = AsyncMock()
        account = type("Account", (), {"id": 1})()
        fake_client = FakeAsyncClient(
            [
                {"retcode": -100, "message": "visit too frequently", "data": None},
                {"retcode": -100, "message": "visit too frequently", "data": None},
                {"retcode": -100, "message": "visit too frequently", "data": None},
                {"retcode": -100, "message": "visit too frequently", "data": None},
            ]
        )
        sleep_mock = AsyncMock()

        with (
            patch("app.services.gacha.httpx.AsyncClient", return_value=fake_client),
            patch("app.services.gacha.asyncio.sleep", sleep_mock),
            patch("app.services.gacha.random.randint", side_effect=[2200, 4500, 7500]),
        ):
            with self.assertRaises(HTTPException) as context:
                await service.import_records(
                    account=account,
                    game="genshin",
                    game_uid="10001",
                    import_url=self._build_genshin_import_url(),
                )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "抽卡记录导入失败：访问过于频繁，请稍后重试")
        self.assertEqual(len(fake_client.calls), 4)
        self.assertEqual(sleep_mock.await_count, 3)
        db.commit.assert_not_awaited()
        service._save_page_records.assert_not_called()

    async def test_import_records_scans_all_starrail_pools_when_gacha_type_missing(self):
        from app.services.gacha import GachaService

        db = DummyGachaDb()
        service = GachaService(db)
        service._save_page_records = AsyncMock(side_effect=[(5, 0), (5, 0), (5, 0)])
        account = type("Account", (), {"id": 1})()
        starrail_items = lambda prefix, pool: [
            {
                "id": f"{prefix}{index}",
                "name": "测试角色",
                "item_type": "角色",
                "rank_type": "5",
                "gacha_type": pool,
                "time": f"2026-03-18 12:00:0{index}",
            }
            for index in range(5)
        ]
        fake_client = FakeAsyncClient(
            [
                {"retcode": 0, "message": "OK", "data": {"list": starrail_items("1", "1")}},
                {"retcode": 0, "message": "OK", "data": {"list": []}},
                {"retcode": 0, "message": "OK", "data": {"list": starrail_items("11", "11")}},
                {"retcode": 0, "message": "OK", "data": {"list": starrail_items("12", "12")}},
            ]
        )
        sleep_mock = AsyncMock()

        with (
            patch("app.services.gacha.httpx.AsyncClient", return_value=fake_client),
            patch("app.services.gacha.asyncio.sleep", sleep_mock),
            patch("app.services.gacha.random.randint", return_value=1100),
        ):
            response = await service.import_records(
                account=account,
                game="starrail",
                game_uid="80001",
                import_url=self._build_starrail_import_url(),
            )

        self.assertEqual(response.inserted_count, 15)
        self.assertEqual(response.fetched_count, 15)
        self.assertEqual(response.source_url_masked.count("gacha_type=auto"), 1)
        self.assertEqual([call["params"]["gacha_type"] for call in fake_client.calls], ["1", "2", "11", "12"])
        self.assertEqual(service._save_page_records.await_count, 3)
        self.assertEqual(sleep_mock.await_count, 0)
        db.commit.assert_awaited_once()

    async def test_import_records_keeps_single_starrail_pool_when_gacha_type_present(self):
        from app.services.gacha import GachaService

        db = DummyGachaDb()
        service = GachaService(db)
        service._save_page_records = AsyncMock(return_value=(5, 0))
        account = type("Account", (), {"id": 1})()
        fake_client = FakeAsyncClient(
            [
                {
                    "retcode": 0,
                    "message": "OK",
                    "data": {
                        "list": [
                            {
                                "id": f"11-{index}",
                                "name": "希儿",
                                "item_type": "角色",
                                "rank_type": "5",
                                "gacha_type": "11",
                                "time": f"2026-03-18 12:00:0{index}",
                            }
                            for index in range(5)
                        ]
                    },
                }
            ]
        )

        with patch("app.services.gacha.httpx.AsyncClient", return_value=fake_client):
            response = await service.import_records(
                account=account,
                game="starrail",
                game_uid="80001",
                import_url=self._build_starrail_import_url(gacha_type="11"),
            )

        self.assertEqual(response.inserted_count, 5)
        self.assertEqual(len(fake_client.calls), 1)
        self.assertEqual(fake_client.calls[0]["params"]["gacha_type"], "11")
        self.assertIn("gacha_type=11", response.source_url_masked)
        db.commit.assert_awaited_once()

    async def test_import_records_does_not_commit_partial_starrail_results_when_later_pool_fails(self):
        from app.services.gacha import GachaService

        db = DummyGachaDb()
        service = GachaService(db)
        service._save_page_records = AsyncMock(return_value=(5, 0))
        account = type("Account", (), {"id": 1})()
        fake_client = FakeAsyncClient(
            [
                {
                    "retcode": 0,
                    "message": "OK",
                    "data": {
                        "list": [
                            {
                                "id": f"1-{index}",
                                "name": "测试角色",
                                "item_type": "角色",
                                "rank_type": "5",
                                "gacha_type": "1",
                                "time": f"2026-03-18 12:00:0{index}",
                            }
                            for index in range(5)
                        ]
                    },
                },
                {"retcode": -100, "message": "visit too frequently", "data": None},
                {"retcode": -100, "message": "visit too frequently", "data": None},
                {"retcode": -100, "message": "visit too frequently", "data": None},
                {"retcode": -100, "message": "visit too frequently", "data": None},
            ]
        )
        sleep_mock = AsyncMock()

        with (
            patch("app.services.gacha.httpx.AsyncClient", return_value=fake_client),
            patch("app.services.gacha.asyncio.sleep", sleep_mock),
            patch("app.services.gacha.random.randint", side_effect=[2200, 4500, 7500]),
        ):
            with self.assertRaises(HTTPException) as context:
                await service.import_records(
                    account=account,
                    game="starrail",
                    game_uid="80001",
                    import_url=self._build_starrail_import_url(),
                )

        self.assertEqual(context.exception.detail, "抽卡记录导入失败：访问过于频繁，请稍后重试")
        self.assertEqual(service._save_page_records.await_count, 1)
        db.commit.assert_not_awaited()


class GachaTests(MySqlIsolatedAsyncioTestCase):
    # 抽卡模型这轮刚切到 `game_uid` 三维唯一键。
    # 这里要求测试基座直接走 drop/create，一次性把旧 schema 残留清空；
    # 否则历史库里若还留着旧唯一键，`create_all()` 不会报错，但后续断言会在错误结构上运行。
    recreate_schema = True

    async def _new_session(self):
        return self.session_factory()

    async def _seed_account_with_roles(self, role_specs=None):
        role_specs = role_specs or [
            {
                "game_biz": "hk4e_cn",
                "game_uid": "10001",
                "nickname": "旅行者",
                "region": "cn_gf01",
            }
        ]
        async with await self._new_session() as session:
            user = User(username="gacha-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()

            account = MihoyoAccount(user_id=user.id, nickname="测试账号", mihoyo_uid="123456")
            session.add(account)
            await session.flush()

            roles = []
            for index, role_spec in enumerate(role_specs, start=1):
                role = GameRole(
                    account_id=account.id,
                    game_biz=role_spec["game_biz"],
                    game_uid=role_spec["game_uid"],
                    nickname=role_spec.get("nickname") or f"角色{index}",
                    region=role_spec.get("region"),
                    level=role_spec.get("level"),
                    is_enabled=role_spec.get("is_enabled", True),
                )
                session.add(role)
                roles.append(role)

            await session.commit()
            return user, account, roles

    async def _seed_high_privilege_account_with_roles(self, role_specs=None):
        # 新的 authkey 主链会先校验可解密的根凭据，再决定是否向上游发起 POST。
        # 成功路径测试若仍沿用“裸账号”夹具，断言会提前死在凭据校验上，无法真正锁住协议是否对齐 HuTao 主链。
        user, account, roles = await self._seed_account_with_roles(role_specs)
        async with await self._new_session() as session:
            managed = await session.get(MihoyoAccount, account.id)
            managed.stoken_encrypted = encrypt_text("v2_test_stoken")
            managed.stuid = "10001"
            managed.mid = "mid-10001"
            managed.credential_status = "valid"
            await session.commit()
            await session.refresh(managed)
        return user, managed, roles

    def _build_genshin_import_url(self, *, game_uid: str | None = None) -> str:
        return GachaContractTests()._build_genshin_import_url(game_uid=game_uid)

    def _build_uigf_payload(self) -> dict:
        return GachaContractTests()._build_uigf_payload()

    async def test_list_supported_accounts_returns_gacha_roles(self):
        user, _account, _roles = await self._seed_account_with_roles(
            [
                {
                    "game_biz": "hk4e_cn",
                    "game_uid": "10001",
                    "nickname": "旅行者",
                    "region": "cn_gf01",
                },
                {
                    "game_biz": "hk4e_os",
                    "game_uid": "10002",
                    "nickname": "旅行者小号",
                    "region": "os_usa",
                },
                {
                    "game_biz": "hkrpg_cn",
                    "game_uid": "80001",
                    "nickname": "开拓者",
                    "region": "prod_gf_cn",
                },
            ]
        )

        async with await self._new_session() as session:
            response = await get_gacha_accounts(current_user=user, db=session)

        self.assertEqual(response.total, 1)
        self.assertEqual(len(response.accounts[0].gacha_roles), 3)
        self.assertEqual(
            {(role.game, role.game_uid) for role in response.accounts[0].gacha_roles},
            {("genshin", "10001"), ("genshin", "10002"), ("starrail", "80001")},
        )

    async def test_import_deduplicates_within_same_uid_but_not_across_other_uid(self):
        payload = {
            "retcode": 0,
            "message": "OK",
            "data": {
                "list": [
                    {
                        "id": "1000001",
                        "name": "刻晴",
                        "item_type": "角色",
                        "rank_type": "5",
                        "gacha_type": "301",
                        "time": "2026-03-18 12:00:00",
                    }
                ]
            },
        }
        user, account, _roles = await self._seed_account_with_roles(
            [
                {"game_biz": "hk4e_cn", "game_uid": "10001", "nickname": "主号", "region": "cn_gf01"},
                {"game_biz": "hk4e_cn", "game_uid": "10002", "nickname": "小号", "region": "cn_gf01"},
            ]
        )

        async with await self._new_session() as session:
            with patch("app.services.gacha.httpx.AsyncClient", return_value=FakeAsyncClient([payload])):
                first = await import_gacha_records(
                    GachaImportRequest(
                        account_id=account.id,
                        game="genshin",
                        game_uid="10001",
                        import_url=self._build_genshin_import_url(game_uid="10001"),
                    ),
                    current_user=user,
                    db=session,
                )

            with patch("app.services.gacha.httpx.AsyncClient", return_value=FakeAsyncClient([payload])):
                second = await import_gacha_records(
                    GachaImportRequest(
                        account_id=account.id,
                        game="genshin",
                        game_uid="10002",
                        import_url=self._build_genshin_import_url(game_uid="10002"),
                    ),
                    current_user=user,
                    db=session,
                )

            first_uid_total = (
                await session.execute(
                    select(func.count(GachaRecord.id)).where(
                        GachaRecord.account_id == account.id,
                        GachaRecord.game == "genshin",
                        GachaRecord.game_uid == "10001",
                    )
                )
            ).scalar_one()
            second_uid_total = (
                await session.execute(
                    select(func.count(GachaRecord.id)).where(
                        GachaRecord.account_id == account.id,
                        GachaRecord.game == "genshin",
                        GachaRecord.game_uid == "10002",
                    )
                )
            ).scalar_one()

        self.assertEqual(first.inserted_count, 1)
        self.assertEqual(first.duplicate_count, 0)
        self.assertEqual(second.inserted_count, 1)
        self.assertEqual(second.duplicate_count, 0)
        self.assertEqual(first_uid_total, 1)
        self.assertEqual(second_uid_total, 1)

    async def test_import_rejects_url_uid_mismatch(self):
        user, account, _roles = await self._seed_account_with_roles(
            [{"game_biz": "hk4e_cn", "game_uid": "10001", "nickname": "主号", "region": "cn_gf01"}]
        )

        async with await self._new_session() as session:
            with self.assertRaises(HTTPException) as context:
                await import_gacha_records(
                    GachaImportRequest(
                        account_id=account.id,
                        game="genshin",
                        game_uid="10001",
                        import_url=self._build_genshin_import_url(game_uid="10002"),
                    ),
                    current_user=user,
                    db=session,
                )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("UID", context.exception.detail)

    async def test_import_without_url_uid_uses_requested_game_uid_for_storage(self):
        payload = {
            "retcode": 0,
            "message": "OK",
            "data": {
                "list": [
                    {
                        "id": "1200001",
                        "name": "迪卢克",
                        "item_type": "角色",
                        "rank_type": "5",
                        "gacha_type": "301",
                        "time": "2026-03-18 12:00:00",
                    }
                ]
            },
        }
        user, account, _roles = await self._seed_account_with_roles(
            [
                {"game_biz": "hk4e_cn", "game_uid": "10001", "nickname": "主号", "region": "cn_gf01"},
                {"game_biz": "hk4e_cn", "game_uid": "10002", "nickname": "小号", "region": "cn_gf01"},
            ]
        )

        async with await self._new_session() as session:
            with patch("app.services.gacha.httpx.AsyncClient", return_value=FakeAsyncClient([payload])):
                response = await import_gacha_records(
                    GachaImportRequest(
                        account_id=account.id,
                        game="genshin",
                        game_uid="10002",
                        import_url=self._build_genshin_import_url(),
                    ),
                    current_user=user,
                    db=session,
                )

            stored = (
                await session.execute(
                    select(GachaRecord).where(
                        GachaRecord.account_id == account.id,
                        GachaRecord.game == "genshin",
                        GachaRecord.record_id == "1200001",
                    )
                )
            ).scalar_one()

        self.assertEqual(response.game_uid, "10002")
        self.assertEqual(stored.game_uid, "10002")

    async def test_get_owned_account_for_game_requires_matching_game_uid_role(self):
        user, account, _roles = await self._seed_account_with_roles(
            [{"game_biz": "hk4e_cn", "game_uid": "10001", "nickname": "主号", "region": "cn_gf01"}]
        )
        from app.services.gacha import GachaService

        async with await self._new_session() as session:
            service = GachaService(session)
            with self.assertRaises(HTTPException) as context:
                await service.get_owned_account_for_game(account.id, user.id, "genshin", "10002")

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "该账号未开通所选角色的抽卡记录能力")

    async def test_import_from_account_posts_json_using_root_stoken_contract(self):
        user, account, _roles = await self._seed_high_privilege_account_with_roles(
            [
                {"game_biz": "hk4e_cn", "game_uid": "10001", "nickname": "国服", "region": "cn_gf01"},
                {"game_biz": "hk4e_os", "game_uid": "10002", "nickname": "国际服", "region": "os_usa"},
            ]
        )
        authkey_client = FakeAsyncClient(
            [
                {
                    "retcode": 0,
                    "message": "OK",
                    "data": {
                        "authkey": "generated-authkey",
                        "authkey_ver": 1,
                        "sign_type": 2,
                    },
                }
            ]
        )
        gacha_client = FakeAsyncClient(
            [
                {
                    "retcode": 0,
                    "message": "OK",
                    "data": {
                        "list": [
                            {
                                "id": "1300001",
                                "name": "刻晴",
                                "item_type": "角色",
                                "rank_type": "5",
                                "gacha_type": "301",
                                "time": "2026-03-18 12:00:00",
                            }
                        ]
                    },
                }
            ]
        )

        async with await self._new_session() as session:
            with (
                patch("app.services.genshin_authkey.generate_device_id", return_value="device-id-001"),
                patch("app.services.genshin_authkey.generate_cn_gen1_ds_lk2", return_value="123456,abcdef,sign"),
                patch("app.services.genshin_authkey.httpx.AsyncClient", return_value=authkey_client),
                patch("app.services.gacha.httpx.AsyncClient", return_value=gacha_client),
            ):
                response = await import_gacha_records_from_account(
                    GachaImportFromAccountRequest(
                        account_id=account.id,
                        game="genshin",
                        game_uid="10001",
                    ),
                    current_user=user,
                    db=session,
                )

        self.assertEqual(response.inserted_count, 1)
        self.assertEqual(authkey_client.calls[0]["method"], "POST")
        self.assertEqual(authkey_client.calls[0]["url"], GENSHIN_AUTHKEY_API_URL)
        self.assertEqual(
            authkey_client.calls[0]["json"],
            {
                "auth_appid": "webview_gacha",
                "game_biz": "hk4e_cn",
                "game_uid": 10001,
                "region": "cn_gf01",
            },
        )
        self.assertEqual(authkey_client.calls[0]["headers"]["Cookie"], "mid=mid-10001; stoken=v2_test_stoken; stuid=10001")
        self.assertEqual(authkey_client.calls[0]["headers"]["Referer"], "https://app.mihoyo.com")
        self.assertEqual(authkey_client.calls[0]["headers"]["x-rpc-app_version"], "2.95.1")
        self.assertEqual(authkey_client.calls[0]["headers"]["x-rpc-device_id"], "device-id-001")
        self.assertEqual(authkey_client.calls[0]["headers"]["DS"], "123456,abcdef,sign")
        self.assertNotIn("x-rpc-device_fp", authkey_client.calls[0]["headers"])
        self.assertEqual(gacha_client.calls[0]["method"], "GET")
        self.assertEqual(gacha_client.calls[0]["params"]["authkey"], "generated-authkey")

    async def test_import_from_account_falls_back_region_only_for_hk4e_cn_role(self):
        user, account, _roles = await self._seed_high_privilege_account_with_roles(
            [{"game_biz": "hk4e_cn", "game_uid": "10001", "nickname": "国服缺区服", "region": None}]
        )
        authkey_client = FakeAsyncClient(
            [
                {
                    "retcode": 0,
                    "message": "OK",
                    "data": {
                        "authkey": "generated-authkey",
                        "authkey_ver": 1,
                        "sign_type": 2,
                    },
                }
            ]
        )
        gacha_client = FakeAsyncClient(
            [
                {
                    "retcode": 0,
                    "message": "OK",
                    "data": {"list": []},
                }
            ]
        )

        async with await self._new_session() as session:
            with (
                patch("app.services.genshin_authkey.httpx.AsyncClient", return_value=authkey_client),
                patch("app.services.gacha.httpx.AsyncClient", return_value=gacha_client),
            ):
                response = await import_gacha_records_from_account(
                    GachaImportFromAccountRequest(
                        account_id=account.id,
                        game="genshin",
                        game_uid="10001",
                    ),
                    current_user=user,
                    db=session,
                )

        self.assertEqual(response.inserted_count, 0)
        self.assertEqual(
            authkey_client.calls[0]["json"],
            {
                "auth_appid": "webview_gacha",
                "game_biz": "hk4e_cn",
                "game_uid": 10001,
                "region": "cn_gf01",
            },
        )

    async def test_import_from_account_requires_high_privilege_root_credentials(self):
        # 这里故意只给一个“看起来还能用”的工作 Cookie，却不给可解密的高权限根凭据。
        # 若后续实现回退成“工作 Cookie 能用就继续试”，这个用例会把协议降级直接打红。
        user, account, _roles = await self._seed_account_with_roles(
            [{"game_biz": "hk4e_cn", "game_uid": "10001", "nickname": "国服", "region": "cn_gf01"}]
        )
        async with await self._new_session() as session:
            managed = await session.get(MihoyoAccount, account.id)
            managed.cookie_encrypted = encrypt_cookie("ltuid=10001; cookie_token=legacy-cookie-token")
            managed.cookie_status = "valid"
            await session.commit()

        async with await self._new_session() as session:
            with self.assertRaises(HTTPException) as context:
                await import_gacha_records_from_account(
                    GachaImportFromAccountRequest(
                        account_id=account.id,
                        game="genshin",
                        game_uid="10001",
                    ),
                    current_user=user,
                    db=session,
                )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "高权限根凭据已失效，请重新扫码升级高权限登录")

    async def test_import_from_account_rejects_oversea_role_for_genshin_authkey(self):
        # HuTao 主链对国际服 `SToken -> authkey` 直接判不支持。
        # 这里必须在本地前置拒绝，不能继续“先打上游再看返回值”，否则错误语义会重新变模糊。
        user, account, _roles = await self._seed_high_privilege_account_with_roles(
            [{"game_biz": "hk4e_os", "game_uid": "10002", "nickname": "国际服", "region": "os_usa"}]
        )
        fake_client = FakeAsyncClient(
            [
                {
                    "retcode": 0,
                    "message": "OK",
                    "data": {
                        "authkey": "should-not-be-used",
                        "authkey_ver": 1,
                        "sign_type": 2,
                    },
                }
            ]
        )

        async with await self._new_session() as session:
            with (
                patch("app.services.genshin_authkey.httpx.AsyncClient", return_value=fake_client),
            ):
                with self.assertRaises(HTTPException) as context:
                    await import_gacha_records_from_account(
                        GachaImportFromAccountRequest(
                            account_id=account.id,
                            game="genshin",
                            game_uid="10002",
                        ),
                        current_user=user,
                        db=session,
                    )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "当前仅支持原神国服账号自动导入")
        self.assertEqual(fake_client.calls, [])

    async def test_import_from_account_maps_upstream_login_expired_to_reauth_message(self):
        user, account, _roles = await self._seed_high_privilege_account_with_roles(
            [{"game_biz": "hk4e_cn", "game_uid": "10001", "nickname": "国服", "region": "cn_gf01"}]
        )
        authkey_client = FakeAsyncClient(
            [
                {
                    "retcode": -100,
                    "message": "登录状态失效，请重新登录",
                    "data": None,
                }
            ]
        )

        async with await self._new_session() as session:
            with (
                patch("app.services.genshin_authkey.generate_device_id", return_value="device-id-001"),
                patch("app.services.genshin_authkey.generate_cn_gen1_ds_lk2", return_value="123456,abcdef,sign"),
                patch("app.services.genshin_authkey.httpx.AsyncClient", return_value=authkey_client),
            ):
                with self.assertRaises(HTTPException) as context:
                    await import_gacha_records_from_account(
                        GachaImportFromAccountRequest(
                            account_id=account.id,
                            game="genshin",
                            game_uid="10001",
                        ),
                        current_user=user,
                        db=session,
                    )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "原神 authkey 生成失败：米游社登录状态已失效，请重新扫码登录")

    async def test_import_uigf_only_imports_requested_uid_and_rejects_missing_uid(self):
        user, account, _roles = await self._seed_account_with_roles(
            [
                {"game_biz": "hk4e_cn", "game_uid": "10001", "nickname": "主号", "region": "cn_gf01"},
                {"game_biz": "hk4e_cn", "game_uid": "10002", "nickname": "小号", "region": "cn_gf01"},
                # 这里额外放一个账号真实拥有、但 UIGF 文件并未包含的 UID，
                # 用来锁定“账号校验通过后，仍要继续报文件缺少目标 UID”的分支。
                # 如果直接传完全不存在于账号下的 UID，接口会更早在账号/角色权限校验处失败，
                # 该测试就不再是在验证 UIGF 解析边界，而是误测了前置鉴权。
                {"game_biz": "hk4e_cn", "game_uid": "10003", "nickname": "缺档号", "region": "cn_gf01"},
            ]
        )

        async with await self._new_session() as session:
            imported = await import_gacha_records_from_uigf(
                GachaImportUIGFRequest(
                    account_id=account.id,
                    game="genshin",
                    game_uid="10002",
                    source_name="backup.uigf.json",
                    uigf_json=self._build_uigf_payload(),
                ),
                current_user=user,
                db=session,
            )

            stored_ids = (
                await session.execute(
                    select(GachaRecord.record_id).where(
                        GachaRecord.account_id == account.id,
                        GachaRecord.game == "genshin",
                        GachaRecord.game_uid == "10002",
                    )
                )
            ).scalars().all()

            with self.assertRaises(HTTPException) as context:
                await import_gacha_records_from_uigf(
                    GachaImportUIGFRequest(
                        account_id=account.id,
                        game="genshin",
                        game_uid="10003",
                        source_name="backup.uigf.json",
                        uigf_json=self._build_uigf_payload(),
                    ),
                    current_user=user,
                    db=session,
                )

        self.assertEqual(imported.inserted_count, 1)
        self.assertEqual(imported.game_uid, "10002")
        self.assertEqual(stored_ids, ["5000002"])
        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "UIGF 文件中不包含所选 UID 的记录")

    async def test_summary_records_export_and_reset_only_affect_selected_uid(self):
        user, account, _roles = await self._seed_account_with_roles(
            [
                {"game_biz": "hk4e_cn", "game_uid": "10001", "nickname": "主号", "region": "cn_gf01"},
                {"game_biz": "hk4e_cn", "game_uid": "10002", "nickname": "小号", "region": "cn_gf01"},
            ]
        )

        async with await self._new_session() as session:
            session.add_all(
                [
                    GachaRecord(
                        account_id=account.id,
                        game="genshin",
                        game_uid="10001",
                        record_id="2000001",
                        pool_type="301",
                        pool_name="角色活动祈愿",
                        item_name="刻晴",
                        item_type="角色",
                        rank_type="5",
                        time_text="2026-03-18 12:00:00",
                    ),
                    GachaRecord(
                        account_id=account.id,
                        game="genshin",
                        game_uid="10002",
                        record_id="2000002",
                        pool_type="301",
                        pool_name="角色活动祈愿",
                        item_name="迪卢克",
                        item_type="角色",
                        rank_type="5",
                        time_text="2026-03-18 11:00:00",
                    ),
                    GachaImportJob(
                        account_id=account.id,
                        game="genshin",
                        game_uid="10001",
                        source_url_masked="uigf://uid-10001.json",
                        status="success",
                        fetched_count=1,
                        inserted_count=1,
                        duplicate_count=0,
                        message="导入完成",
                    ),
                    GachaImportJob(
                        account_id=account.id,
                        game="genshin",
                        game_uid="10002",
                        source_url_masked="uigf://uid-10002.json",
                        status="success",
                        fetched_count=1,
                        inserted_count=1,
                        duplicate_count=0,
                        message="导入完成",
                    ),
                ]
            )
            await session.commit()

            summary = await get_gacha_summary(
                account_id=account.id,
                game="genshin",
                game_uid="10001",
                current_user=user,
                db=session,
            )
            records = await get_gacha_records(
                account_id=account.id,
                game="genshin",
                game_uid="10001",
                pool_type=None,
                page=1,
                page_size=20,
                current_user=user,
                db=session,
            )
            exported = await export_gacha_records_uigf(
                account_id=account.id,
                game="genshin",
                game_uid="10001",
                current_user=user,
                db=session,
            )
            reset_result = await reset_gacha_records(
                account_id=account.id,
                game="genshin",
                game_uid="10001",
                current_user=user,
                db=session,
            )

            remaining_record_ids = (
                await session.execute(
                    select(GachaRecord.record_id).where(
                        GachaRecord.account_id == account.id,
                        GachaRecord.game == "genshin",
                    )
                )
            ).scalars().all()
            remaining_job_uids = (
                await session.execute(
                    select(GachaImportJob.game_uid).where(
                        GachaImportJob.account_id == account.id,
                        GachaImportJob.game == "genshin",
                    )
                )
            ).scalars().all()

        self.assertEqual(summary.game_uid, "10001")
        self.assertEqual(summary.total_count, 1)
        self.assertEqual(records.total, 1)
        self.assertEqual(records.records[0].game_uid, "10001")
        self.assertEqual(exported.game_uid, "10001")
        self.assertEqual(exported.total, 1)
        self.assertEqual(exported.uigf["hk4e"][0]["uid"], "10001")
        self.assertEqual(exported.uigf["hk4e"][0]["list"][0]["id"], "2000001")
        self.assertEqual(reset_result.deleted_records, 1)
        self.assertEqual(reset_result.deleted_import_jobs, 1)
        self.assertEqual(reset_result.game_uid, "10001")
        self.assertEqual(remaining_record_ids, ["2000002"])
        self.assertEqual(remaining_job_uids, ["10002"])

    async def test_import_uigf_accepts_raw_json_text(self):
        user, account, _roles = await self._seed_account_with_roles(
            [{"game_biz": "hkrpg_cn", "game_uid": "80001", "nickname": "开拓者", "region": "prod_gf_cn"}]
        )

        async with await self._new_session() as session:
            response = await import_gacha_records_from_uigf(
                GachaImportUIGFRequest(
                    account_id=account.id,
                    game="starrail",
                    game_uid="80001",
                    source_name="starrail-backup.uigf.json",
                    uigf_json=json.dumps(
                        {
                            "info": {
                                "export_timestamp": 1710000000,
                                "export_app": "test-suite",
                                "export_app_version": "1.0.0",
                                "version": "v4.2",
                            },
                            "hkrpg": [
                                {
                                    "uid": "80001",
                                    "timezone": 8,
                                    "lang": "zh-cn",
                                    "list": [
                                        {
                                            "gacha_id": "2001",
                                            "gacha_type": "11",
                                            "item_id": "",
                                            "count": "1",
                                            "time": "2026-03-18 12:00:00",
                                            "name": "希儿",
                                            "item_type": "角色",
                                            "rank_type": "5",
                                            "id": "5100001",
                                        }
                                    ],
                                }
                            ],
                        }
                    ),
                ),
                current_user=user,
                db=session,
            )

            stored = (
                await session.execute(
                    select(GachaRecord).where(
                        GachaRecord.account_id == account.id,
                        GachaRecord.game == "starrail",
                        GachaRecord.game_uid == "80001",
                        GachaRecord.record_id == "5100001",
                    )
                )
            ).scalar_one()

        self.assertEqual(response.inserted_count, 1)
        self.assertEqual(response.game_uid, "80001")
        self.assertEqual(stored.item_name, "希儿")


if __name__ == "__main__":
    unittest.main()
