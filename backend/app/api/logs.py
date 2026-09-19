"""
签到日志查询 API
- 分页查询
- 支持按日期范围、账号、状态、游戏筛选
"""

import json
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.account import MihoyoAccount, GameRole
from app.models.checkin_reward_catalog import CheckinRewardCatalog
from app.models.task_log import TaskLog
from app.schemas.task_log import (
    RewardCalendarResponse,
    RewardGameOption,
    RewardItem,
    RewardRoleOption,
    TaskLogResponse,
    TaskLogListResponse,
)
from app.api.auth import get_current_user
from app.services.checkin import CHECKIN_GAME_CONFIGS, is_checkin_supported_game
from app.services.checkin_rewards import (
    FAMILY_TO_BIZ,
    awards_from_jsonable,
    build_month_award_items,
    build_reward_game_options,
    empty_reward_calendar_payload,
    families_from_roles,
    game_family_of,
    pick_award,
    pick_default_family,
    pick_default_role_id,
    preview_reward_index,
)
from app.utils.timezone import get_shanghai_date, get_shanghai_day_utc_range, to_shanghai

router = APIRouter(prefix="/api/logs", tags=["签到日志"])

# 日志筛选按产品层游戏家族匹配，不把 B 服当成独立游戏。
# 未知 game 值视为未筛选，避免脏参数把列表打空。
GAME_FILTER_BIZ = FAMILY_TO_BIZ


@router.get("", response_model=TaskLogListResponse)
async def list_logs(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    account_id: Optional[int] = Query(None, description="按账号筛选"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    date_start: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    date_end: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD"),
    game: Optional[str] = Query(None, description="按游戏筛选：hk4e / hkrpg / bh3 / nap"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    查询签到日志
    - 仅返回当前用户拥有的账号的日志
    - 支持按账号、状态、日期范围、游戏筛选
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

    biz_list = GAME_FILTER_BIZ.get(game or "")
    if biz_list:
        conditions.append(
            TaskLog.game_role_id.in_(
                select(GameRole.id).where(GameRole.game_biz.in_(biz_list))
            )
        )

    if date_start:
        try:
            start_dt, _ = get_shanghai_day_utc_range(
                datetime.strptime(date_start, "%Y-%m-%d").date()
            )
            conditions.append(TaskLog.executed_at >= start_dt)
        except ValueError:
            pass

    if date_end:
        try:
            _, end_dt = get_shanghai_day_utc_range(
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
                reward_name=log.reward_name,
                reward_cnt=log.reward_cnt,
                reward_icon=log.reward_icon,
                executed_at=log.executed_at,
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
        day = get_shanghai_date() - timedelta(days=i)
        day_start, day_end = get_shanghai_day_utc_range(day)

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


def _next_month_start(day):
    if day.month == 12:
        return day.replace(year=day.year + 1, month=1, day=1)
    return day.replace(month=day.month + 1, day=1)


def _calendar_role_options(family_roles, account_by_id):
    return [
        RewardRoleOption(
            game_role_id=role.id,
            account_nickname=account_by_id[role.account_id].nickname
            or account_by_id[role.account_id].mihoyo_uid,
            game_nickname=role.nickname or role.game_uid,
        )
        for role in family_roles
    ]


@router.get("/rewards", response_model=RewardCalendarResponse)
async def get_reward_calendar(
    game: Optional[str] = Query(None, description="按游戏筛选：hk4e / hkrpg / bh3 / nap"),
    game_role_id: Optional[int] = Query(None, description="按角色筛选"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    当月奖励日历。只读库内目录和本平台签到日志，不请求米游社。
    无 game 参数时优先落到当月已有目录的游戏族；显式传入则尊重选择。
    """
    today = get_shanghai_date()
    empty = empty_reward_calendar_payload(today)
    month = today.strftime("%Y-%m")

    accounts_result = await db.execute(
        select(MihoyoAccount).where(MihoyoAccount.user_id == current_user.id)
    )
    accounts = accounts_result.scalars().all()
    if not accounts:
        empty["empty_reason"] = "no_account"
        return RewardCalendarResponse(**empty)

    account_by_id = {account.id: account for account in accounts}
    roles_result = await db.execute(
        select(GameRole)
        .where(
            GameRole.account_id.in_(account_by_id.keys()),
            GameRole.game_biz.in_(tuple(CHECKIN_GAME_CONFIGS.keys())),
        )
        .order_by(GameRole.id.asc())
    )
    roles = [
        role for role in roles_result.scalars().all()
        if is_checkin_supported_game(role.game_biz)
    ]
    if not roles:
        empty["empty_reason"] = "no_games"
        return RewardCalendarResponse(**empty)

    user_families = families_from_roles(roles)
    catalog_result = await db.execute(
        select(CheckinRewardCatalog.game_family).where(
            CheckinRewardCatalog.month == month,
            CheckinRewardCatalog.game_family.in_(tuple(user_families)),
        )
    )
    catalog_families = {family for family in catalog_result.scalars().all() if family}
    game_options = [
        RewardGameOption(**item)
        for item in build_reward_game_options(roles, catalog_families)
    ]
    empty["games"] = game_options

    month_start = today.replace(day=1)
    month_start_utc, _ = get_shanghai_day_utc_range(month_start)
    next_month_utc, _ = get_shanghai_day_utc_range(_next_month_start(today))
    logs_result = await db.execute(
        select(TaskLog).where(
            TaskLog.game_role_id.in_([role.id for role in roles]),
            TaskLog.task_type == "checkin",
            TaskLog.executed_at >= month_start_utc,
            TaskLog.executed_at < next_month_utc,
        )
    )
    all_month_logs = logs_result.scalars().all()
    role_by_id = {role.id: role for role in roles}
    activity_families: set[str] = set()
    claimed_role_ids: set[int] = set()
    for log in all_month_logs:
        role = role_by_id.get(log.game_role_id)
        if role is None:
            continue
        family = game_family_of(role.game_biz)
        if family:
            activity_families.add(family)
        if log.status in ("success", "already_signed"):
            claimed_role_ids.add(log.game_role_id)

    if game:
        if game not in FAMILY_TO_BIZ:
            empty["empty_reason"] = "no_role"
            return RewardCalendarResponse(**empty)
        requested_family = game
        family_roles = [role for role in roles if game_family_of(role.game_biz) == requested_family]
    else:
        requested_family = pick_default_family(user_families, catalog_families, activity_families)
        family_roles = [
            role for role in roles if game_family_of(role.game_biz) == requested_family
        ]

    if not family_roles:
        empty["game"] = requested_family
        empty["empty_reason"] = "no_role"
        return RewardCalendarResponse(**empty)

    if game_role_id is not None:
        selected = next((role for role in family_roles if role.id == game_role_id), None)
        if selected is None:
            empty["game"] = requested_family
            empty["roles"] = _calendar_role_options(family_roles, account_by_id)
            empty["empty_reason"] = "no_role"
            return RewardCalendarResponse(**empty)
    else:
        selected_id = pick_default_role_id(
            [role.id for role in family_roles],
            claimed_role_ids,
        )
        selected = next((role for role in family_roles if role.id == selected_id), family_roles[0])

    account = account_by_id[selected.account_id]
    role_options = _calendar_role_options(family_roles, account_by_id)

    config = CHECKIN_GAME_CONFIGS.get(selected.game_biz)
    awards = []
    catalog_available = False
    if config is not None:
        catalog_result = await db.execute(
            select(CheckinRewardCatalog).where(
                CheckinRewardCatalog.act_id == config.act_id,
                CheckinRewardCatalog.month == month,
            )
        )
        catalog = catalog_result.scalar_one_or_none()
        if catalog is not None:
            try:
                raw = json.loads(catalog.awards_json) if catalog.awards_json else []
            except (TypeError, ValueError, json.JSONDecodeError):
                raw = []
            awards = awards_from_jsonable(raw)
            catalog_available = True

    month_logs = [log for log in all_month_logs if log.game_role_id == selected.id]

    claimed_days: set[int] = set()
    activity_days: list[int] = []
    latest_claimed = None
    today_claimed_log = None
    for log in month_logs:
        log_day = to_shanghai(log.executed_at).date().day
        activity_days.append(log_day)
        if log.status in ("success", "already_signed"):
            claimed_days.add(log_day)
            if latest_claimed is None or log.executed_at > latest_claimed.executed_at:
                latest_claimed = log
            if log_day == today.day and (
                today_claimed_log is None or log.executed_at > today_claimed_log.executed_at
            ):
                today_claimed_log = log

    first_activity_day = min(activity_days) if activity_days else None
    award_items = []
    if catalog_available:
        award_items = build_month_award_items(
            awards=awards,
            today=today,
            claimed_days=claimed_days,
            first_activity_day=first_activity_day,
        )

    today_claimed = today.day in claimed_days
    today_reward = None
    if catalog_available:
        if today_claimed_log is not None and today_claimed_log.reward_name:
            today_reward = RewardItem(
                day=today.day,
                name=today_claimed_log.reward_name,
                cnt=today_claimed_log.reward_cnt or 0,
                icon=today_claimed_log.reward_icon,
                status="today",
            )
        else:
            if today_claimed:
                claimed_total = latest_claimed.total_sign_days if latest_claimed else None
                preview_index = (
                    claimed_total - 1
                    if claimed_total is not None and claimed_total > 0
                    else max(len(claimed_days) - 1, 0)
                )
            else:
                preview_index = preview_reward_index(
                    latest_claimed.total_sign_days if latest_claimed else None,
                    len(claimed_days),
                )
            preview = pick_award(awards, preview_index)
            if preview is not None and preview.name:
                today_reward = RewardItem(
                    day=today.day,
                    name=preview.name,
                    cnt=preview.cnt,
                    icon=preview.icon,
                    status="today",
                )

    return RewardCalendarResponse(
        month=month,
        today=today.isoformat(),
        game=requested_family,
        game_role_id=selected.id,
        account_nickname=account.nickname or account.mihoyo_uid,
        game_nickname=selected.nickname or selected.game_uid,
        total_sign_days=latest_claimed.total_sign_days if latest_claimed else None,
        today_reward=today_reward,
        today_claimed=today_claimed,
        awards=[RewardItem(**item) for item in award_items],
        catalog_available=catalog_available,
        first_weekday=empty["first_weekday"],
        roles=role_options,
        games=game_options,
        empty_reason=None if catalog_available else "no_catalog",
    )
