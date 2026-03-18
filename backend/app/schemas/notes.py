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
    metrics: list[NoteMetricResponse]


class NoteSummaryResponse(BaseModel):
    account_id: int
    account_name: str
    total_cards: int
    available_cards: int
    failed_cards: int
    cards: list[NoteCardResponse]
