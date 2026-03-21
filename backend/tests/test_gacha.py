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
        self.calls.append({"url": url, "params": params, "headers": headers})
        payload = self._payloads[min(index, len(self._payloads) - 1)]
        return FakeResponse(payload)


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


class GachaTests(MySqlIsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self._rebuild_schema()

    async def _rebuild_schema(self) -> None:
        async with self.engine.begin() as conn:
            # 抽卡模型本轮直接切换了唯一键与字段集合。
            # 这里显式重建表结构，是为了避免测试库残留旧 schema 时 `create_all()` 静默跳过，
            # 最终把“库结构没更新”误判成业务逻辑回归。
            await conn.run_sync(self._drop_and_create_all)

    @staticmethod
    def _drop_and_create_all(sync_conn) -> None:
        from app.database import Base

        Base.metadata.drop_all(sync_conn)
        Base.metadata.create_all(sync_conn)

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

    async def test_import_from_account_uses_requested_game_uid_role(self):
        user, account, _roles = await self._seed_account_with_roles(
            [
                {"game_biz": "hk4e_cn", "game_uid": "10001", "nickname": "国服", "region": "cn_gf01"},
                {"game_biz": "hk4e_os", "game_uid": "10002", "nickname": "国际服", "region": "os_usa"},
            ]
        )
        fake_client = FakeAsyncClient(
            [
                {
                    "retcode": 0,
                    "message": "OK",
                    "data": {
                        "authkey": "generated-authkey",
                        "authkey_ver": 1,
                        "sign_type": 2,
                    },
                },
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
                },
            ]
        )

        async with await self._new_session() as session:
            with (
                patch(
                    "app.services.gacha.AccountCredentialService.ensure_work_cookie",
                    new=AsyncMock(return_value={"state": "valid", "message": "ok", "cookie": "ltoken_v2=test"}),
                ),
                patch("app.services.gacha.httpx.AsyncClient", return_value=fake_client),
            ):
                response = await import_gacha_records_from_account(
                    GachaImportFromAccountRequest(
                        account_id=account.id,
                        game="genshin",
                        game_uid="10002",
                    ),
                    current_user=user,
                    db=session,
                )

        self.assertEqual(response.inserted_count, 1)
        self.assertEqual(fake_client.calls[0]["params"]["game_uid"], "10002")
        self.assertEqual(fake_client.calls[0]["params"]["game_biz"], "hk4e_os")

    async def test_import_uigf_only_imports_requested_uid_and_rejects_missing_uid(self):
        user, account, _roles = await self._seed_account_with_roles(
            [
                {"game_biz": "hk4e_cn", "game_uid": "10001", "nickname": "主号", "region": "cn_gf01"},
                {"game_biz": "hk4e_cn", "game_uid": "10002", "nickname": "小号", "region": "cn_gf01"},
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
                        game_uid="99999",
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
