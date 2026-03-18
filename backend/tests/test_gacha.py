import json
import unittest
from unittest.mock import patch

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.gacha import (
    export_gacha_records,
    get_gacha_accounts,
    get_gacha_records,
    get_gacha_summary,
    import_gacha_records,
    import_gacha_records_from_json,
    reset_gacha_records,
)
from app.database import Base
from app.models.account import GameRole, MihoyoAccount
from app.models.gacha import GachaImportJob, GachaRecord
from app.models.user import User
from app.schemas.gacha import GachaImportJsonRequest, GachaImportRequest


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
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

            session.add(GameRole(account_id=account.id, game_biz="hk4e_cn", game_uid="10001", nickname="旅行者"))
            await session.commit()
            await session.refresh(user)
            await session.refresh(account)
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

    async def test_import_gacha_records_from_json_inserts_and_deduplicates(self):
        user, account = await self._seed_user_and_account()

        async with await self._new_session() as session:
            response = await import_gacha_records_from_json(
                GachaImportJsonRequest(
                    account_id=account.id,
                    game="genshin",
                    source_name="backup.json",
                    records=[
                        {
                            "record_id": "5000001",
                            "pool_type": "301",
                            "pool_name": "角色活动祈愿",
                            "item_name": "刻晴",
                            "item_type": "角色",
                            "rank_type": "5",
                            "time_text": "2026-03-18 12:00:00",
                        },
                        {
                            "record_id": "5000001",
                            "pool_type": "301",
                            "pool_name": "角色活动祈愿",
                            "item_name": "刻晴",
                            "item_type": "角色",
                            "rank_type": "5",
                            "time_text": "2026-03-18 12:00:00",
                        },
                    ],
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
        self.assertEqual(total, 1)

    async def test_export_gacha_records_returns_json_backup_for_selected_account_and_game(self):
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

            response = await export_gacha_records(
                account_id=account.id,
                game="genshin",
                current_user=user,
                db=session,
            )

        self.assertEqual(response.account_id, account.id)
        self.assertEqual(response.game, "genshin")
        self.assertEqual(response.total, 1)
        self.assertEqual(response.records[0].record_id, "6000001")

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


if __name__ == "__main__":
    unittest.main()
