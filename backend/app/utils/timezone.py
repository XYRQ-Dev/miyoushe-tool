"""
时区工具。

对外只承认 Asia/Shanghai：业务“今天”、调度、接口展示、日志墙上时间都固定东八区。
不允许再引入应用时区配置、浏览器时区或部署机器时区作为第二种选择。

内部约定：
1. 数据库中的无时区 datetime 一律视为 UTC 绝对时刻
2. JWT exp 继续使用 UTC，这是协议要求，不是给用户看的时区
3. 面向用户的日期边界和 datetime 出参一律转成东八区
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import BeforeValidator
from typing import Annotated

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _coerce_shanghai(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"期望 datetime，实际为 {type(value)!r}")
    return to_shanghai(value)


ShanghaiDateTime = Annotated[datetime, BeforeValidator(_coerce_shanghai)]


def utc_now() -> datetime:
    """
    返回时区感知的 UTC 当前时间。

    Python 3.12+ 已弃用 `datetime.utcnow()`；统一从这里取 UTC 时间，
    可以避免各模块继续散落过时写法，也能明确“当前值带 UTC 时区”。
    JWT `exp` 必须继续走这里，不要改成东八区。
    """
    return datetime.now(timezone.utc)


def utc_now_naive() -> datetime:
    """
    返回按 UTC 解释的无时区当前时间，供当前 ORM 的 `DateTime` 字段落库使用。

    当前模型层仍把时间统一存成“按 UTC 解释的无时区值”。
    这里显式去掉 tzinfo，是为了让写入约定和查询换算都只收口在这一层，避免各模块自己猜时区。
    """
    return utc_now().replace(tzinfo=None)


def shanghai_now() -> datetime:
    """返回东八区感知的当前时间。"""
    return datetime.now(SHANGHAI)


def get_shanghai_date() -> date:
    """返回东八区当前日期，供签到“今天”、日历和邮件标题使用。"""
    return shanghai_now().date()


def to_shanghai(dt: datetime) -> datetime:
    """
    将时间转换为东八区感知 datetime。

    无时区值一律按 UTC 解释；这与当前库内存储约定一致。
    已经带时区的值只做时区转换，不改变绝对时刻。
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(SHANGHAI)


def get_shanghai_day_utc_range(day: date) -> tuple[datetime, datetime]:
    """
    计算东八区某一天对应的 UTC 存储区间，返回无时区 UTC datetime。

    查询数据库时必须使用这个区间，不能直接把本地日期拼成无时区时间，
    否则会把东八区零点前后的记录错分到前一天或后一天。
    """
    day_start_local = datetime.combine(day, dt_time.min, tzinfo=SHANGHAI)
    day_end_local = day_start_local + timedelta(days=1)
    return (
        day_start_local.astimezone(timezone.utc).replace(tzinfo=None),
        day_end_local.astimezone(timezone.utc).replace(tzinfo=None),
    )


class ShanghaiLogFormatter(logging.Formatter):
    """把 logging 墙上时间固定为东八区，不跟随进程宿主时区。"""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, SHANGHAI)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]


def configure_process_timezone() -> None:
    """
    尽量把进程本地时区也钉到东八区。

    Linux/容器有 `tzset()`；Windows 没有，因此日志显示仍必须依赖 `ShanghaiLogFormatter`。
    """
    os.environ["TZ"] = "Asia/Shanghai"
    tzset = getattr(time, "tzset", None)
    if callable(tzset):
        tzset()


def configure_shanghai_logging() -> None:
    """配置根 logger 与 uvicorn logger，使业务日志和访问日志都显示东八区。"""
    configure_process_timezone()
    formatter = ShanghaiLogFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    else:
        root.setLevel(logging.INFO)
    for handler in root.handlers:
        handler.setFormatter(formatter)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        for handler in uv_logger.handlers:
            handler.setFormatter(formatter)
