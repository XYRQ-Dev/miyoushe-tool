"""抽卡记录相关 Schema"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SupportedGachaGame = Literal["genshin", "starrail"]


class GachaImportRequest(BaseModel):
    account_id: int
    game: SupportedGachaGame
    import_url: str = Field(min_length=10, description="从游戏或工具中复制的完整抽卡记录链接")


class GachaImportResponse(BaseModel):
    import_id: int
    account_id: int
    game: SupportedGachaGame
    fetched_count: int
    inserted_count: int
    duplicate_count: int
    source_url_masked: str
    message: str


class GachaJsonRecordInput(BaseModel):
    record_id: str
    pool_type: str
    pool_name: str | None = None
    item_name: str
    item_type: str | None = None
    rank_type: str
    time_text: str


class GachaImportJsonRequest(BaseModel):
    account_id: int
    game: SupportedGachaGame
    source_name: str | None = Field(default=None, description="导入文件名，仅用于日志与导入历史展示")
    records: list[GachaJsonRecordInput]


class GachaPoolSummary(BaseModel):
    pool_type: str
    pool_name: str
    count: int


class GachaSummaryResponse(BaseModel):
    total_count: int
    five_star_count: int
    four_star_count: int
    latest_five_star_name: str | None = None
    latest_five_star_time: str | None = None
    pool_summaries: list[GachaPoolSummary]


class GachaRecordResponse(BaseModel):
    id: int
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
    records: list[GachaRecordResponse]
    total: int


class GachaAccountOption(BaseModel):
    id: int
    nickname: str | None = None
    mihoyo_uid: str | None = None
    supported_games: list[SupportedGachaGame]


class GachaAccountListResponse(BaseModel):
    accounts: list[GachaAccountOption]
    total: int


class GachaExportResponse(BaseModel):
    account_id: int
    game: SupportedGachaGame
    exported_at: datetime
    total: int
    records: list[GachaJsonRecordInput]


class GachaResetResponse(BaseModel):
    account_id: int
    game: SupportedGachaGame
    deleted_records: int
    deleted_import_jobs: int
    message: str
