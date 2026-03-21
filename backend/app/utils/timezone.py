"""
应用时区工具

约定：
1. 数据库中的无时区 datetime 一律视为 UTC 时间存储
2. 面向用户的“按天统计/筛选/展示”统一按应用时区解释

若后续有人跳过这里直接拿无时区时间做本地日历判断，
很容易出现“日志时间差 8 小时、今日统计跨天错位”的问题。
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings

APP_TIMEZONE = ZoneInfo(settings.APP_TIMEZONE)


def utc_now() -> datetime:
    """
    返回时区感知的 UTC 当前时间。

    Python 3.12+ 已弃用 `datetime.utcnow()`；统一从这里取 UTC 时间，
    可以避免各模块继续散落过时写法，也能明确“当前值带 UTC 时区”。
    """
    return datetime.now(timezone.utc)


def utc_now_naive() -> datetime:
    """
    返回按 UTC 解释的无时区当前时间，供当前 ORM 的 `DateTime` 字段落库使用。

    当前模型层仍把时间统一存成“按 UTC 解释的无时区值”。
    这里显式去掉 tzinfo，是为了让写入约定和查询换算都只收口在这一层，避免各模块自己猜时区。
    """
    return utc_now().replace(tzinfo=None)


def get_current_app_date() -> date:
    """返回应用时区下的当前日期。"""
    return datetime.now(APP_TIMEZONE).date()


def convert_utc_naive_to_app_timezone(dt: datetime) -> datetime:
    """
    将“数据库中按 UTC 解释的无时区时间”转换为应用时区的 aware datetime。

    如果未来数据库字段改成真正的 timezone-aware datetime，这里仍保持兼容，
    避免接口层再次散落时区判断逻辑。
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.astimezone(APP_TIMEZONE)


def get_app_day_utc_range(day: date) -> tuple[datetime, datetime]:
    """
    计算“应用时区某一天”对应的 UTC 存储区间，返回无时区 UTC datetime。

    查询数据库时必须使用这个区间，不能直接把本地日期拼成无时区时间，
    否则会把东八区零点前后的记录错分到前一天或后一天。
    """
    day_start_local = datetime.combine(day, time.min, tzinfo=APP_TIMEZONE)
    day_end_local = day_start_local + timedelta(days=1)
    return (
        day_start_local.astimezone(timezone.utc).replace(tzinfo=None),
        day_end_local.astimezone(timezone.utc).replace(tzinfo=None),
    )
