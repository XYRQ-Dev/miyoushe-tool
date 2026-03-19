"""实时便笺相关 Schema"""

from typing import Optional

from pydantic import BaseModel


class NoteAccountOption(BaseModel):
    id: int
    nickname: Optional[str] = None
    mihoyo_uid: Optional[str] = None
    supported_games: list[str]


class NoteAccountListResponse(BaseModel):
    accounts: list[NoteAccountOption]
    total: int


class NoteMetricResponse(BaseModel):
    key: str
    label: str
    value: str
    detail: Optional[str] = None
    tone: str = "normal"


class NoteCardResponse(BaseModel):
    role_id: int
    game: str
    game_name: str
    game_biz: str
    role_uid: str
    role_nickname: Optional[str] = None
    region: Optional[str] = None
    level: Optional[int] = None
    status: str
    message: Optional[str] = None
    updated_at: Optional[str] = None
    # `detail_kind/detail` 是 v2 协议里给前端暴露的“游戏专属精细字段”承载层。
    # 这里不能继续把所有信息都压进 metrics：
    # 1. metrics 适合首页摘要展示，但不适合承载三游异构的完整语义
    # 2. detail_kind 让前端能稳定判定字段来源，避免仅靠 game/status 猜结构
    # 3. detail 继续使用宽对象而不是进一步拆成单一 schema，是为了兼容三游字段演进，
    #    但调用方必须先根据 detail_kind 判型，不能直接假定任意字段在所有游戏都存在
    detail_kind: Optional[str] = None
    detail: Optional[dict] = None
    metrics: list[NoteMetricResponse]


class NoteSummaryResponse(BaseModel):
    # v2 之后显式返回 schema/provider，目的是把“本地聚合协议版本”和“底层取数实现来源”固定下来；
    # 这样前后端排障时可以直接区分“页面没升级”和“provider 行为变了”，避免再靠隐式字段猜测。
    schema_version: int = 2
    provider: str = "genshin.py"
    account_id: int
    account_name: str
    total_cards: int
    available_cards: int
    failed_cards: int
    cards: list[NoteCardResponse]
