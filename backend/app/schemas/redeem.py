"""兑换码中心相关 Schema"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SupportedRedeemGame = Literal["genshin", "starrail"]


class RedeemExecuteRequest(BaseModel):
    game: SupportedRedeemGame
    code: str = Field(min_length=3, max_length=100)
    account_ids: list[int] = Field(min_length=1)


class RedeemAccountOption(BaseModel):
    id: int
    nickname: str | None = None
    mihoyo_uid: str | None = None
    supported_games: list[SupportedRedeemGame]


class RedeemAccountListResponse(BaseModel):
    accounts: list[RedeemAccountOption]
    total: int


class RedeemExecutionResponse(BaseModel):
    id: int
    account_id: int
    account_name: str
    game: SupportedRedeemGame
    status: str
    upstream_code: int | None = None
    message: str | None = None
    executed_at: datetime


class RedeemBatchSummaryResponse(BaseModel):
    batch_id: int
    code: str
    game: SupportedRedeemGame
    total_accounts: int
    success_count: int
    already_redeemed_count: int
    invalid_code_count: int
    invalid_cookie_count: int
    error_count: int
    failed_count: int
    message: str | None = None
    created_at: datetime


class RedeemBatchDetailResponse(RedeemBatchSummaryResponse):
    executions: list[RedeemExecutionResponse]


class RedeemBatchListResponse(BaseModel):
    items: list[RedeemBatchSummaryResponse]
    total: int
