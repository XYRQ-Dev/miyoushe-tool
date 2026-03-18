"""
抽卡记录导入与查询服务
"""

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import MihoyoAccount, GameRole
from app.models.gacha import GachaImportJob, GachaRecord
from app.schemas.gacha import (
    GachaAccountListResponse,
    GachaAccountOption,
    GachaExportResponse,
    GachaImportJsonRequest,
    GachaImportResponse,
    GachaPoolSummary,
    GachaRecordListResponse,
    GachaResetResponse,
    GachaSummaryResponse,
)
from app.utils.timezone import utc_now_naive


SUPPORTED_GACHA_GAME_CONFIGS = {
    "genshin": {
        "name": "原神",
        "host_keywords": ("hk4e", "genshin"),
        "pool_names": {
            "100": "新手祈愿",
            "200": "常驻祈愿",
            "301": "角色活动祈愿",
            "302": "武器活动祈愿",
            "500": "集录祈愿",
        },
        "supported_role_prefixes": ("hk4e_",),
    },
    "starrail": {
        "name": "星穹铁道",
        "host_keywords": ("hkrpg", "starrail"),
        "pool_names": {
            "1": "常驻跃迁",
            "2": "新手跃迁",
            "11": "角色活动跃迁",
            "12": "光锥活动跃迁",
        },
        "supported_role_prefixes": ("hkrpg_",),
    },
}


@dataclass
class ParsedImportSource:
    base_url: str
    base_params: dict[str, str]
    masked_url: str


class GachaService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_owned_account(self, account_id: int, user_id: int) -> MihoyoAccount:
        result = await self.db.execute(
            select(MihoyoAccount).where(
                MihoyoAccount.id == account_id,
                MihoyoAccount.user_id == user_id,
            )
        )
        account = result.scalar_one_or_none()
        if account is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        return account

    async def list_supported_accounts(self, user_id: int) -> GachaAccountListResponse:
        result = await self.db.execute(
            select(MihoyoAccount).where(MihoyoAccount.user_id == user_id).order_by(MihoyoAccount.created_at.desc())
        )
        accounts = result.scalars().all()

        response_items: list[GachaAccountOption] = []
        for account in accounts:
            roles_result = await self.db.execute(
                select(GameRole.game_biz).where(GameRole.account_id == account.id)
            )
            game_biz_list = [row[0] for row in roles_result.all()]

            supported_games: list[str] = []
            for game, config in SUPPORTED_GACHA_GAME_CONFIGS.items():
                prefixes = config["supported_role_prefixes"]
                if any(game_biz.startswith(prefixes) for game_biz in game_biz_list):
                    supported_games.append(game)

            if not supported_games:
                continue

            response_items.append(
                GachaAccountOption(
                    id=account.id,
                    nickname=account.nickname,
                    mihoyo_uid=account.mihoyo_uid,
                    supported_games=supported_games,
                )
            )

        return GachaAccountListResponse(accounts=response_items, total=len(response_items))

    async def import_records(self, *, account: MihoyoAccount, game: str, import_url: str) -> GachaImportResponse:
        config = SUPPORTED_GACHA_GAME_CONFIGS.get(game)
        if config is None:
            raise HTTPException(status_code=400, detail="暂不支持该游戏的抽卡记录导入")

        parsed = self._parse_import_url(game, import_url)
        fetched_count = 0
        inserted_count = 0
        duplicate_count = 0
        page = 1
        end_id = "0"

        async with httpx.AsyncClient(
            timeout=30.0,
            headers={
                # 抽卡记录接口对浏览器来源相对宽松，但统一的 UA 能减少被某些边缘代理拦截成异常客户端。
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            },
        ) as client:
            while True:
                params = dict(parsed.base_params)
                params["page"] = str(page)
                params["size"] = "20"
                params["end_id"] = end_id

                response = await client.get(parsed.base_url, params=params)
                payload = response.json()

                if payload.get("retcode") != 0:
                    message = payload.get("message") or payload.get("msg") or "上游返回失败"
                    raise HTTPException(status_code=400, detail=f"抽卡记录导入失败：{message}")

                items = (payload.get("data") or {}).get("list") or []
                if not items:
                    break

                fetched_count += len(items)
                page_inserted, page_duplicates = await self._save_page_records(
                    account_id=account.id,
                    game=game,
                    items=items,
                    pool_name_map=config["pool_names"],
                )
                inserted_count += page_inserted
                duplicate_count += page_duplicates

                if len(items) < 20:
                    break

                next_end_id = str(items[-1].get("id") or "").strip()
                if not next_end_id or next_end_id == end_id:
                    break
                end_id = next_end_id
                page += 1

                # 抽卡记录的 end_id 翻页在异常数据下可能出现循环。
                # 这里设置上限不是为了限制正常用户导入，而是防止坏链接或上游异常把单次导入卡死。
                if page > 200:
                    break

        job = GachaImportJob(
            account_id=account.id,
            game=game,
            source_url_masked=parsed.masked_url,
            status="success",
            fetched_count=fetched_count,
            inserted_count=inserted_count,
            duplicate_count=duplicate_count,
            message="导入完成",
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)

        return GachaImportResponse(
            import_id=job.id,
            account_id=account.id,
            game=game,
            fetched_count=fetched_count,
            inserted_count=inserted_count,
            duplicate_count=duplicate_count,
            source_url_masked=parsed.masked_url,
            message="抽卡记录导入完成",
        )

    async def import_records_from_json(
        self,
        *,
        account: MihoyoAccount,
        game: str,
        request: GachaImportJsonRequest,
    ) -> GachaImportResponse:
        if game not in SUPPORTED_GACHA_GAME_CONFIGS:
            raise HTTPException(status_code=400, detail="暂不支持该游戏的抽卡记录导入")
        if not request.records:
            raise HTTPException(status_code=400, detail="JSON 导入内容不能为空")

        # JSON 导入本质上是“离线恢复/迁移”，不是抓取上游接口。
        # 这里沿用同一套记录模型与去重逻辑，避免形成两条统计口径不一致的入库路径。
        items = [
            {
                "id": record.record_id,
                "gacha_type": record.pool_type,
                "name": record.item_name,
                "item_type": record.item_type,
                "rank_type": record.rank_type,
                "time": record.time_text,
                "pool_name": record.pool_name,
            }
            for record in request.records
        ]
        inserted_count, duplicate_count = await self._save_page_records(
            account_id=account.id,
            game=game,
            items=items,
            pool_name_map=SUPPORTED_GACHA_GAME_CONFIGS[game]["pool_names"],
        )

        source_name = (request.source_name or "json-import").strip() or "json-import"
        source_name = source_name.replace("\\", "_").replace("/", "_")
        job = GachaImportJob(
            account_id=account.id,
            game=game,
            source_url_masked=f"json://{source_name}",
            status="success",
            fetched_count=len(request.records),
            inserted_count=inserted_count,
            duplicate_count=duplicate_count,
            message="JSON 导入完成",
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)

        return GachaImportResponse(
            import_id=job.id,
            account_id=account.id,
            game=game,
            fetched_count=len(request.records),
            inserted_count=inserted_count,
            duplicate_count=duplicate_count,
            source_url_masked=job.source_url_masked,
            message="JSON 导入完成",
        )

    async def _save_page_records(
        self,
        *,
        account_id: int,
        game: str,
        items: list[dict[str, Any]],
        pool_name_map: dict[str, str],
    ) -> tuple[int, int]:
        record_ids = [str(item.get("id") or "").strip() for item in items if item.get("id")]
        existing_result = await self.db.execute(
            select(GachaRecord.record_id).where(
                and_(
                    GachaRecord.account_id == account_id,
                    GachaRecord.game == game,
                    GachaRecord.record_id.in_(record_ids),
                )
            )
        )
        existing_ids = set(existing_result.scalars().all())

        inserted_count = 0
        duplicate_count = 0
        for item in items:
            record_id = str(item.get("id") or "").strip()
            if not record_id:
                continue
            if record_id in existing_ids:
                duplicate_count += 1
                continue

            pool_type = str(item.get("gacha_type") or "").strip() or "unknown"
            self.db.add(
                GachaRecord(
                    account_id=account_id,
                    game=game,
                    record_id=record_id,
                    pool_type=pool_type,
                    pool_name=str(item.get("pool_name") or pool_name_map.get(pool_type, pool_type)),
                    item_name=str(item.get("name") or "未知物品"),
                    item_type=item.get("item_type"),
                    rank_type=str(item.get("rank_type") or "0"),
                    time_text=str(item.get("time") or ""),
                )
            )
            inserted_count += 1

            # 记录新增的 record_id，防止同一次导入中后续条目重复触发唯一索引并为重复条目累加统计。
            existing_ids.add(record_id)

        await self.db.flush()
        return inserted_count, duplicate_count

    async def get_summary(self, *, account_id: int, game: str) -> GachaSummaryResponse:
        result = await self.db.execute(
            select(GachaRecord).where(
                and_(GachaRecord.account_id == account_id, GachaRecord.game == game)
            ).order_by(GachaRecord.time_text.desc(), GachaRecord.record_id.desc())
        )
        records = result.scalars().all()

        five_star = [record for record in records if record.rank_type == "5"]
        four_star_count = sum(1 for record in records if record.rank_type == "4")
        pool_counter: dict[tuple[str, str], int] = {}
        for record in records:
            key = (record.pool_type, record.pool_name or record.pool_type)
            pool_counter[key] = pool_counter.get(key, 0) + 1

        pool_summaries = [
            GachaPoolSummary(pool_type=pool_type, pool_name=pool_name, count=count)
            for (pool_type, pool_name), count in sorted(
                pool_counter.items(),
                key=lambda item: (-item[1], item[0][0]),
            )
        ]

        latest_five = five_star[0] if five_star else None
        return GachaSummaryResponse(
            total_count=len(records),
            five_star_count=len(five_star),
            four_star_count=four_star_count,
            latest_five_star_name=latest_five.item_name if latest_five else None,
            latest_five_star_time=latest_five.time_text if latest_five else None,
            pool_summaries=pool_summaries,
        )

    async def list_records(
        self,
        *,
        account_id: int,
        game: str,
        pool_type: str | None,
        page: int,
        page_size: int,
    ) -> GachaRecordListResponse:
        conditions = [GachaRecord.account_id == account_id, GachaRecord.game == game]
        if pool_type:
            conditions.append(GachaRecord.pool_type == pool_type)

        total = (
            await self.db.execute(
                select(func.count(GachaRecord.id)).where(and_(*conditions))
            )
        ).scalar_one()

        result = await self.db.execute(
            select(GachaRecord)
            .where(and_(*conditions))
            .order_by(GachaRecord.time_text.desc(), GachaRecord.record_id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        records = result.scalars().all()
        return GachaRecordListResponse(records=records, total=total)

    async def export_records(self, *, account_id: int, game: str) -> GachaExportResponse:
        result = await self.db.execute(
            select(GachaRecord)
            .where(and_(GachaRecord.account_id == account_id, GachaRecord.game == game))
            .order_by(GachaRecord.time_text.desc(), GachaRecord.record_id.desc())
        )
        records = result.scalars().all()
        return GachaExportResponse(
            account_id=account_id,
            game=game,
            exported_at=utc_now_naive(),
            total=len(records),
            records=[
                {
                    "record_id": record.record_id,
                    "pool_type": record.pool_type,
                    "pool_name": record.pool_name,
                    "item_name": record.item_name,
                    "item_type": record.item_type,
                    "rank_type": record.rank_type,
                    "time_text": record.time_text,
                }
                for record in records
            ],
        )

    async def reset_records(self, *, account_id: int, game: str) -> GachaResetResponse:
        record_result = await self.db.execute(
            select(GachaRecord).where(
                and_(GachaRecord.account_id == account_id, GachaRecord.game == game)
            )
        )
        records = record_result.scalars().all()
        for record in records:
            await self.db.delete(record)

        job_result = await self.db.execute(
            select(GachaImportJob).where(
                and_(GachaImportJob.account_id == account_id, GachaImportJob.game == game)
            )
        )
        jobs = job_result.scalars().all()
        for job in jobs:
            await self.db.delete(job)

        await self.db.commit()
        return GachaResetResponse(
            account_id=account_id,
            game=game,
            deleted_records=len(records),
            deleted_import_jobs=len(jobs),
            message="抽卡记录已重置",
        )

    def _parse_import_url(self, game: str, import_url: str) -> ParsedImportSource:
        raw = import_url.strip()
        parsed = urlparse(raw)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(status_code=400, detail="请输入完整的抽卡记录链接")

        config = SUPPORTED_GACHA_GAME_CONFIGS[game]
        netloc = parsed.netloc.lower()
        if not any(keyword in netloc for keyword in config["host_keywords"]):
            raise HTTPException(status_code=400, detail=f"该链接与所选游戏“{config['name']}”不匹配")

        params = {key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True)}
        if not params.get("authkey"):
            raise HTTPException(status_code=400, detail="抽卡记录链接缺少 authkey，无法导入")

        base_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        masked_params = dict(params)
        if "authkey" in masked_params:
            masked_params["authkey"] = "***"
        masked_url = f"{base_url}?{urlencode(masked_params)}"

        # 分页字段由服务端统一接管，避免用户粘贴历史链接时把当前页码锁死在中间页。
        params.pop("page", None)
        params.pop("size", None)
        params.pop("end_id", None)

        return ParsedImportSource(base_url=base_url, base_params=params, masked_url=masked_url)


gacha_service_type = GachaService
