"""抽卡记录相关 Schema"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


SupportedGachaGame = Literal["genshin", "starrail"]


class GachaImportRequest(BaseModel):
    account_id: int
    # 这里刻意不用 `SupportedGachaGame` 约束请求入参。
    # 原因不是放松业务校验，而是避免 FastAPI / Pydantic 在 HTTP 边界先把非法值拦成 422，
    # 导致同一个“游戏不支持”问题在不同入口出现 422/400 两套语义。
    # 实际合法性统一交给 service 层 `_ensure_supported_game()` 收口，这样函数直调、HTTP 请求、
    # 以及未来可能增加的内部任务入口都共享同一份 400 业务错误口径。
    game: str
    # 抽卡链路现在必须显式绑定到角色 UID。
    # 这里不能再靠“从链接里猜”或“默认取第一个角色”兜底，否则前端当前选中的角色与后端真正落库的角色
    # 可能不是同一个，最终会出现导入成功但明细/导出看不到、或者清空时误删另一个 UID 数据的问题。
    game_uid: str = Field(min_length=1, description="当前操作绑定的游戏角色 UID")
    import_url: str = Field(min_length=10, description="从游戏或工具中复制的完整抽卡记录链接")


class GachaImportFromAccountRequest(BaseModel):
    account_id: int
    # 账号直连导入同样刻意不在 schema 层把游戏枚举锁死。
    # 这样“当前仅支持原神账号自动导入”会继续由 service 层统一返回 400，
    # 而不会因为 FastAPI/Pydantic 先拦截成 422，破坏整个抽卡模块现有的错误语义一致性。
    game: str
    game_uid: str = Field(min_length=1, description="当前操作绑定的游戏角色 UID")


class GachaImportResponse(BaseModel):
    import_id: int
    account_id: int
    game: SupportedGachaGame
    game_uid: str
    fetched_count: int
    inserted_count: int
    duplicate_count: int
    source_url_masked: str
    message: str


class GachaImportUIGFRequest(BaseModel):
    account_id: int
    # 同上：请求模型不在 schema 层把 `game` 限死，避免真实 HTTP 流量被框架先转成 422。
    # UIGF 导入最终仍会被 service 层按统一规则校验成 400，从而保证与 URL 导入、查询、导出一致。
    game: str
    game_uid: str = Field(min_length=1, description="当前操作绑定的游戏角色 UID")
    # `source_name` 只用于生成脱敏后的导入来源摘要，不能被误解成可信文件路径。
    # 这里保留原始文件名语义，是为了让运维和用户能从导入历史里定位“用了哪份备份”，
    # 但落库前必须转成 `uigf://` 语义，避免后续维护者又把它当成本地文件路径或 URL 去拼接处理。
    source_name: str | None = Field(default=None, description="导入文件名，仅用于日志与导入历史展示")
    # 正式交换协议统一为 UIGF，对外默认接收完整 UIGF JSON 对象。
    # 这里不把它进一步细分进当前 schema，是为了避免 API 层和协议适配层形成循环依赖；
    # 真正的版本兼容、字段校验与归一化在 `services.gacha_uigf` 中集中处理。
    # 这里同时接受“已解析对象”和“原始 JSON 文本”，是为了兼容：
    # 1. 前端先 `JSON.parse` 后再提交对象；
    # 2. 前端/脚本把文件原文直接透传给后端。
    # 如果误收紧成仅 `dict`，最常见的回归就是文件上传路径能读到文本却在 schema 层被直接拦截。
    uigf_json: dict[str, Any] | str


class GachaFiveStarHistory(BaseModel):
    item_name: str
    time_text: str
    pity_count: int


class GachaPoolSummary(BaseModel):
    pool_type: str
    pool_name: str
    count: int
    five_star_count: int = 0
    four_star_count: int = 0
    current_pity: int = 0
    five_star_history: list[GachaFiveStarHistory] = Field(default_factory=list)


class GachaSummaryResponse(BaseModel):
    account_id: int
    game: SupportedGachaGame
    game_uid: str
    total_count: int
    five_star_count: int
    four_star_count: int
    latest_five_star_name: str | None = None
    latest_five_star_time: str | None = None
    pool_summaries: list[GachaPoolSummary]


class GachaRecordResponse(BaseModel):
    id: int
    game_uid: str
    record_id: str
    pool_type: str
    pool_name: str | None = None
    item_name: str
    item_type: str | None = None
    rank_type: str
    time_text: str
    imported_at: datetime

    model_config = {"from_attributes": True}


class GachaRecordListResponse(BaseModel):
    account_id: int
    game: SupportedGachaGame
    game_uid: str
    records: list[GachaRecordResponse]
    total: int


class GachaRoleOption(BaseModel):
    game: SupportedGachaGame
    game_uid: str
    nickname: str | None = None
    region: str | None = None


class GachaAccountOption(BaseModel):
    id: int
    nickname: str | None = None
    mihoyo_uid: str | None = None
    supported_games: list[SupportedGachaGame]
    gacha_roles: list[GachaRoleOption]


class GachaAccountListResponse(BaseModel):
    accounts: list[GachaAccountOption]
    total: int


class GachaExportResponse(BaseModel):
    account_id: int
    game: SupportedGachaGame
    game_uid: str
    exported_at: datetime
    total: int
    # 导出响应改为直接返回 UIGF 对象，而不是仓库私有的 `records` 扁平数组。
    # 这样前端、备份文件和第三方工具可以围绕同一份协议工作，避免“接口能导、文件不能互通”。
    uigf: dict[str, Any]


class GachaResetResponse(BaseModel):
    account_id: int
    game: SupportedGachaGame
    game_uid: str
    deleted_records: int
    deleted_import_jobs: int
    message: str
