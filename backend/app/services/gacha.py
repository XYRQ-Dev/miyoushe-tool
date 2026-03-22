"""
抽卡记录导入与查询服务
"""

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import GameRole, MihoyoAccount
from app.models.gacha import GachaImportJob, GachaRecord
from app.schemas.gacha import (
    GachaAccountListResponse,
    GachaAccountOption,
    GachaExportResponse,
    GachaImportResponse,
    GachaImportUIGFRequest,
    GachaPoolSummary,
    GachaRecordListResponse,
    GachaResetResponse,
    GachaRoleOption,
    GachaSummaryResponse,
)
from app.services.genshin_authkey import GenshinAuthkeyService
from app.services.gacha_uigf import export_uigf_v42, parse_uigf
from app.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)

SUPPORTED_GACHA_GAME_CONFIGS = {
    "genshin": {
        "name": "原神",
        "host_keywords": ("hk4e", "genshin"),
        "pool_names": {
            "100": "新手祈愿",
            "200": "常驻祈愿",
            "301": "角色活动祈愿",
            "302": "武器活动祈愿",
            "400": "角色活动祈愿",
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
GACHA_PAGE_DELAY_RANGE_MS = (1000, 2000)
GACHA_RATE_LIMIT_RETRY_DELAY_RANGES_MS = (
    (2000, 3000),
    (4000, 6000),
    (7000, 9000),
)

@dataclass
class ParsedImportSource:
    base_url: str
    base_params: dict[str, str]
    masked_url: str
    scan_gacha_types: tuple[str, ...]


@dataclass(frozen=True)
class ImportRunSummary:
    fetched_count: int
    inserted_count: int
    duplicate_count: int


class GachaService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _ensure_supported_game(self, game: str, *, detail: str = "暂不支持该游戏的抽卡记录操作") -> dict[str, Any]:
        config = SUPPORTED_GACHA_GAME_CONFIGS.get(game)
        if config is None:
            raise HTTPException(status_code=400, detail=detail)
        return config

    def _normalize_game_uid(self, game_uid: str, *, detail: str = "缺少 game_uid，无法定位目标角色") -> str:
        normalized = str(game_uid or "").strip()
        if not normalized:
            raise HTTPException(status_code=400, detail=detail)
        return normalized

    def _raise_upstream_import_error(self, message: str) -> None:
        # 抽卡 URL 导入依赖外部接口与网络环境，网络抖动、代理篡改、上游异常格式都属于高频外部失败。
        # 这些情况若直接冒泡成 500，用户和维护者都会被误导成“服务端代码炸了”，实际排障方向会完全跑偏。
        # 这里统一收口成 400 业务错误，是为了明确表达：请求已被成功处理，但导入源本身不可用或不合法。
        raise HTTPException(status_code=400, detail=f"抽卡记录导入失败：{message}")

    @staticmethod
    def _is_gacha_rate_limited(message: str) -> bool:
        normalized = (message or "").strip().lower()
        return "visit too frequently" in normalized

    def _normalize_gacha_upstream_error_message(self, message: str) -> str:
        if self._is_gacha_rate_limited(message):
            return "访问过于频繁，请稍后重试"
        return (message or "").strip() or "上游返回失败"

    # 星铁手贴链接经常只给基础 authkey URL，不包含具体卡池类型。
    # 如果这里要求用户手工拆成 4 条单池链接，实际体验会退化成“链接明明有效，但导入总是 0 条”，
    # 维护侧也很难第一眼看出根因是缺 `gacha_type` 而不是票据失效。
    # 因此仅在星铁手贴链接缺池型参数时，后端兜底按已支持池型逐个扫描并统一去重。
    STARRAIL_SUPPORTED_GACHA_TYPES = ("1", "2", "11", "12")

    @staticmethod
    def _pick_delay_ms(delay_range_ms: tuple[int, int]) -> int:
        return random.randint(delay_range_ms[0], delay_range_ms[1])

    async def _sleep_page_interval(self) -> None:
        """
        在分页请求之间插入 HuTao 风格随机等待。

        `getGachaLog` 连续翻页过快时，上游会直接返回 `visit too frequently`。
        这里必须在“上一页成功、下一页尚未发出”之间等待，而不是失败后才临时补救，
        否则真实链路会继续表现成“偶尔能导入几页，随后稳定被限流”。
        """
        await asyncio.sleep(self._pick_delay_ms(GACHA_PAGE_DELAY_RANGE_MS) / 1000)

    async def _sleep_rate_limit_backoff(self, *, page: int, retry_index: int) -> None:
        delay_range_ms = GACHA_RATE_LIMIT_RETRY_DELAY_RANGES_MS[retry_index]
        delay_ms = self._pick_delay_ms(delay_range_ms)
        logger.warning(
            "抽卡分页请求触发频率限制，准备退避重试: page=%s retry=%s delay_ms=%s",
            page,
            retry_index + 1,
            delay_ms,
        )
        await asyncio.sleep(delay_ms / 1000)

    async def _fetch_gacha_page_payload(
        self,
        client: httpx.AsyncClient,
        *,
        parsed: ParsedImportSource,
        page: int,
        end_id: str,
    ) -> dict[str, Any]:
        params = dict(parsed.base_params)
        params["page"] = str(page)
        params["size"] = "20"
        params["end_id"] = end_id

        max_attempts = len(GACHA_RATE_LIMIT_RETRY_DELAY_RANGES_MS) + 1
        for attempt in range(max_attempts):
            try:
                response = await client.get(parsed.base_url, params=params)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self._raise_upstream_import_error(f"上游接口返回异常状态 {exc.response.status_code}")
            except httpx.HTTPError:
                self._raise_upstream_import_error("无法连接上游接口")

            try:
                payload = response.json()
            except Exception:
                self._raise_upstream_import_error("上游返回了无法解析的响应")

            if not isinstance(payload, dict):
                self._raise_upstream_import_error("上游返回了不符合预期的响应结构")

            if payload.get("retcode") == 0:
                return payload

            message = str(payload.get("message") or payload.get("msg") or "上游返回失败").strip()
            if self._is_gacha_rate_limited(message) and attempt < max_attempts - 1:
                await self._sleep_rate_limit_backoff(page=page, retry_index=attempt)
                continue

            self._raise_upstream_import_error(self._normalize_gacha_upstream_error_message(message))

        self._raise_upstream_import_error("访问过于频繁，请稍后重试")

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

    async def get_owned_account_for_game(
        self,
        account_id: int,
        user_id: int,
        game: str,
        game_uid: str,
    ) -> MihoyoAccount:
        config = self._ensure_supported_game(game)
        normalized_game_uid = self._normalize_game_uid(game_uid)
        account = await self.get_owned_account(account_id, user_id)

        prefixes = config["supported_role_prefixes"]
        # 读写接口现在必须把“所选角色是否真实存在”当成权限校验的一部分，而不是只校验账号拥有该游戏任意角色。
        # 否则同账号下两个 UID 并存时，用户即使选中了 A 角色，也可能被后端默默写到 B 角色名下，
        # 这会让导入、导出、重置和资产总览全部出现“看起来成功、实际串 UID”的高隐蔽回归。
        role_result = await self.db.execute(
            select(GameRole.id).where(
                GameRole.account_id == account_id,
                GameRole.game_uid == normalized_game_uid,
                or_(*(GameRole.game_biz.startswith(prefix) for prefix in prefixes)),
            ).limit(1)
        )
        if role_result.first() is None:
            raise HTTPException(status_code=400, detail="该账号未开通所选角色的抽卡记录能力")

        return account

    async def list_supported_accounts(self, user_id: int) -> GachaAccountListResponse:
        result = await self.db.execute(
            select(MihoyoAccount).where(MihoyoAccount.user_id == user_id).order_by(MihoyoAccount.created_at.desc())
        )
        accounts = result.scalars().all()

        response_items: list[GachaAccountOption] = []
        for account in accounts:
            roles_result = await self.db.execute(
                select(GameRole).where(GameRole.account_id == account.id).order_by(GameRole.id.asc())
            )
            roles = roles_result.scalars().all()

            supported_games: list[str] = []
            gacha_roles: list[GachaRoleOption] = []
            for game, config in SUPPORTED_GACHA_GAME_CONFIGS.items():
                prefixes = config["supported_role_prefixes"]
                matching_roles = [role for role in roles if role.game_biz.startswith(prefixes) and role.game_uid]
                if not matching_roles:
                    continue

                supported_games.append(game)
                gacha_roles.extend(
                    GachaRoleOption(
                        game=game,
                        game_uid=str(role.game_uid),
                        nickname=role.nickname,
                        region=role.region,
                    )
                    for role in matching_roles
                )

            if not supported_games:
                continue

            response_items.append(
                GachaAccountOption(
                    id=account.id,
                    nickname=account.nickname,
                    mihoyo_uid=account.mihoyo_uid,
                    supported_games=supported_games,
                    gacha_roles=gacha_roles,
                )
            )

        return GachaAccountListResponse(accounts=response_items, total=len(response_items))

    async def import_records(
        self,
        *,
        account: MihoyoAccount,
        game: str,
        game_uid: str,
        import_url: str,
    ) -> GachaImportResponse:
        config = self._ensure_supported_game(game, detail="暂不支持该游戏的抽卡记录导入")
        normalized_game_uid = self._normalize_game_uid(game_uid)
        parsed = self._parse_import_url(game, normalized_game_uid, import_url)

        async with httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            },
        ) as client:
            import_summary = ImportRunSummary(fetched_count=0, inserted_count=0, duplicate_count=0)
            for import_source in self._expand_import_sources(parsed):
                source_summary = await self._import_records_from_source(
                    client=client,
                    account_id=account.id,
                    game=game,
                    game_uid=normalized_game_uid,
                    parsed=import_source,
                    pool_name_map=config["pool_names"],
                )
                import_summary = ImportRunSummary(
                    fetched_count=import_summary.fetched_count + source_summary.fetched_count,
                    inserted_count=import_summary.inserted_count + source_summary.inserted_count,
                    duplicate_count=import_summary.duplicate_count + source_summary.duplicate_count,
                )

        job = GachaImportJob(
            account_id=account.id,
            game=game,
            game_uid=normalized_game_uid,
            source_url_masked=parsed.masked_url,
            status="success",
            fetched_count=import_summary.fetched_count,
            inserted_count=import_summary.inserted_count,
            duplicate_count=import_summary.duplicate_count,
            message="导入完成",
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)

        return GachaImportResponse(
            import_id=job.id,
            account_id=account.id,
            game=game,
            game_uid=normalized_game_uid,
            fetched_count=import_summary.fetched_count,
            inserted_count=import_summary.inserted_count,
            duplicate_count=import_summary.duplicate_count,
            source_url_masked=parsed.masked_url,
            message="抽卡记录导入完成",
        )

    def _expand_import_sources(self, parsed: ParsedImportSource) -> list[ParsedImportSource]:
        if len(parsed.scan_gacha_types) <= 1:
            return [parsed]

        import_sources: list[ParsedImportSource] = []
        for gacha_type in parsed.scan_gacha_types:
            base_params = dict(parsed.base_params)
            base_params["gacha_type"] = gacha_type
            import_sources.append(
                ParsedImportSource(
                    base_url=parsed.base_url,
                    base_params=base_params,
                    masked_url=parsed.masked_url,
                    scan_gacha_types=(gacha_type,),
                )
            )
        return import_sources

    async def _import_records_from_source(
        self,
        *,
        client: httpx.AsyncClient,
        account_id: int,
        game: str,
        game_uid: str,
        parsed: ParsedImportSource,
        pool_name_map: dict[str, str],
    ) -> ImportRunSummary:
        fetched_count = 0
        inserted_count = 0
        duplicate_count = 0
        page = 1
        end_id = "0"

        while True:
            payload = await self._fetch_gacha_page_payload(
                client,
                parsed=parsed,
                page=page,
                end_id=end_id,
            )

            data_payload = payload.get("data") or {}
            if not isinstance(data_payload, dict):
                self._raise_upstream_import_error("上游返回了不符合预期的响应结构")

            items = data_payload.get("list") or []
            if not isinstance(items, list):
                self._raise_upstream_import_error("上游返回了不符合预期的响应结构")
            if not items:
                break

            fetched_count += len(items)
            page_inserted, page_duplicates = await self._save_page_records(
                account_id=account_id,
                game=game,
                game_uid=game_uid,
                items=items,
                pool_name_map=pool_name_map,
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
            await self._sleep_page_interval()

            # 抽卡记录的 end_id 翻页在异常数据下可能出现循环。
            # 这里设置上限不是为了限制正常用户导入，而是防止坏链接或上游异常把单次导入卡死。
            if page > 200:
                break

        return ImportRunSummary(
            fetched_count=fetched_count,
            inserted_count=inserted_count,
            duplicate_count=duplicate_count,
        )

    async def import_records_from_account(
        self,
        *,
        account: MihoyoAccount,
        game: str,
        game_uid: str,
    ) -> GachaImportResponse:
        if game != "genshin":
            raise HTTPException(status_code=400, detail="当前仅支持原神账号自动导入")

        import_url = await self._generate_genshin_authkey(account, game_uid)
        # 账号直连导入刻意只负责把账号态换成一条临时抽卡 URL，然后直接复用既有 URL 导入逻辑。
        # 原因是分页抓取、去重、落库、导入历史已经在 `import_records()` 中被现网路径验证过；
        # 如果这里再复制一套分页实现，后续任何字段修复或去重规则调整都要双份维护，极易出现两条导入链路语义漂移。
        return await self.import_records(account=account, game=game, game_uid=game_uid, import_url=import_url)

    async def import_records_from_uigf(
        self,
        *,
        account: MihoyoAccount,
        game: str,
        request: GachaImportUIGFRequest,
    ) -> GachaImportResponse:
        self._ensure_supported_game(game, detail="暂不支持该游戏的抽卡记录导入")
        normalized_game_uid = self._normalize_game_uid(request.game_uid)

        try:
            parsed_uigf = parse_uigf(request.uigf_json)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        game_records_by_uid = parsed_uigf.records_by_game_and_uid.get(game) or {}
        if not game_records_by_uid:
            raise HTTPException(status_code=400, detail="UIGF 文件中不包含所选游戏记录")

        items = [
            {
                "id": record.record_id,
                "gacha_type": record.pool_type,
                "name": record.item_name,
                "item_type": record.item_type,
                "rank_type": record.rank_type,
                "time": record.time_text,
            }
            for record in game_records_by_uid.get(normalized_game_uid, [])
        ]
        if not items:
            raise HTTPException(status_code=400, detail="UIGF 文件中不包含所选 UID 的记录")

        inserted_count, duplicate_count = await self._save_page_records(
            account_id=account.id,
            game=game,
            game_uid=normalized_game_uid,
            items=items,
            pool_name_map=SUPPORTED_GACHA_GAME_CONFIGS[game]["pool_names"],
        )

        source_name = (request.source_name or "uigf-import").strip() or "uigf-import"
        source_name = source_name.replace("\\", "_").replace("/", "_")
        job = GachaImportJob(
            account_id=account.id,
            game=game,
            game_uid=normalized_game_uid,
            source_url_masked=f"uigf://{source_name}",
            status="success",
            fetched_count=len(items),
            inserted_count=inserted_count,
            duplicate_count=duplicate_count,
            message="UIGF 导入完成",
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)

        return GachaImportResponse(
            import_id=job.id,
            account_id=account.id,
            game=game,
            game_uid=normalized_game_uid,
            fetched_count=len(items),
            inserted_count=inserted_count,
            duplicate_count=duplicate_count,
            source_url_masked=job.source_url_masked,
            message="UIGF 导入完成",
        )

    async def _save_page_records(
        self,
        *,
        account_id: int,
        game: str,
        game_uid: str,
        items: list[dict[str, Any]],
        pool_name_map: dict[str, str],
    ) -> tuple[int, int]:
        normalized_game_uid = self._normalize_game_uid(game_uid)
        duplicate_count = 0
        rows_to_insert: list[dict[str, Any]] = []
        seen_record_ids: set[str] = set()
        for item in items:
            record_id = str(item.get("id") or "").strip()
            if not record_id:
                continue

            # 星铁全池扫描和上游异常页里都可能把同一条 `record_id` 重复返回。
            # 这里只靠“先查数据库再逐条 add”并不能覆盖同页重复、跨请求竞态或并发导入：
            # 查询结束到 flush 之间，目标唯一键依然可能被别的写入占住，最终把用户可恢复的重复数据放大成 500。
            # 因此这里先做页内去重，再把最终幂等性交给 MySQL 唯一键 + IGNORE 写入收口。
            if record_id in seen_record_ids:
                duplicate_count += 1
                continue

            seen_record_ids.add(record_id)
            pool_type = str(item.get("gacha_type") or "").strip() or "unknown"
            rows_to_insert.append(
                {
                    "account_id": account_id,
                    "game": game,
                    "game_uid": normalized_game_uid,
                    "record_id": record_id,
                    "pool_type": pool_type,
                    "pool_name": str(item.get("pool_name") or pool_name_map.get(pool_type, pool_type)),
                    "item_name": str(item.get("name") or "未知物品"),
                    "item_type": item.get("item_type"),
                    "rank_type": str(item.get("rank_type") or "0"),
                    "time_text": str(item.get("time") or ""),
                    "imported_at": utc_now_naive(),
                }
            )

        if not rows_to_insert:
            return 0, duplicate_count

        insert_stmt = mysql_insert(GachaRecord).values(rows_to_insert).prefix_with("IGNORE")
        result = await self.db.execute(insert_stmt)
        inserted_count = int(result.rowcount or 0)
        duplicate_count += len(rows_to_insert) - inserted_count
        return inserted_count, duplicate_count

    async def get_summary(self, *, account_id: int, game: str, game_uid: str) -> GachaSummaryResponse:
        self._ensure_supported_game(game)
        normalized_game_uid = self._normalize_game_uid(game_uid)
        result = await self.db.execute(
            select(GachaRecord)
            .where(
                and_(
                    GachaRecord.account_id == account_id,
                    GachaRecord.game == game,
                    GachaRecord.game_uid == normalized_game_uid,
                )
            )
            .order_by(GachaRecord.time_text.desc(), GachaRecord.record_id.desc())
        )
        records = result.scalars().all()

        five_star = [record for record in records if record.rank_type == "5"]
        four_star_count = sum(1 for record in records if record.rank_type == "4")
        
        # Calculate per-pool detailed stats
        pool_stats: dict[str, dict[str, Any]] = {}
        pool_names_map = SUPPORTED_GACHA_GAME_CONFIGS[game]["pool_names"]
        
        # Iterate backwards (oldest first) to build pity and history accurately
        for record in reversed(records):
            pool_type = record.pool_type
            # 原神角色活动祈愿 2 (400) 与 1 (301) 共享保底，汇总时归入 301 统计。
            display_type = "301" if game == "genshin" and pool_type == "400" else pool_type
            pool_name = pool_names_map.get(display_type, record.pool_name or display_type)
            
            if display_type not in pool_stats:
                pool_stats[display_type] = {
                    "pool_type": display_type,
                    "pool_name": pool_name,
                    "count": 0,
                    "five_star_count": 0,
                    "four_star_count": 0,
                    "current_pity": 0,
                    "five_star_history": [],
                }
            
            stats = pool_stats[display_type]
            stats["count"] += 1
            
            if record.rank_type == "4":
                stats["four_star_count"] += 1
                stats["current_pity"] += 1
            elif record.rank_type == "5":
                stats["five_star_count"] += 1
                stats["five_star_history"].append(
                    {
                        "item_name": record.item_name,
                        "time_text": record.time_text,
                        "pity_count": stats["current_pity"] + 1,
                    }
                )
                stats["current_pity"] = 0
            else:
                stats["current_pity"] += 1

        # We reverse the history so the newest 5-star is at the top of the list in the UI
        for stats in pool_stats.values():
            stats["five_star_history"].reverse()

        pool_summaries = [
            GachaPoolSummary(**stats)
            for _, stats in sorted(
                pool_stats.items(),
                key=lambda item: (-item[1]["count"], item[0]),
            )
        ]

        latest_five = five_star[0] if five_star else None
        return GachaSummaryResponse(
            account_id=account_id,
            game=game,
            game_uid=normalized_game_uid,
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
        game_uid: str,
        pool_type: str | None,
        page: int,
        page_size: int,
    ) -> GachaRecordListResponse:
        self._ensure_supported_game(game)
        normalized_game_uid = self._normalize_game_uid(game_uid)
        conditions = [
            GachaRecord.account_id == account_id,
            GachaRecord.game == game,
            GachaRecord.game_uid == normalized_game_uid,
        ]
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
        return GachaRecordListResponse(
            account_id=account_id,
            game=game,
            game_uid=normalized_game_uid,
            records=records,
            total=total,
        )

    async def export_records(self, *, account_id: int, game: str, game_uid: str) -> GachaExportResponse:
        self._ensure_supported_game(game)
        normalized_game_uid = self._normalize_game_uid(game_uid)
        result = await self.db.execute(
            select(GachaRecord)
            .where(
                and_(
                    GachaRecord.account_id == account_id,
                    GachaRecord.game == game,
                    GachaRecord.game_uid == normalized_game_uid,
                )
            )
            .order_by(GachaRecord.time_text.desc(), GachaRecord.record_id.desc())
        )
        records = result.scalars().all()

        uigf_payload = export_uigf_v42(
            {
                game: {
                    normalized_game_uid: records,
                }
            }
        )

        return GachaExportResponse(
            account_id=account_id,
            game=game,
            game_uid=normalized_game_uid,
            exported_at=utc_now_naive(),
            total=len(records),
            uigf=uigf_payload,
        )

    async def reset_records(self, *, account_id: int, game: str, game_uid: str) -> GachaResetResponse:
        self._ensure_supported_game(game)
        normalized_game_uid = self._normalize_game_uid(game_uid)
        record_result = await self.db.execute(
            select(GachaRecord).where(
                and_(
                    GachaRecord.account_id == account_id,
                    GachaRecord.game == game,
                    GachaRecord.game_uid == normalized_game_uid,
                )
            )
        )
        records = record_result.scalars().all()
        for record in records:
            await self.db.delete(record)

        job_result = await self.db.execute(
            select(GachaImportJob).where(
                and_(
                    GachaImportJob.account_id == account_id,
                    GachaImportJob.game == game,
                    GachaImportJob.game_uid == normalized_game_uid,
                )
            )
        )
        jobs = job_result.scalars().all()
        for job in jobs:
            await self.db.delete(job)

        await self.db.commit()
        return GachaResetResponse(
            account_id=account_id,
            game=game,
            game_uid=normalized_game_uid,
            deleted_records=len(records),
            deleted_import_jobs=len(jobs),
            message="抽卡记录已重置",
        )

    def _parse_import_url(self, game: str, game_uid: str, import_url: str) -> ParsedImportSource:
        raw = import_url.strip()
        parsed = urlparse(raw)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(status_code=400, detail="请输入完整的抽卡记录链接")

        config = SUPPORTED_GACHA_GAME_CONFIGS[game]
        netloc = parsed.netloc.lower()
        if not any(keyword in netloc for keyword in config["host_keywords"]):
            raise HTTPException(status_code=400, detail=f"该链接与所选游戏“{config['name']}”不匹配")

        normalized_game_uid = self._normalize_game_uid(game_uid)
        params = {key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True)}
        if not params.get("authkey"):
            raise HTTPException(status_code=400, detail="抽卡记录链接缺少 authkey，无法导入")

        source_game_uid = str(params.get("game_uid") or "").strip()
        if source_game_uid and source_game_uid != normalized_game_uid:
            raise HTTPException(status_code=400, detail="抽卡记录链接中的 UID 与所选角色不一致")

        base_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        masked_params = dict(params)
        if "authkey" in masked_params:
            masked_params["authkey"] = "***"
        gacha_type = str(params.get("gacha_type") or "").strip()
        if game == "starrail" and not gacha_type:
            # 星铁基础链接缺少 `gacha_type` 时，上游通常不会报错，只会静默返回空列表。
            # 这里在脱敏来源里显式标成 `auto`，是为了让导入历史能还原“后端做过全池扫描”这一事实，
            # 否则后续排障会误判成用户贴的是完整单池链接。
            masked_params["gacha_type"] = "auto"
        masked_url = f"{base_url}?{urlencode(masked_params)}"

        # 分页字段由服务端统一接管，避免用户粘贴历史链接时把当前页码锁死在中间页。
        params.pop("page", None)
        params.pop("size", None)
        params.pop("end_id", None)
        if game == "starrail" and not gacha_type:
            scan_gacha_types = self.STARRAIL_SUPPORTED_GACHA_TYPES
        else:
            scan_gacha_types = (gacha_type,) if gacha_type else ()

        return ParsedImportSource(
            base_url=base_url,
            base_params=params,
            masked_url=masked_url,
            scan_gacha_types=scan_gacha_types,
        )

    async def _generate_genshin_authkey(self, account: MihoyoAccount, game_uid: str) -> str:
        normalized_game_uid = self._normalize_game_uid(game_uid)
        role_result = await self.db.execute(
            select(GameRole)
            .where(
                GameRole.account_id == account.id,
                GameRole.game_uid == normalized_game_uid,
                or_(
                    *(
                        GameRole.game_biz.startswith(prefix)
                        for prefix in SUPPORTED_GACHA_GAME_CONFIGS["genshin"]["supported_role_prefixes"]
                    )
                ),
            )
            .order_by(GameRole.id.asc())
        )
        role = role_result.scalars().first()
        if role is None or not role.game_uid:
            raise HTTPException(status_code=400, detail="该账号缺少可用的原神角色，无法自动导入")

        return await GenshinAuthkeyService(self.db).generate_import_url(account, role)


gacha_service_type = GachaService
