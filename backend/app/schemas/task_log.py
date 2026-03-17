"""任务日志和调度配置的 Pydantic 模型"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class TaskConfigCreate(BaseModel):
    cron_expr: str = "0 6 * * *"
    is_enabled: bool = True


class TaskConfigResponse(BaseModel):
    id: int
    user_id: int
    task_type: str
    cron_expr: str
    is_enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskLogResponse(BaseModel):
    id: int
    account_id: int
    game_role_id: Optional[int] = None
    task_type: str
    status: str
    message: Optional[str] = None
    total_sign_days: Optional[int] = None
    executed_at: datetime
    # 额外展示字段（从关联查询填充）
    account_nickname: Optional[str] = None
    game_nickname: Optional[str] = None
    game_biz: Optional[str] = None

    model_config = {"from_attributes": True}


class TaskLogListResponse(BaseModel):
    logs: List[TaskLogResponse]
    total: int


class CheckinResult(BaseModel):
    """单次签到结果"""
    account_id: int
    game_role_id: Optional[int] = None
    # 邮件和前端结果展示都需要定位到具体账号/游戏/角色，否则用户很难判断是哪条签到记录。
    # 这些字段是展示上下文，不参与签到逻辑判断；缺失时前端和邮件模板必须按空值兜底。
    account_nickname: Optional[str] = None
    game_biz: Optional[str] = None
    game_nickname: Optional[str] = None
    status: str  # success / failed / already_signed / risk
    message: str
    total_sign_days: Optional[int] = None


class CheckinSummary(BaseModel):
    """批量签到汇总"""
    total: int
    success: int
    failed: int
    already_signed: int
    risk: int
    results: List[CheckinResult]
