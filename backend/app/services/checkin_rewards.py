"""签到奖励目录解析与月历叠加。

`home.awards` 是本月第 1/2/…/N 次签到的奖，官方活动页按 1 号到月末排。
未漏签时第 N 号 ≈ 第 N 次；漏签后档位会顺延。本期不做补签，也不重排 awards。
格子按官方排期展示物品，已领 / 漏签只按本平台东八区日志打标。
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Any


GAME_FAMILY_BY_BIZ = {
    "hk4e_cn": "hk4e",
    "hk4e_bilibili": "hk4e",
    "hkrpg_cn": "hkrpg",
    "hkrpg_bilibili": "hkrpg",
    "bh3_cn": "bh3",
    "nap_cn": "nap",
}

FAMILY_TO_BIZ = {
    "hk4e": ("hk4e_cn", "hk4e_bilibili"),
    "hkrpg": ("hkrpg_cn", "hkrpg_bilibili"),
    "bh3": ("bh3_cn",),
    "nap": ("nap_cn",),
}


@dataclass(frozen=True)
class ParsedAward:
    name: str
    cnt: int
    icon: str | None = None


def game_family_of(game_biz: str | None) -> str | None:
    if not game_biz:
        return None
    return GAME_FAMILY_BY_BIZ.get(game_biz)


def parse_home_awards(payload: dict[str, Any] | None) -> list[ParsedAward] | None:
    """解析 `luna/home`。非 0 retcode 返回 None，表示本次不更新目录。"""
    if not isinstance(payload, dict):
        return None
    try:
        retcode = int(payload.get("retcode", -1))
    except (TypeError, ValueError):
        return None
    if retcode != 0:
        return None

    data = payload.get("data") or {}
    raw_awards = data.get("awards") if isinstance(data, dict) else None
    if not isinstance(raw_awards, list):
        return []

    parsed: list[ParsedAward] = []
    for item in raw_awards:
        # 空名称也保留占位，避免下标错位
        if not isinstance(item, dict):
            parsed.append(ParsedAward(name="", cnt=0, icon=None))
            continue
        name = str(item.get("name") or "").strip()
        try:
            cnt = int(item.get("cnt") or 0)
        except (TypeError, ValueError):
            cnt = 0
        icon = item.get("icon") or item.get("img")
        if isinstance(icon, str):
            icon = icon.strip() or None
        else:
            icon = None
        parsed.append(ParsedAward(name=name, cnt=cnt, icon=icon))
    return parsed


def awards_to_jsonable(awards: list[ParsedAward]) -> list[dict[str, Any]]:
    return [{"name": item.name, "cnt": item.cnt, "icon": item.icon} for item in awards]


def awards_from_jsonable(raw: Any) -> list[ParsedAward]:
    if not isinstance(raw, list):
        return []
    parsed: list[ParsedAward] = []
    for item in raw:
        if not isinstance(item, dict):
            parsed.append(ParsedAward(name="", cnt=0, icon=None))
            continue
        name = str(item.get("name") or "").strip()
        try:
            cnt = int(item.get("cnt") or 0)
        except (TypeError, ValueError):
            cnt = 0
        icon = item.get("icon")
        if isinstance(icon, str):
            icon = icon.strip() or None
        else:
            icon = None
        parsed.append(ParsedAward(name=name, cnt=cnt, icon=icon))
    return parsed


def pick_award(awards: list[ParsedAward], index: int | None) -> ParsedAward | None:
    if index is None or index < 0 or index >= len(awards):
        return None
    return awards[index]


def resolve_claimed_reward_index(
    *,
    signed_from_info: bool,
    result_total: int | None,
    query_total: int | None,
) -> int | None:
    """把当月已签天数映射成 awards 下标。

    - info 已签到或 sign 成功且带 total_sign_day：用该值减 1
    - sign 成功但响应不带该字段：用查询时的已签天数作为今天这一档的下标
    """
    if result_total is not None and result_total > 0:
        return result_total - 1
    if signed_from_info:
        return None
    if query_total is not None and query_total >= 0:
        return query_total
    return None


def preview_reward_index(total_sign_days: int | None, claimed_count: int) -> int:
    """未领取时预览下一档。已签天数和本平台 claimed 次数取较大值。"""
    if total_sign_days is not None and total_sign_days > 0:
        return max(total_sign_days, claimed_count)
    return claimed_count


def format_reward_text(name: str | None, cnt: int | None) -> str | None:
    if not name:
        return None
    if cnt is None:
        return name
    return f"{name} ×{cnt}"


def month_first_weekday(month_start: date) -> int:
    """返回东八区该月 1 号是星期几，周一为 0。"""
    return month_start.weekday()


def empty_reward_calendar_payload(today: date, **overrides: Any) -> dict[str, Any]:
    payload = {
        "month": today.strftime("%Y-%m"),
        "today": today.isoformat(),
        "game": None,
        "game_role_id": None,
        "account_nickname": None,
        "game_nickname": None,
        "total_sign_days": None,
        "today_reward": None,
        "today_claimed": False,
        "awards": [],
        "catalog_available": False,
        "first_weekday": month_first_weekday(today.replace(day=1)),
        "roles": [],
        "games": [],
        "empty_reason": None,
    }
    payload.update(overrides)
    return payload


def families_from_roles(roles: list[Any]) -> list[str]:
    """按角色 id 首次出现顺序收集游戏族，B 服并进同一族。"""
    families: list[str] = []
    seen: set[str] = set()
    for role in roles:
        family = game_family_of(getattr(role, "game_biz", None))
        if not family or family in seen:
            continue
        seen.add(family)
        families.append(family)
    return families


def build_reward_game_options(
    roles: list[Any],
    catalog_families: set[str],
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    order: list[str] = []
    for role in roles:
        family = game_family_of(getattr(role, "game_biz", None))
        if not family:
            continue
        if family not in counts:
            counts[family] = 0
            order.append(family)
        counts[family] += 1
    return [
        {
            "game": family,
            "catalog_available": family in catalog_families,
            "role_count": counts[family],
        }
        for family in order
    ]


def pick_default_family(
    families: list[str],
    catalog_families: set[str],
    activity_families: set[str],
) -> str | None:
    """无 game 参数时的默认游戏族：有当月目录优先，其次本月有日志，否则第一条。"""
    if not families:
        return None
    for family in families:
        if family in catalog_families:
            return family
    for family in families:
        if family in activity_families:
            return family
    return families[0]


def pick_default_role_id(
    role_ids: list[int],
    claimed_role_ids: set[int],
) -> int | None:
    """同一游戏族内优先本月已成功/已签到的角色，否则第一条。"""
    if not role_ids:
        return None
    for role_id in role_ids:
        if role_id in claimed_role_ids:
            return role_id
    return role_ids[0]


def build_month_award_items(
    *,
    awards: list[ParsedAward],
    today: date,
    claimed_days: set[int],
    first_activity_day: int | None,
) -> list[dict[str, Any]]:
    """生成当月每一天的展示项。

    漏签只涂在本月该角色第一条签到日志之后、今天之前、且没有成功/已签到的日子。
    本月还没有任何日志时不把整月打成漏签。
    """
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    items: list[dict[str, Any]] = []
    for day in range(1, days_in_month + 1):
        award = awards[day - 1] if day - 1 < len(awards) else ParsedAward("", 0, None)
        if day > today.day:
            status = "future"
        elif day in claimed_days:
            status = "claimed" if day < today.day else "today"
        elif day == today.day:
            status = "today"
        elif first_activity_day is not None and day >= first_activity_day:
            status = "missed"
        else:
            status = "empty"
        items.append(
            {
                "day": day,
                "name": award.name,
                "cnt": award.cnt,
                "icon": award.icon,
                "status": status,
            }
        )
    return items
