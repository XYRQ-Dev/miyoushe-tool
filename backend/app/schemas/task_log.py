"""任务日志和调度配置的 Pydantic 模型"""

from typing import Optional, List
from pydantic import BaseModel

from app.utils.timezone import ShanghaiDateTime


class TaskConfigCreate(BaseModel):
    cron_expr: str = "0 6 * * *"
    is_enabled: bool = True


class TaskConfigResponse(BaseModel):
    id: int
    user_id: int
    task_type: str
    cron_expr: str
    is_enabled: bool
    created_at: ShanghaiDateTime
    job_registered: bool = False
    job_id: Optional[str] = None
    next_run_time: Optional[ShanghaiDateTime] = None
    scheduler_error: Optional[str] = None

    model_config = {"from_attributes": True}


class TaskLogResponse(BaseModel):
    id: int
    account_id: int
    game_role_id: Optional[int] = None
    task_type: str
    status: str
    message: Optional[str] = None
    total_sign_days: Optional[int] = None
    reward_name: Optional[str] = None
    reward_cnt: Optional[int] = None
    reward_icon: Optional[str] = None
    executed_at: ShanghaiDateTime
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
    reward_name: Optional[str] = None
    reward_cnt: Optional[int] = None
    reward_icon: Optional[str] = None


class CheckinSummary(BaseModel):
    """批量签到汇总"""
    total: int
    success: int
    failed: int
    already_signed: int
    risk: int
    results: List[CheckinResult]


class RewardItem(BaseModel):
    day: int
    name: str = ""
    cnt: int = 0
    icon: Optional[str] = None
    status: str


class RewardRoleOption(BaseModel):
    game_role_id: int
    account_nickname: Optional[str] = None
    game_nickname: Optional[str] = None


class RewardGameOption(BaseModel):
    game: str
    catalog_available: bool = False
    role_count: int = 0


class RewardCalendarResponse(BaseModel):
    month: str
    today: str
    game: Optional[str] = None
    game_role_id: Optional[int] = None
    account_nickname: Optional[str] = None
    game_nickname: Optional[str] = None
    total_sign_days: Optional[int] = None
    today_reward: Optional[RewardItem] = None
    today_claimed: bool = False
    awards: List[RewardItem] = []
    catalog_available: bool = False
    first_weekday: int = 0
    roles: List[RewardRoleOption] = []
    games: List[RewardGameOption] = []
    empty_reason: Optional[str] = None
