import os
import json
import unittest
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from fastapi import HTTPException
import httpx
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.gacha import (
    export_gacha_records_uigf,
    get_gacha_accounts,
    get_gacha_records,
    get_gacha_summary,
    import_gacha_records,
    import_gacha_records_from_account,
    import_gacha_records_from_uigf,
    reset_gacha_records,
)
from app.database import Base
from app.models.account import GameRole, MihoyoAccount
from app.models.gacha import GachaImportJob, GachaRecord
from app.models.user import User
from app.schemas.gacha import (
    GachaImportFromAccountRequest,
    GachaImportRequest,
    GachaImportUIGFRequest,
)


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

    async def get(self, url, params=None):
        index = len(self.calls)
        self.calls.append({"url": url, "params": params})
        payload = self._payloads[min(index, len(self._payloads) - 1)]
        return FakeResponse(payload)


class FakeRouteAsyncClient:
    def __init__(self, route_payloads):
        self._route_payloads = {
            route: list(payloads)
            for route, payloads in route_payloads.items()
        }
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, headers=None):
        route_key = url.split("://", 1)[-1]
        self.calls.append({"url": url, "params": params, "headers": headers})
        payloads = self._route_payloads.get(route_key)
        if not payloads:
            raise AssertionError(f"Unexpected GET route: {url}")
        payload = payloads.pop(0)
        return FakeResponse(payload)


class GachaTests(unittest.IsolatedAsyncioTestCase):
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

    async def _seed_user_and_account(self):
        async with await self._new_session() as session:
            user = User(username="gacha-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()

            account = MihoyoAccount(user_id=user.id, nickname="测试账号", mihoyo_uid="123456")
            session.add(account)
            await session.flush()

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
            await session.refresh(user)
            await session.refresh(account)
            return user, account

    async def _seed_user_and_account_for_game(self, game: str):
        user, account = await self._seed_user_and_account()
        game_biz = {
            "genshin": "hk4e_cn",
            "starrail": "hkrpg_cn",
        }[game]
        game_uid = {
            "genshin": "10001",
            "starrail": "80001",
        }[game]

        async with await self._new_session() as session:
            existing = (
                await session.execute(
                    select(GameRole).where(
                        GameRole.account_id == account.id,
                        GameRole.game_biz == game_biz,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    GameRole(
                        account_id=account.id,
                        game_biz=game_biz,
                        game_uid=game_uid,
                        nickname="测试角色",
                        region="cn_gf01" if game == "genshin" else "prod_gf_cn",
                    )
                )
                await session.commit()

        return user, account

    async def test_import_gacha_records_saves_records_and_reimport_deduplicates(self):
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
                    },
                    {
                        "id": "1000002",
                        "name": "祭礼剑",
                        "item_type": "武器",
                        "rank_type": "4",
                        "gacha_type": "301",
                        "time": "2026-03-18 11:59:00",
                    },
                ]
            },
        }

        user, account = await self._seed_user_and_account()

        async with await self._new_session() as session:
            with patch("app.services.gacha.httpx.AsyncClient", return_value=FakeAsyncClient([payload])):
                first_result = await import_gacha_records(
                    GachaImportRequest(
                        account_id=account.id,
                        game="genshin",
                        import_url="https://public-operation-hk4e.mihoyo.com/gacha_info/api/getGachaLog?authkey=test-key&authkey_ver=1&sign_type=2&lang=zh-cn&gacha_type=301&page=1&size=20&end_id=0",
                    ),
                    current_user=user,
                    db=session,
                )

            with patch("app.services.gacha.httpx.AsyncClient", return_value=FakeAsyncClient([payload])):
                second_result = await import_gacha_records(
                    GachaImportRequest(
                        account_id=account.id,
                        game="genshin",
                        import_url="https://public-operation-hk4e.mihoyo.com/gacha_info/api/getGachaLog?authkey=test-key&authkey_ver=1&sign_type=2&lang=zh-cn&gacha_type=301&page=1&size=20&end_id=0",
                    ),
                    current_user=user,
                    db=session,
                )

            total = (
                await session.execute(
                    select(func.count(GachaRecord.id)).where(GachaRecord.account_id == account.id)
                )
            ).scalar_one()

        self.assertEqual(first_result.inserted_count, 2)
        self.assertEqual(first_result.duplicate_count, 0)
        self.assertEqual(second_result.inserted_count, 0)
        self.assertEqual(second_result.duplicate_count, 2)
        self.assertEqual(total, 2)

    async def test_import_gacha_records_from_account_generates_genshin_authkey_and_reuses_url_import_chain(self):
        user, account = await self._seed_user_and_account()
        fake_client = FakeRouteAsyncClient(
            {
                "api-takumi.mihoyo.com/binding/api/genAuthKey": [
                    {
                        "retcode": 0,
                        "message": "OK",
                        "data": {
                            "authkey": "generated-authkey",
                            "authkey_ver": 1,
                            "sign_type": 2,
                        },
                    }
                ],
                "public-operation-hk4e.mihoyo.com/gacha_info/api/getGachaLog": [
                    {
                        "retcode": 0,
                        "message": "OK",
                        "data": {
                            "list": [
                                {
                                    "id": "1100001",
                                    "name": "刻晴",
                                    "item_type": "角色",
                                    "rank_type": "5",
                                    "gacha_type": "301",
                                    "time": "2026-03-18 12:00:00",
                                },
                                {
                                    "id": "1100002",
                                    "name": "祭礼剑",
                                    "item_type": "武器",
                                    "rank_type": "4",
                                    "gacha_type": "301",
                                    "time": "2026-03-18 11:59:00",
                                },
                            ]
                        },
                    }
                ],
            }
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
                    GachaImportFromAccountRequest(account_id=account.id, game="genshin"),
                    current_user=user,
                    db=session,
                )

        self.assertEqual(response.game, "genshin")
        self.assertEqual(response.inserted_count, 2)
        self.assertEqual(len(fake_client.calls), 2)
        self.assertEqual(
            fake_client.calls[0]["params"]["auth_appid"],
            "webview_gacha",
        )
        self.assertEqual(
            fake_client.calls[0]["params"]["game_biz"],
            "hk4e_cn",
        )

    async def test_import_gacha_records_from_account_rejects_non_genshin_game(self):
        user, account = await self._seed_user_and_account_for_game("starrail")

        async with await self._new_session() as session:
            with self.assertRaises(HTTPException) as context:
                await import_gacha_records_from_account(
                    GachaImportFromAccountRequest(account_id=account.id, game="starrail"),
                    current_user=user,
                    db=session,
                )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "当前仅支持原神账号自动导入")

    async def test_import_gacha_records_wraps_upstream_network_error_as_400(self):
        user, account = await self._seed_user_and_account_for_game("starrail")

        class RaisingAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, params=None):
                raise httpx.ReadTimeout("timeout")

        async with await self._new_session() as session:
            with patch("app.services.gacha.httpx.AsyncClient", return_value=RaisingAsyncClient()):
                with self.assertRaises(HTTPException) as context:
                    await import_gacha_records(
                        GachaImportRequest(
                            account_id=account.id,
                            game="genshin",
                            import_url="https://public-operation-hk4e.mihoyo.com/gacha_info/api/getGachaLog?authkey=test-key&authkey_ver=1&sign_type=2&lang=zh-cn&gacha_type=301&page=1&size=20&end_id=0",
                        ),
                        current_user=user,
                        db=session,
                    )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "抽卡记录导入失败：无法连接上游接口")

    async def test_import_gacha_records_wraps_invalid_json_response_as_400(self):
        user, account = await self._seed_user_and_account()

        class InvalidJsonAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, params=None):
                return FakeResponse(None, json_error=ValueError("bad json"))

        async with await self._new_session() as session:
            with patch("app.services.gacha.httpx.AsyncClient", return_value=InvalidJsonAsyncClient()):
                with self.assertRaises(HTTPException) as context:
                    await import_gacha_records(
                        GachaImportRequest(
                            account_id=account.id,
                            game="genshin",
                            import_url="https://public-operation-hk4e.mihoyo.com/gacha_info/api/getGachaLog?authkey=test-key&authkey_ver=1&sign_type=2&lang=zh-cn&gacha_type=301&page=1&size=20&end_id=0",
                        ),
                        current_user=user,
                        db=session,
                    )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "抽卡记录导入失败：上游返回了无法解析的响应")

    async def test_import_gacha_records_handles_duplicate_entries_within_single_page(self):
        payload = {
            "retcode": 0,
            "message": "OK",
            "data": {
                "list": [
                    {
                        "id": "4000001",
                        "name": "莫娜",
                        "item_type": "角色",
                        "rank_type": "5",
                        "gacha_type": "301",
                        "time": "2026-03-18 12:05:00",
                    },
                    {
                        "id": "4000001",
                        "name": "莫娜",
                        "item_type": "角色",
                        "rank_type": "5",
                        "gacha_type": "301",
                        "time": "2026-03-18 12:05:00",
                    },
                ]
            },
        }

        user, account = await self._seed_user_and_account()

        async with await self._new_session() as session:
            with patch("app.services.gacha.httpx.AsyncClient", return_value=FakeAsyncClient([payload])):
                result = await import_gacha_records(
                    GachaImportRequest(
                        account_id=account.id,
                        game="genshin",
                        import_url="https://public-operation-hk4e.mihoyo.com/gacha_info/api/getGachaLog?authkey=test-key&authkey_ver=1&sign_type=2&lang=zh-cn&gacha_type=301&page=1&size=20&end_id=0",
                    ),
                    current_user=user,
                    db=session,
                )

            total = (
                await session.execute(
                    select(func.count(GachaRecord.id)).where(GachaRecord.account_id == account.id)
                )
            ).scalar_one()

        self.assertEqual(result.inserted_count, 1)
        self.assertEqual(result.duplicate_count, 1)
        self.assertEqual(total, 1)

    async def test_get_gacha_summary_returns_basic_rank_statistics(self):
        user, account = await self._seed_user_and_account()

        async with await self._new_session() as session:
            session.add_all([
                GachaRecord(
                    account_id=account.id,
                    game="genshin",
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
                    record_id="2000002",
                    pool_type="301",
                    pool_name="角色活动祈愿",
                    item_name="西风剑",
                    item_type="武器",
                    rank_type="4",
                    time_text="2026-03-18 11:59:00",
                ),
            ])
            await session.commit()

            summary = await get_gacha_summary(
                account_id=account.id,
                game="genshin",
                current_user=user,
                db=session,
            )

        self.assertEqual(summary.total_count, 2)
        self.assertEqual(summary.five_star_count, 1)
        self.assertEqual(summary.four_star_count, 1)
        self.assertEqual(summary.latest_five_star_name, "刻晴")
        self.assertEqual(summary.pool_summaries[0].count, 2)

    async def test_get_gacha_accounts_only_returns_supported_accounts(self):
        async with await self._new_session() as session:
            user = User(username="account-list-user", password_hash="x", role="user", is_active=True)
            session.add(user)
            await session.flush()

            supported = MihoyoAccount(user_id=user.id, nickname="支持账号")
            unsupported = MihoyoAccount(user_id=user.id, nickname="未适配账号")
            session.add_all([supported, unsupported])
            await session.flush()

            session.add_all([
                GameRole(account_id=supported.id, game_biz="hk4e_cn", game_uid="10001", nickname="旅行者"),
                GameRole(account_id=unsupported.id, game_biz="nap_cn", game_uid="20001", nickname="绳匠"),
            ])
            await session.commit()
            await session.refresh(user)

            response = await get_gacha_accounts(current_user=user, db=session)

        self.assertEqual(response.total, 1)
        self.assertEqual(response.accounts[0].nickname, "支持账号")

    async def test_get_gacha_records_filters_by_pool_type(self):
        user, account = await self._seed_user_and_account()

        async with await self._new_session() as session:
            session.add_all([
                GachaRecord(
                    account_id=account.id,
                    game="genshin",
                    record_id="3000001",
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
                    record_id="3000002",
                    pool_type="302",
                    pool_name="武器活动祈愿",
                    item_name="祭礼剑",
                    item_type="武器",
                    rank_type="4",
                    time_text="2026-03-18 11:59:00",
                ),
            ])
            await session.commit()

            response = await get_gacha_records(
                account_id=account.id,
                game="genshin",
                pool_type="301",
                page=1,
                page_size=20,
                current_user=user,
                db=session,
            )

        self.assertEqual(response.total, 1)
        self.assertEqual(response.records[0].item_name, "刻晴")

    async def test_import_gacha_records_from_uigf_inserts_and_deduplicates(self):
        user, account = await self._seed_user_and_account()

        async with await self._new_session() as session:
            response = await import_gacha_records_from_uigf(
                GachaImportUIGFRequest(
                    account_id=account.id,
                    game="genshin",
                    source_name="backup.uigf.json",
                    uigf_json={
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
                                    },
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
                                    },
                                ],
                            }
                        ],
                    },
                ),
                current_user=user,
                db=session,
            )

            total = (
                await session.execute(
                    select(func.count(GachaRecord.id)).where(GachaRecord.account_id == account.id)
                )
            ).scalar_one()

        self.assertEqual(response.inserted_count, 1)
        self.assertEqual(response.duplicate_count, 1)
        self.assertEqual(response.source_url_masked, "uigf://backup.uigf.json")
        self.assertEqual(total, 1)

    async def test_import_gacha_records_from_uigf_accepts_raw_json_text(self):
        user, account = await self._seed_user_and_account_for_game("starrail")

        async with await self._new_session() as session:
            response = await import_gacha_records_from_uigf(
                GachaImportUIGFRequest(
                    account_id=account.id,
                    game="starrail",
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
                        GachaRecord.record_id == "5100001",
                    )
                )
            ).scalar_one()

        self.assertEqual(response.inserted_count, 1)
        self.assertEqual(response.duplicate_count, 0)
        self.assertEqual(response.source_url_masked, "uigf://starrail-backup.uigf.json")
        self.assertEqual(stored.item_name, "希儿")

    async def test_import_gacha_records_from_uigf_rejects_malformed_structure_with_400(self):
        user, account = await self._seed_user_and_account()

        async with await self._new_session() as session:
            with self.assertRaises(HTTPException) as context:
                await import_gacha_records_from_uigf(
                    GachaImportUIGFRequest(
                        account_id=account.id,
                        game="genshin",
                        source_name="broken.uigf.json",
                        uigf_json={
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
                                            "gacha_type": "301",
                                            "item_id": "",
                                            "count": "1",
                                            "time": "2026-03-18 12:00:00",
                                            "name": "刻晴",
                                            "item_type": "角色",
                                            "rank_type": "5",
                                            "id": "5200001",
                                        }
                                    ],
                                }
                            ],
                        },
                    ),
                    current_user=user,
                    db=session,
                )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("UIGF", context.exception.detail)

    async def test_export_gacha_records_returns_uigf_backup_for_selected_account_and_game(self):
        user, account = await self._seed_user_and_account()

        async with await self._new_session() as session:
            session.add_all([
                GachaRecord(
                    account_id=account.id,
                    game="genshin",
                    record_id="6000001",
                    pool_type="301",
                    pool_name="角色活动祈愿",
                    item_name="刻晴",
                    item_type="角色",
                    rank_type="5",
                    time_text="2026-03-18 12:00:00",
                ),
                GachaRecord(
                    account_id=account.id,
                    game="starrail",
                    record_id="6000002",
                    pool_type="11",
                    pool_name="角色活动跃迁",
                    item_name="希儿",
                    item_type="角色",
                    rank_type="5",
                    time_text="2026-03-18 11:00:00",
                ),
            ])
            await session.commit()

            response = await export_gacha_records_uigf(
                account_id=account.id,
                game="genshin",
                current_user=user,
                db=session,
            )

        self.assertEqual(response.account_id, account.id)
        self.assertEqual(response.game, "genshin")
        self.assertEqual(response.total, 1)
        self.assertEqual(response.uigf["info"]["version"], "v4.2")
        self.assertIn("hk4e", response.uigf)
        self.assertEqual(response.uigf["hk4e"][0]["list"][0]["id"], "6000001")
        self.assertNotIn("hkrpg", response.uigf)

    async def test_reset_gacha_records_deletes_records_and_import_history_for_selected_game_only(self):
        user, account = await self._seed_user_and_account()

        async with await self._new_session() as session:
            session.add_all([
                GachaRecord(
                    account_id=account.id,
                    game="genshin",
                    record_id="7000001",
                    pool_type="301",
                    pool_name="角色活动祈愿",
                    item_name="刻晴",
                    item_type="角色",
                    rank_type="5",
                    time_text="2026-03-18 12:00:00",
                ),
                GachaRecord(
                    account_id=account.id,
                    game="starrail",
                    record_id="7000002",
                    pool_type="11",
                    pool_name="角色活动跃迁",
                    item_name="希儿",
                    item_type="角色",
                    rank_type="5",
                    time_text="2026-03-18 11:00:00",
                ),
            ])
            session.add_all([
                GachaImportJob(
                    account_id=account.id,
                    game="genshin",
                    source_url_masked="json://genshin-backup.json",
                    status="success",
                    fetched_count=1,
                    inserted_count=1,
                    duplicate_count=0,
                    message="导入完成",
                ),
                GachaImportJob(
                    account_id=account.id,
                    game="starrail",
                    source_url_masked="json://starrail-backup.json",
                    status="success",
                    fetched_count=1,
                    inserted_count=1,
                    duplicate_count=0,
                    message="导入完成",
                ),
            ])
            await session.commit()

            response = await reset_gacha_records(
                account_id=account.id,
                game="genshin",
                current_user=user,
                db=session,
            )

            remaining_genshin_records = (
                await session.execute(
                    select(func.count(GachaRecord.id)).where(
                        GachaRecord.account_id == account.id,
                        GachaRecord.game == "genshin",
                    )
                )
            ).scalar_one()
            remaining_starrail_records = (
                await session.execute(
                    select(func.count(GachaRecord.id)).where(
                        GachaRecord.account_id == account.id,
                        GachaRecord.game == "starrail",
                    )
                )
            ).scalar_one()
            remaining_genshin_jobs = (
                await session.execute(
                    select(func.count(GachaImportJob.id)).where(
                        GachaImportJob.account_id == account.id,
                        GachaImportJob.game == "genshin",
                    )
                )
            ).scalar_one()
            remaining_starrail_jobs = (
                await session.execute(
                    select(func.count(GachaImportJob.id)).where(
                        GachaImportJob.account_id == account.id,
                        GachaImportJob.game == "starrail",
                    )
                )
            ).scalar_one()

        self.assertEqual(response.deleted_records, 1)
        self.assertEqual(response.deleted_import_jobs, 1)
        self.assertEqual(remaining_genshin_records, 0)
        self.assertEqual(remaining_starrail_records, 1)
        self.assertEqual(remaining_genshin_jobs, 0)
        self.assertEqual(remaining_starrail_jobs, 1)

    async def test_query_paths_reject_invalid_game_with_consistent_400(self):
        user, account = await self._seed_user_and_account()

        async with await self._new_session() as session:
            for action in (
                lambda: get_gacha_summary(
                    account_id=account.id,
                    game="invalid-game",
                    current_user=user,
                    db=session,
                ),
                lambda: get_gacha_records(
                    account_id=account.id,
                    game="invalid-game",
                    pool_type=None,
                    page=1,
                    page_size=20,
                    current_user=user,
                    db=session,
                ),
                lambda: export_gacha_records_uigf(
                    account_id=account.id,
                    game="invalid-game",
                    current_user=user,
                    db=session,
                ),
                lambda: reset_gacha_records(
                    account_id=account.id,
                    game="invalid-game",
                    current_user=user,
                    db=session,
                ),
            ):
                with self.subTest(action=action):
                    with self.assertRaises(HTTPException) as context:
                        await action()
                    self.assertEqual(context.exception.status_code, 400)
                    self.assertEqual(context.exception.detail, "暂不支持该游戏的抽卡记录操作")

    async def test_account_without_matching_game_role_is_rejected(self):
        user, account = await self._seed_user_and_account()

        async with await self._new_session() as session:
            with self.assertRaises(HTTPException) as context:
                await import_gacha_records_from_uigf(
                    GachaImportUIGFRequest(
                        account_id=account.id,
                        game="starrail",
                        source_name="starrail-backup.uigf.json",
                        uigf_json={
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
                                            "id": "5300001",
                                        }
                                    ],
                                }
                            ],
                        },
                    ),
                    current_user=user,
                    db=session,
                )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "该账号未开通所选游戏的抽卡记录能力")

    async def test_get_gacha_summary_allows_multiple_roles_for_same_game_account(self):
        user, account = await self._seed_user_and_account()

        async with await self._new_session() as session:
            session.add(
                GameRole(
                    account_id=account.id,
                    game_biz="hk4e_os",
                    game_uid="10002",
                    nickname="旅行者小号",
                )
            )
            session.add(
                GachaRecord(
                    account_id=account.id,
                    game="genshin",
                    record_id="8000001",
                    pool_type="301",
                    pool_name="角色活动祈愿",
                    item_name="刻晴",
                    item_type="角色",
                    rank_type="5",
                    time_text="2026-03-18 12:00:00",
                )
            )
            await session.commit()

            # 同一米游社账号下拥有多个原神角色是常态。
            # 这个用例锁定的是“游戏能力校验只判断存在性，不要求唯一角色”，否则读接口会被误打成 500。
            summary = await get_gacha_summary(
                account_id=account.id,
                game="genshin",
                current_user=user,
                db=session,
            )

        self.assertEqual(summary.total_count, 1)
        self.assertEqual(summary.latest_five_star_name, "刻晴")


if __name__ == "__main__":
    unittest.main()
