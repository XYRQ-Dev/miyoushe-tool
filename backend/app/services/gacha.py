"""
抽卡记录导入与查询服务
"""

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import MihoyoAccount, GameRole
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
    GachaSummaryResponse,
)
from app.services.account_credentials import AccountCredentialService
from app.services.gacha_uigf import export_uigf_v42, parse_uigf
from app.utils.crypto import decrypt_cookie
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

GENSHIN_AUTHKEY_API_URL = "https://api-takumi.mihoyo.com/binding/api/genAuthKey"
GENSHIN_GACHA_LOG_API_URL = "https://public-operation-hk4e.mihoyo.com/gacha_info/api/getGachaLog"
GENSHIN_REGION_BY_GAME_BIZ = {
    "hk4e_cn": "cn_gf01",
    "hk4e_os": "os_usa",
}


@dataclass
class ParsedImportSource:
    base_url: str
    base_params: dict[str, str]
    masked_url: str


class GachaService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _ensure_supported_game(self, game: str, *, detail: str = "暂不支持该游戏的抽卡记录操作") -> dict[str, Any]:
        config = SUPPORTED_GACHA_GAME_CONFIGS.get(game)
        if config is None:
            raise HTTPException(status_code=400, detail=detail)
        return config

    def _raise_upstream_import_error(self, message: str) -> None:
        # 抽卡 URL 导入依赖外部接口与网络环境，网络抖动、代理篡改、上游异常格式都属于高频外部失败。
        # 这些情况若直接冒泡成 500，用户和维护者都会被误导成“服务端代码炸了”，实际排障方向会完全跑偏。
        # 这里统一收口成 400 业务错误，是为了明确表达：请求已被成功处理，但导入源本身不可用或不合法。
        raise HTTPException(status_code=400, detail=f"抽卡记录导入失败：{message}")

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

    async def get_owned_account_for_game(self, account_id: int, user_id: int, game: str) -> MihoyoAccount:
        config = self._ensure_supported_game(game)
        account = await self.get_owned_account(account_id, user_id)

        prefixes = config["supported_role_prefixes"]
        # `list_supported_accounts()` 会把账号-游戏能力展示给前端，但这不能只是“界面提示”。
        # 如果读写接口不复用同一套能力判定，前端看到“不支持”的账号仍可被手工请求写入另一款游戏数据，
        # 最终会把不同游戏的记录混进同一账号，破坏后续导出、统计与排障边界。
        # 因此这里强制把“展示出来的 supported_games”和“后端实际允许读写的权限”绑定为同一事实来源。
        role_result = await self.db.execute(
            select(GameRole.id).where(
                GameRole.account_id == account_id,
                or_(*(GameRole.game_biz.startswith(prefix) for prefix in prefixes)),
            ).limit(1)
        )
        # 这里的业务问题是“账号是否至少拥有一个该游戏角色”，不是“是否只拥有唯一角色”。
        # 同一米游社账号下出现多个同游戏角色是平台的正常数据形态；如果改回 `scalar_one_or_none()` 这类唯一性读取，
        # 能力校验会把合法账号误判成 500，前端侧所有依赖该校验的读写接口都会一起被打断，排障时也会被误导到数据库重复数据方向。
        # 因此查询只保留存在性语义，并显式 `limit(1)`，避免未来维护时把“权限判断”和“唯一约束”再次混为一谈。
        if role_result.first() is None:
            raise HTTPException(status_code=400, detail="该账号未开通所选游戏的抽卡记录能力")

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
        config = self._ensure_supported_game(game, detail="暂不支持该游戏的抽卡记录导入")

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

                try:
                    response = await client.get(parsed.base_url, params=params)
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    self._raise_upstream_import_error(f"上游接口返回异常状态 {exc.response.status_code}")
                except httpx.HTTPError as exc:
                    self._raise_upstream_import_error("无法连接上游接口")

                try:
                    payload = response.json()
                except Exception:
                    self._raise_upstream_import_error("上游返回了无法解析的响应")

                if not isinstance(payload, dict):
                    self._raise_upstream_import_error("上游返回了不符合预期的响应结构")

                if payload.get("retcode") != 0:
                    message = payload.get("message") or payload.get("msg") or "上游返回失败"
                    raise HTTPException(status_code=400, detail=f"抽卡记录导入失败：{message}")

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

    async def import_records_from_account(self, *, account: MihoyoAccount, game: str) -> GachaImportResponse:
        if game != "genshin":
            # 本任务只补原神的 `SToken -> authkey -> 导入` 主链路。
            # 星铁虽然也支持手贴 URL / UIGF，但它的自动票据链、接口参数和风险面并不与原神完全一致；
            # 若在这次需求里顺手复用，会把“已验证的原神链路”与“未完成验证的星铁票据链”混在同一入口里。
            raise HTTPException(status_code=400, detail="当前仅支持原神账号自动导入")

        import_url = await self._generate_genshin_authkey(account)
        # 账号直连导入刻意只负责把账号态换成一条临时抽卡 URL，然后直接复用既有 URL 导入逻辑。
        # 原因是分页抓取、去重、落库、导入历史已经在 `import_records()` 中被现网路径验证过；
        # 如果这里再复制一套分页实现，后续任何字段修复或去重规则调整都要双份维护，极易出现两条导入链路语义漂移。
        return await self.import_records(account=account, game=game, import_url=import_url)

    async def import_records_from_uigf(
        self,
        *,
        account: MihoyoAccount,
        game: str,
        request: GachaImportUIGFRequest,
    ) -> GachaImportResponse:
        self._ensure_supported_game(game, detail="暂不支持该游戏的抽卡记录导入")

        try:
            parsed_uigf = parse_uigf(request.uigf_json)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        game_records_by_uid = parsed_uigf.records_by_game_and_uid.get(game) or {}
        if not game_records_by_uid:
            raise HTTPException(status_code=400, detail="UIGF 文件中不包含所选游戏记录")

        # 现有表结构没有 `game_uid` 维度，这里只能把同账号同游戏的多个 UID 记录继续压平成一份导入批次。
        # 这是刻意保持当前主线兼容：导入、汇总、去重全部仍围绕旧表工作，避免协议替换顺手引入数据迁移。
        # 如果未来要按角色 UID 精确隔离导入历史，必须新增字段和迁移，而不是在这里悄悄改变统计口径。
        items = [
            {
                "id": record.record_id,
                "gacha_type": record.pool_type,
                "name": record.item_name,
                "item_type": record.item_type,
                "rank_type": record.rank_type,
                "time": record.time_text,
            }
            for records in game_records_by_uid.values()
            for record in records
        ]
        if not items:
            raise HTTPException(status_code=400, detail="UIGF 文件中没有可导入的记录")

        inserted_count, duplicate_count = await self._save_page_records(
            account_id=account.id,
            game=game,
            items=items,
            pool_name_map=SUPPORTED_GACHA_GAME_CONFIGS[game]["pool_names"],
        )

        source_name = (request.source_name or "uigf-import").strip() or "uigf-import"
        source_name = source_name.replace("\\", "_").replace("/", "_")
        job = GachaImportJob(
            account_id=account.id,
            game=game,
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
        self._ensure_supported_game(game)
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
        self._ensure_supported_game(game)
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
        self._ensure_supported_game(game)
        result = await self.db.execute(
            select(GachaRecord)
            .where(and_(GachaRecord.account_id == account_id, GachaRecord.game == game))
            .order_by(GachaRecord.time_text.desc(), GachaRecord.record_id.desc())
        )
        records = result.scalars().all()

        supported_prefixes = SUPPORTED_GACHA_GAME_CONFIGS[game]["supported_role_prefixes"]
        role_result = await self.db.execute(
            select(GameRole.game_uid)
            .where(
                GameRole.account_id == account_id,
                or_(*(GameRole.game_biz.startswith(prefix) for prefix in supported_prefixes)),
            )
            .order_by(GameRole.id.asc())
        )
        game_uids = [str(uid) for uid in role_result.scalars().all() if uid]

        # 当前导出仍基于扁平表，记录本身不携带角色 UID。
        # 因此这里只能选择一个稳定 UID 作为单游戏 UIGF 分组键，保证导出的协议合法且行为可预期；
        # 若未来把这里改成“按多 UID 拆分”，但底层数据仍未保存来源 UID，就会把同一批记录伪装成多角色数据。
        export_uid = game_uids[0] if game_uids else "unknown"
        uigf_payload = export_uigf_v42(
            {
                game: {
                    export_uid: records,
                }
            }
        )

        return GachaExportResponse(
            account_id=account_id,
            game=game,
            exported_at=utc_now_naive(),
            total=len(records),
            uigf=uigf_payload,
        )

    async def reset_records(self, *, account_id: int, game: str) -> GachaResetResponse:
        self._ensure_supported_game(game)
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

    async def _generate_genshin_authkey(self, account: MihoyoAccount) -> str:
        role_result = await self.db.execute(
            select(GameRole)
            .where(
                GameRole.account_id == account.id,
                or_(*(GameRole.game_biz.startswith(prefix) for prefix in SUPPORTED_GACHA_GAME_CONFIGS["genshin"]["supported_role_prefixes"])),
            )
            .order_by(GameRole.id.asc())
        )
        role = role_result.scalars().first()
        if role is None or not role.game_uid:
            raise HTTPException(status_code=400, detail="该账号缺少可用的原神角色，无法自动导入")

        region = (role.region or GENSHIN_REGION_BY_GAME_BIZ.get(role.game_biz) or "").strip()
        if not region:
            raise HTTPException(status_code=400, detail="该原神角色缺少区域信息，无法自动导入")

        ensure_result = await AccountCredentialService(self.db).ensure_work_cookie(account)
        if ensure_result.get("state") != "valid":
            detail = str(ensure_result.get("message") or "账号工作 Cookie 不可用")
            raise HTTPException(status_code=400, detail=detail)

        work_cookie = str(ensure_result.get("cookie") or "").strip()
        if not work_cookie and account.cookie_encrypted:
            try:
                work_cookie = decrypt_cookie(account.cookie_encrypted)
            except Exception as exc:
                raise HTTPException(status_code=400, detail="账号工作 Cookie 无法解密，无法自动导入") from exc
        if not work_cookie:
            raise HTTPException(status_code=400, detail="账号工作 Cookie 不可用")

        params = {
            "auth_appid": "webview_gacha",
            "game_biz": "hk4e_cn",
            "game_uid": str(role.game_uid),
            "region": region,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    GENSHIN_AUTHKEY_API_URL,
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "Cookie": work_cookie,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=400, detail=f"原神 authkey 生成失败：上游接口返回异常状态 {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=400, detail="原神 authkey 生成失败：无法连接上游接口") from exc

        try:
            payload = response.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="原神 authkey 生成失败：上游返回了无法解析的响应") from exc

        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="原神 authkey 生成失败：上游返回了不符合预期的响应结构")

        if payload.get("retcode") != 0:
            message = payload.get("message") or payload.get("msg") or "上游返回失败"
            raise HTTPException(status_code=400, detail=f"原神 authkey 生成失败：{message}")

        data_payload = payload.get("data") or {}
        if not isinstance(data_payload, dict):
            raise HTTPException(status_code=400, detail="原神 authkey 生成失败：上游返回了不符合预期的响应结构")

        authkey = str(data_payload.get("authkey") or "").strip()
        authkey_ver = str(data_payload.get("authkey_ver") or "").strip()
        sign_type = str(data_payload.get("sign_type") or "").strip()
        if not authkey or not authkey_ver or not sign_type:
            raise HTTPException(status_code=400, detail="原神 authkey 生成失败：上游未返回完整票据")

        return self._build_genshin_import_url_from_authkey(
            authkey=authkey,
            authkey_ver=authkey_ver,
            sign_type=sign_type,
        )

    def _build_genshin_import_url_from_authkey(self, *, authkey: str, authkey_ver: str, sign_type: str) -> str:
        # `authkey` 与完整抽卡 URL 都属于可直接重放抽卡接口的高敏感票据。
        # 这里故意只在内存里瞬时组装，随后立刻交给现有 URL 导入链路；真正落库的仍只有脱敏后的 `source_url_masked`。
        # 如果未来有人把完整 URL 顺手写进日志、任务表或异常上报，等价于把账号抽卡查询能力暴露给日志系统。
        params = {
            "authkey": authkey,
            "authkey_ver": authkey_ver,
            "sign_type": sign_type,
            "lang": "zh-cn",
            "gacha_type": "301",
        }
        return f"{GENSHIN_GACHA_LOG_API_URL}?{urlencode(params)}"


gacha_service_type = GachaService
