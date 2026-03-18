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
    navigable: bool = True


NOTES_MODULE_PATH = "[module] dashboard-notes"
# `notes.path` 是菜单可见性接口里的契约级占位值，不是前端路由，也不是 UI 展示文案。
# notes 实际上是仪表盘内部模块；如果这里误改成 `/notes` 这类伪路由，调用方会把它误判成独立页面，
# 导致菜单管理、前端信息架构和后续兼容逻辑继续围绕一个不存在的真实页面演进。
APP_MENU_DEFINITIONS: tuple[AppMenuDefinition, ...] = (
    AppMenuDefinition("dashboard", "仪表盘", "/", True, True),
    AppMenuDefinition("accounts", "账号管理", "/accounts", True, True),
    AppMenuDefinition("logs", "签到日志", "/logs", True, True),
    AppMenuDefinition("gacha", "抽卡记录", "/gacha", True, True),
    AppMenuDefinition("assets", "角色资产", "/assets", True, True),
    AppMenuDefinition("health", "账号健康中心", "/health", True, True),
    AppMenuDefinition("redeem", "兑换码中心", "/redeem", True, True),
    # 实时便笺属于“独立功能开关”而不是传统导航菜单：
    # 1. 前端需要在菜单管理页里展示并单独控制它
    # 2. 侧边导航却不一定要把它渲染成固定入口
    # 因此这里显式标记 `navigable=False`。若误删该字段或改回可导航项，
    # 前端可能会把本应仅作能力开关的配置误当成菜单入口渲染，造成信息架构漂移。
    AppMenuDefinition("notes", "实时便笺（仪表盘模块）", NOTES_MODULE_PATH, True, True, navigable=False),
    AppMenuDefinition("settings", "系统设置", "/settings", True, True),
    AppMenuDefinition("admin_users", "用户信息列表", "/admin/users", False, True),
    AppMenuDefinition("admin_menu_management", "菜单与功能开关", "/admin/menus", False, True, editable=False),
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


def is_menu_visible_for_role(*, menu_key: str, role: str, raw_value: str | None) -> bool:
    """
    判断某个功能开关对当前角色是否可用。

    这里不能让各个 API 自己去手写 JSON 解析或直接拼 visible_menu_keys，
    否则一旦菜单定义、默认值或保底规则发生变化，接口层很容易继续沿用旧语义，
    出现“菜单看起来被关了，但接口仍可访问”的权限漂移。
    """
    definition = MENU_DEFINITION_MAP.get(menu_key)
    if definition is None:
        return False

    normalized = normalize_menu_visibility(raw_value)
    audience = "admin" if role == "admin" else "user"
    return bool(normalized[definition.key][audience])
