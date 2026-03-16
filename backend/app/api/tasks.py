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
from datetime import datetime, date

from app.database import get_db
from app.models.user import User
from app.models.account import MihoyoAccount, GameRole
from app.models.task_log import TaskConfig, TaskLog
from app.schemas.task_log import (
    TaskConfigCreate, TaskConfigResponse, CheckinSummary,
)
from app.api.auth import get_current_user
from app.services.checkin import CheckinService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["任务管理"])


@router.get("/config", response_model=TaskConfigResponse)
async def get_task_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的签到调度配置"""
    result = await db.execute(
        select(TaskConfig).where(TaskConfig.user_id == current_user.id)
    )
    config = result.scalar_one_or_none()

    if not config:
        # 首次访问时自动创建默认配置
        config = TaskConfig(user_id=current_user.id)
        db.add(config)
        await db.commit()
        await db.refresh(config)

    return config


@router.put("/config", response_model=TaskConfigResponse)
async def update_task_config(
    data: TaskConfigCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新签到调度配置"""
    result = await db.execute(
        select(TaskConfig).where(TaskConfig.user_id == current_user.id)
    )
    config = result.scalar_one_or_none()

    if not config:
        config = TaskConfig(user_id=current_user.id)
        db.add(config)

    config.cron_expr = data.cron_expr
    config.is_enabled = data.is_enabled
    await db.commit()
    await db.refresh(config)

    # 通知调度器更新任务
    from app.services.scheduler import scheduler_service
    await scheduler_service.update_user_schedule(current_user.id, config)

    return config


@router.post("/execute", response_model=CheckinSummary)
async def execute_checkin(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """手动立即执行签到（对该用户的所有启用账号）"""
    checkin_service = CheckinService(db)
    summary = await checkin_service.execute_for_user(current_user.id)
    return summary


@router.get("/status")
async def get_today_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取今日签到状态概览"""
    today_start = datetime.combine(date.today(), datetime.min.time())

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
