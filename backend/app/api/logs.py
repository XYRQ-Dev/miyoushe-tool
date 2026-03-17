"""
签到日志查询 API
- 分页查询
- 支持按日期范围、账号、状态筛选
"""

from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.account import MihoyoAccount, GameRole
from app.models.task_log import TaskLog
from app.schemas.task_log import TaskLogResponse, TaskLogListResponse
from app.api.auth import get_current_user
from app.utils.timezone import (
    convert_utc_naive_to_app_timezone,
    get_app_day_utc_range,
    get_current_app_date,
)

router = APIRouter(prefix="/api/logs", tags=["签到日志"])


@router.get("", response_model=TaskLogListResponse)
async def list_logs(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    account_id: Optional[int] = Query(None, description="按账号筛选"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    date_start: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    date_end: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    查询签到日志
    - 仅返回当前用户拥有的账号的日志
    - 支持按账号、状态、日期范围筛选
    """
    # 获取该用户的所有账号 ID
    accounts_result = await db.execute(
        select(MihoyoAccount.id).where(MihoyoAccount.user_id == current_user.id)
    )
    account_ids = [row[0] for row in accounts_result.all()]

    if not account_ids:
        return TaskLogListResponse(logs=[], total=0)

    # 构建查询条件
    conditions = [TaskLog.account_id.in_(account_ids)]

    if account_id is not None:
        if account_id not in account_ids:
            return TaskLogListResponse(logs=[], total=0)
        conditions.append(TaskLog.account_id == account_id)

    if status:
        conditions.append(TaskLog.status == status)

    if date_start:
        try:
            start_dt, _ = get_app_day_utc_range(
                datetime.strptime(date_start, "%Y-%m-%d").date()
            )
            conditions.append(TaskLog.executed_at >= start_dt)
        except ValueError:
            pass

    if date_end:
        try:
            _, end_dt = get_app_day_utc_range(
                datetime.strptime(date_end, "%Y-%m-%d").date()
            )
            conditions.append(TaskLog.executed_at < end_dt)
        except ValueError:
            pass

    # 查询总数
    count_query = select(func.count(TaskLog.id)).where(and_(*conditions))
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # 分页查询
    offset = (page - 1) * page_size
    query = (
        select(TaskLog)
        .where(and_(*conditions))
        .order_by(TaskLog.executed_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(query)
    logs = result.scalars().all()

    # 预加载账号和角色信息，用于展示
    log_responses = []
    for log in logs:
        # 查询关联的账号昵称
        acc_result = await db.execute(
            select(MihoyoAccount.nickname).where(MihoyoAccount.id == log.account_id)
        )
        acc_nickname = acc_result.scalar()

        # 查询关联的游戏角色信息
        game_nickname = None
        game_biz = None
        if log.game_role_id:
            role_result = await db.execute(
                select(GameRole).where(GameRole.id == log.game_role_id)
            )
            role = role_result.scalar_one_or_none()
            if role:
                game_nickname = role.nickname
                game_biz = role.game_biz

        log_responses.append(
            TaskLogResponse(
                id=log.id,
                account_id=log.account_id,
                game_role_id=log.game_role_id,
                task_type=log.task_type,
                status=log.status,
                message=log.message,
                total_sign_days=log.total_sign_days,
                executed_at=convert_utc_naive_to_app_timezone(log.executed_at),
                account_nickname=acc_nickname,
                game_nickname=game_nickname,
                game_biz=game_biz,
            )
        )

    return TaskLogListResponse(logs=log_responses, total=total)


@router.get("/calendar")
async def get_sign_calendar(
    days: int = Query(7, ge=1, le=30, description="查询天数"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取签到日历数据（最近 N 天每天的签到统计）
    用于前端仪表盘的日历视图
    """
    accounts_result = await db.execute(
        select(MihoyoAccount.id).where(MihoyoAccount.user_id == current_user.id)
    )
    account_ids = [row[0] for row in accounts_result.all()]

    if not account_ids:
        return {"calendar": []}

    calendar = []
    for i in range(days):
        day = get_current_app_date() - timedelta(days=i)
        day_start, day_end = get_app_day_utc_range(day)

        result = await db.execute(
            select(TaskLog).where(
                TaskLog.account_id.in_(account_ids),
                TaskLog.executed_at >= day_start,
                TaskLog.executed_at < day_end,
            )
        )
        day_logs = result.scalars().all()

        success = sum(1 for l in day_logs if l.status in ("success", "already_signed"))
        failed = sum(1 for l in day_logs if l.status == "failed")
        risk = sum(1 for l in day_logs if l.status == "risk")

        calendar.append({
            "date": day.isoformat(),
            "success": success,
            "failed": failed,
            "risk": risk,
            "total": len(day_logs),
        })

    return {"calendar": calendar}
