"""
系统菜单可见性定义与解析。

这里把“菜单目录”“默认可见性”“保底入口规则”集中到服务层，
避免后端接口、auth/me、前端菜单页各自维护一份 key 清单，最终出现：
1. 某个菜单能被配置但前端没有入口
2. 某个路由存在但后端从不下发可见 key
3. 保底菜单被误关后管理员无法自行恢复
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class AppMenuDefinition:
    key: str
    label: str
    path: str
    default_user_visible: bool
    default_admin_visible: bool
    editable: bool = True


APP_MENU_DEFINITIONS: tuple[AppMenuDefinition, ...] = (
    AppMenuDefinition("dashboard", "仪表盘", "/", True, True),
    AppMenuDefinition("accounts", "账号管理", "/accounts", True, True),
    AppMenuDefinition("logs", "签到日志", "/logs", True, True),
    AppMenuDefinition("gacha", "抽卡记录", "/gacha", True, True),
    AppMenuDefinition("assets", "角色资产", "/assets", True, True),
    AppMenuDefinition("health", "账号健康中心", "/health", True, True),
    AppMenuDefinition("redeem", "兑换码中心", "/redeem", True, True),
    AppMenuDefinition("settings", "系统设置", "/settings", True, True),
    AppMenuDefinition("admin_users", "用户信息列表", "/admin/users", False, True),
    AppMenuDefinition("admin_menu_management", "菜单管理", "/admin/menus", False, True, editable=False),
)

MENU_DEFINITION_MAP: dict[str, AppMenuDefinition] = {item.key: item for item in APP_MENU_DEFINITIONS}
GUARDED_ADMIN_MENU_KEY = "admin_menu_management"


def build_default_menu_visibility() -> dict[str, dict[str, bool]]:
    return {
        item.key: {
            "user": item.default_user_visible,
            "admin": item.default_admin_visible,
        }
        for item in APP_MENU_DEFINITIONS
    }


def normalize_menu_visibility(raw_value: str | None) -> dict[str, dict[str, bool]]:
    normalized = build_default_menu_visibility()
    if not raw_value:
        return normalized

    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return normalized

    if not isinstance(payload, dict):
        return normalized

    for key, value in payload.items():
        if key not in MENU_DEFINITION_MAP or not isinstance(value, dict):
            continue
        normalized[key]["user"] = bool(value.get("user", normalized[key]["user"]))
        normalized[key]["admin"] = bool(value.get("admin", normalized[key]["admin"]))

    # 保底后台入口不允许被配置关闭，否则管理员一旦误操作就只能靠人工改库恢复。
    normalized[GUARDED_ADMIN_MENU_KEY]["admin"] = True
    normalized[GUARDED_ADMIN_MENU_KEY]["user"] = False
    return normalized


def serialize_menu_visibility(config: dict[str, dict[str, bool]]) -> str:
    ordered = {
        item.key: {
            "user": bool(config.get(item.key, {}).get("user", item.default_user_visible)),
            "admin": bool(config.get(item.key, {}).get("admin", item.default_admin_visible)),
        }
        for item in APP_MENU_DEFINITIONS
    }
    ordered[GUARDED_ADMIN_MENU_KEY] = {"user": False, "admin": True}
    return json.dumps(ordered, ensure_ascii=False, separators=(",", ":"))


def resolve_visible_menu_keys(*, role: str, raw_value: str | None) -> list[str]:
    normalized = normalize_menu_visibility(raw_value)
    audience = "admin" if role == "admin" else "user"
    return [item.key for item in APP_MENU_DEFINITIONS if normalized[item.key][audience]]

