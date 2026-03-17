"""
任务管理 API
- 获取/更新签到调度配置
- 手动触发签到
- 获取签到状态概览
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.account import MihoyoAccount, GameRole
from app.models.task_log import TaskConfig, TaskLog
from app.schemas.task_log import (
    TaskConfigCreate, TaskConfigResponse, CheckinSummary,
)
from app.api.auth import get_current_user
from app.services.checkin import CheckinService, SUPPORTED_CHECKIN_BIZ
from app.services.notifier import notification_service
from app.services.scheduler import ScheduleRegistrationError, ScheduleRegistrationResult, scheduler_service
from app.services.task_config import get_or_create_task_config
from app.utils.timezone import get_app_day_utc_range, get_current_app_date

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["任务管理"])


def _build_task_config_response(
    config: TaskConfig,
    runtime: ScheduleRegistrationResult,
) -> TaskConfigResponse:
    return TaskConfigResponse(
        id=config.id,
        user_id=config.user_id,
        task_type=config.task_type,
        cron_expr=config.cron_expr,
        is_enabled=config.is_enabled,
        created_at=config.created_at,
        job_registered=runtime.job_registered,
        job_id=runtime.job_id,
        next_run_time=runtime.next_run_time,
        scheduler_error=runtime.scheduler_error,
    )


@router.get("/config", response_model=TaskConfigResponse)
async def get_task_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的签到调度配置"""
    config, _ = await get_or_create_task_config(db, current_user.id, auto_commit=True)
    runtime = scheduler_service.get_user_schedule_status(
        current_user.id,
        enabled=config.is_enabled,
    )
    return _build_task_config_response(config, runtime)


@router.put("/config", response_model=TaskConfigResponse)
async def update_task_config(
    data: TaskConfigCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新签到调度配置"""
    config, _ = await get_or_create_task_config(db, current_user.id, auto_commit=False)

    config.cron_expr = data.cron_expr
    config.is_enabled = data.is_enabled
    await db.flush()

    try:
        runtime = await scheduler_service.update_user_schedule(current_user.id, config)
    except ScheduleRegistrationError as exc:
        await db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    await db.commit()
    await db.refresh(config)
    return _build_task_config_response(config, runtime)


@router.post("/execute", response_model=CheckinSummary)
async def execute_checkin(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """手动立即执行签到（对该用户的所有启用账号）"""
    checkin_service = CheckinService(db)
    summary = await checkin_service.execute_for_user(current_user.id)

    # 手动签到与定时签到必须复用同一套通知语义，避免后续维护时一条链路发邮件、
    # 另一条链路不发邮件，导致用户设置（通知邮箱、通知策略、SMTP）表现不一致。
    # 这里必须复用 NotificationService，而不是在接口层重新拼装“手动专用”通知规则，
    # 否则排障时会出现“定时任务会发、手动执行不发”之类的行为分叉。
    await notification_service.send_checkin_report(
        current_user.id,
        summary,
        db,
        source="manual_execute",
    )
    return summary


@router.get("/status")
async def get_today_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取今日签到状态概览"""
    today_start, today_end = get_app_day_utc_range(get_current_app_date())

    # 查询该用户所有账号
    accounts_result = await db.execute(
        select(MihoyoAccount).where(MihoyoAccount.user_id == current_user.id)
    )
    accounts = accounts_result.scalars().all()
    account_ids = [a.id for a in accounts]

    if not account_ids:
        return {
            "total_accounts": 0,
            "signed_today": 0,
            "failed_today": 0,
            "pending": 0,
        }

    # 查询今日日志
    logs_result = await db.execute(
        select(TaskLog).where(
            TaskLog.account_id.in_(account_ids),
            TaskLog.executed_at >= today_start,
            TaskLog.executed_at < today_end,
        )
    )
    logs = logs_result.scalars().all()

    signed = sum(1 for l in logs if l.status in ("success", "already_signed"))
    failed = sum(1 for l in logs if l.status == "failed")
    risk = sum(1 for l in logs if l.status == "risk")

    # 统计游戏角色总数
    roles_result = await db.execute(
        select(func.count(GameRole.id)).where(
            GameRole.account_id.in_(account_ids),
            GameRole.is_enabled == True,
            GameRole.game_biz.in_(SUPPORTED_CHECKIN_BIZ),
        )
    )
    total_roles = roles_result.scalar() or 0

    return {
        "total_accounts": len(accounts),
        "total_roles": total_roles,
        "signed_today": signed,
        "failed_today": failed,
        "risk_today": risk,
        "pending": max(0, total_roles - signed - failed - risk),
    }
