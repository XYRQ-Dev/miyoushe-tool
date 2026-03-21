"""
UIGF 交换协议适配层。

这里单独抽一层，而不是把 UIGF 细节散落到 API / Service / ORM 三处，原因有三点：
1. 对外交换格式已经明确收敛到 UIGF，继续沿用仓库私有 JSON 协议只会把前后端、备份文件和第三方工具生态割裂开；
2. 导出默认固定到 v4.2，是为了让新产生的备份统一落在当前主流版本，减少“同一产品导出多种口径”带来的排障歧义；
3. 导入仍兼容 v4.0 / v4.1 / v4.2，是因为历史备份文件一旦已经流出，就不能要求用户先手工升级格式，否则恢复链路会在最需要兜底时失效。

数据库层当前仍复用同一张记录表，但业务维度已经升级到 `account_id + game + game_uid + record_id`：
- 协议适配层只负责忠实保留 `game -> uid -> records` 的结构，不再替调用方“选第一个 UID”或压平多 UID；
- 真正决定导入哪个 UID、导出哪个 UID 的责任在服务层显式参数，而不是在这里做隐式兜底；
- 这样可以把“UIGF 协议兼容”与“角色 UID 选择”两件事拆开维护，避免后续有人在适配层悄悄恢复猜测逻辑。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from time import time
from typing import Any

from pydantic import BaseModel, Field
from pydantic import ValidationError


SUPPORTED_UIGF_VERSIONS = {"v4.0", "v4.1", "v4.2"}
GAME_TO_UIGF_KEY = {
    "genshin": "hk4e",
    "starrail": "hkrpg",
}
UIGF_KEY_TO_GAME = {value: key for key, value in GAME_TO_UIGF_KEY.items()}


class UIGFInfo(BaseModel):
    export_timestamp: int
    export_app: str
    export_app_version: str
    version: str

    model_config = {"extra": "ignore"}


class UIGFHK4ERecord(BaseModel):
    uigf_gacha_type: str
    gacha_type: str
    item_id: str = ""
    count: str = "1"
    time: str
    name: str
    item_type: str | None = None
    rank_type: str
    id: str

    model_config = {"extra": "ignore"}


class UIGFHKRPGRecord(BaseModel):
    gacha_id: str
    gacha_type: str
    item_id: str = ""
    count: str = "1"
    time: str
    name: str
    item_type: str | None = None
    rank_type: str
    id: str

    model_config = {"extra": "ignore"}


class UIGFHK4ESection(BaseModel):
    uid: str
    timezone: int = 8
    lang: str = "zh-cn"
    list: list[UIGFHK4ERecord]
 
    model_config = {"extra": "ignore"}


class UIGFHKRPGSection(BaseModel):
    uid: str
    timezone: int = 8
    lang: str = "zh-cn"
    list: list[UIGFHKRPGRecord]

    model_config = {"extra": "ignore"}


class ParsedUIGFRecord(BaseModel):
    record_id: str
    pool_type: str
    item_name: str
    item_type: str | None = None
    rank_type: str
    time_text: str

    model_config = {"extra": "ignore"}


class ParsedUIGFArchive(BaseModel):
    source_version: str
    records_by_game_and_uid: dict[str, dict[str, list[ParsedUIGFRecord]]]


@dataclass(frozen=True)
class _NormalizedRecord:
    record_id: str
    pool_type: str
    item_name: str
    item_type: str | None
    rank_type: str
    time_text: str


def export_uigf_v42(records_by_game_and_uid: dict[str, dict[str, list[Any]]]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "info": UIGFInfo(
            export_timestamp=int(time()),
            export_app="miyoushe-tool",
            export_app_version="1.0.0",
            version="v4.2",
        ).model_dump(),
    }
    for game, uigf_key in GAME_TO_UIGF_KEY.items():
        uid_map = records_by_game_and_uid.get(game) or {}
        if not uid_map:
            continue

        sections: list[dict[str, Any]] = []
        for uid, raw_records in uid_map.items():
            normalized_records = [_normalize_export_record(record) for record in raw_records]
            if game == "genshin":
                sections.append(
                    UIGFHK4ESection(
                        uid=str(uid),
                        list=[
                            UIGFHK4ERecord(
                                uigf_gacha_type=record.pool_type,
                                gacha_type=record.pool_type,
                                time=record.time_text,
                                name=record.item_name,
                                item_type=record.item_type,
                                rank_type=record.rank_type,
                                id=record.record_id,
                            )
                            for record in normalized_records
                        ],
                    ).model_dump()
                )
                continue

            # UIGF v4.2 要求星铁导出写入 `gacha_id`，但当前库里只保存了通用 `pool_type/gacha_type`，
            # 并没有上游返回的真实池子 ID。这里不能伪装成“精确还原”去硬编码看似官方的数值，
            # 否则后续一旦有人拿它做跨工具比对，会把我们生成的占位值误当成真实上游字段。
            # 因此当前导出明确使用稳定的降级策略：`synthetic-<gacha_type>`。
            # 这保证：
            # 1. 结构符合 UIGF 标准，第三方消费者仍能识别字段存在；
            # 2. 同一份本地数据多次导出结果稳定，可用于回归和幂等对比；
            # 3. 一眼能看出它不是原始上游 `gacha_id`，避免误用；
            # 4. 它只是有损占位，不能保证第三方若按 `gacha_id` 分组时仍与真实上游语义完全一致。
            sections.append(
                UIGFHKRPGSection(
                    uid=str(uid),
                    list=[
                        UIGFHKRPGRecord(
                            gacha_id=_build_synthetic_hkrpg_gacha_id(record.pool_type),
                            gacha_type=record.pool_type,
                            time=record.time_text,
                            name=record.item_name,
                            item_type=record.item_type,
                            rank_type=record.rank_type,
                            id=record.record_id,
                        )
                        for record in normalized_records
                    ],
                ).model_dump()
            )

        payload[uigf_key] = sections

    return payload


def parse_uigf(raw_json: dict[str, Any] | str) -> ParsedUIGFArchive:
    if isinstance(raw_json, str):
        try:
            raw_payload = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError("UIGF JSON 不是合法的 JSON 文本") from exc
    else:
        raw_payload = raw_json

    if not isinstance(raw_payload, dict):
        raise ValueError("UIGF 顶层结构必须是 JSON 对象")

    raw_info = raw_payload.get("info")
    if raw_info is None:
        raise ValueError("UIGF 缺少 info 信息")
    if not isinstance(raw_info, dict):
        raise ValueError("UIGF 的 info 字段必须是对象")

    try:
        info = UIGFInfo.model_validate(raw_info)
    except Exception as exc:
        raise ValueError("UIGF 的 info 字段缺失必要信息") from exc
    if info.version not in SUPPORTED_UIGF_VERSIONS:
        raise ValueError("当前仅支持导入 UIGF v4.0 / v4.1 / v4.2")

    records_by_game_and_uid: dict[str, dict[str, list[ParsedUIGFRecord]]] = {}
    hk4e_sections = raw_payload.get("hk4e") or []
    if not isinstance(hk4e_sections, list):
        raise ValueError("UIGF 字段 hk4e 必须是数组")
    for raw_section in hk4e_sections:
        try:
            section = UIGFHK4ESection.model_validate(raw_section)
        except ValidationError as exc:
            # UIGF 文件通常来自用户上传、第三方工具导出或手工编辑。
            # 这类输入错误本质上是“可预期的外部数据不合法”，而不是服务端 bug。
            # 这里统一转成 ValueError，目的是让上层稳定映射为 400，避免把坏文件误报成 500。
            raise ValueError("UIGF 的 hk4e 结构不合法") from exc
        records = [
            ParsedUIGFRecord(
                record_id=record.id,
                pool_type=record.uigf_gacha_type,
                item_name=record.name,
                item_type=record.item_type,
                rank_type=record.rank_type,
                time_text=record.time,
            )
            for record in section.list
        ]
        if not records:
            continue

        game_bucket = records_by_game_and_uid.setdefault("genshin", {})
        game_bucket.setdefault(section.uid, []).extend(records)

    hkrpg_sections = raw_payload.get("hkrpg") or []
    if not isinstance(hkrpg_sections, list):
        raise ValueError("UIGF 字段 hkrpg 必须是数组")
    for raw_section in hkrpg_sections:
        try:
            section = UIGFHKRPGSection.model_validate(raw_section)
        except ValidationError as exc:
            # 星铁结构错误同样属于用户可构造输入错误，必须与 hk4e 一样稳定收口成业务错误。
            raise ValueError("UIGF 的 hkrpg 结构不合法") from exc
        records = [
            ParsedUIGFRecord(
                record_id=record.id,
                pool_type=record.gacha_type,
                item_name=record.name,
                item_type=record.item_type,
                rank_type=record.rank_type,
                time_text=record.time,
            )
            for record in section.list
        ]
        if not records:
            continue

        game_bucket = records_by_game_and_uid.setdefault("starrail", {})
        game_bucket.setdefault(section.uid, []).extend(records)

    return ParsedUIGFArchive(
        source_version=info.version,
        records_by_game_and_uid=records_by_game_and_uid,
    )


def _normalize_export_record(record: Any) -> _NormalizedRecord:
    def read(field_name: str) -> Any:
        if isinstance(record, dict):
            return record.get(field_name)
        return getattr(record, field_name)

    return _NormalizedRecord(
        record_id=str(read("record_id") or ""),
        pool_type=str(read("pool_type") or "unknown"),
        item_name=str(read("item_name") or "未知物品"),
        item_type=read("item_type"),
        rank_type=str(read("rank_type") or "0"),
        time_text=str(read("time_text") or ""),
    )


def _build_synthetic_hkrpg_gacha_id(pool_type: str) -> str:
    normalized_pool_type = str(pool_type or "unknown").strip() or "unknown"
    return f"synthetic-{normalized_pool_type}"
