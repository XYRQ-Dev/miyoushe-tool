"""管理员通知相关 Schema。"""

from pydantic import BaseModel, Field


class AdminBroadcastEmailRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1, max_length=5000)


class AdminBroadcastEmailFailure(BaseModel):
    user_id: int
    username: str
    email: str
    error: str


class AdminBroadcastEmailResponse(BaseModel):
    recipient_count: int
    sent_count: int
    failed_count: int
    failures: list[AdminBroadcastEmailFailure] = Field(default_factory=list)
    operation_log_id: int
