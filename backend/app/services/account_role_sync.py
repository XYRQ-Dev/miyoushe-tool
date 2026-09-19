"""
账号角色同步服务。

这里的关键目标不是“把上游角色列表写进库里”这么简单，而是稳定维护角色身份：
1. TaskLog 等历史数据会通过 `game_role_id` 关联角色；如果刷新账号时删库重建，历史日志会立刻断链
2. 用户对角色的本地选择（例如 `is_enabled`）属于本系统状态，不应因为重新扫码就被重置
3. 因此同步时复用同一业务角色的现有行，新增角色补建，上游消失的角色保留并停用
"""

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import GameRole, MihoyoAccount
from app.utils.crypto import decrypt_cookie
from app.utils.device import (
    HYPERION_APP_VERSION, build_hyperion_headers, generate_device_fp, generate_device_id,
)
from app.utils.ds import generate_ds

logger = logging.getLogger(__name__)
GAME_ROLES_URL = "https://api-takumi.mihoyo.com/binding/api/getUserGameRolesByCookie"


class RoleFetchError(RuntimeError):
    """角色请求失败或响应不完整，不能作为空角色列表同步"""


async def fetch_game_roles(cookie: str) -> list[dict[str, Any]]:
    """获取完整角色快照；只有明确成功且包含 list 的响应才允许更新本地角色"""
    headers = build_hyperion_headers(
        cookie, device_id=generate_device_id(), device_fp=generate_device_fp(),
        ds=generate_ds(), app_version=HYPERION_APP_VERSION,
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(GAME_ROLES_URL, headers=headers)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict) or payload.get("retcode") != 0:
            raise RoleFetchError("角色接口请求失败")
        data = payload.get("data")
        roles = data.get("list") if isinstance(data, dict) else None
        if not isinstance(roles, list):
            raise RoleFetchError("角色接口响应不完整")
        # 任意角色缺少身份字段都视为快照不完整，避免停用仍然存在的角色
        for role in roles:
            if not isinstance(role, dict) or not all(
                isinstance(role.get(key), str) and role[key].strip()
                for key in ("game_biz", "game_uid", "region")
            ):
                raise RoleFetchError("角色接口返回无效角色")
        return roles
    except RoleFetchError:
        raise
    except Exception as exc:
        raise RoleFetchError("角色接口暂不可用") from exc


async def refresh_account_roles(*, db: AsyncSession, account: MihoyoAccount) -> dict[str, Any]:
    """同步角色并返回独立状态；不提交外层事务，也不改变凭据有效性"""
    try:
        payloads = await fetch_game_roles(decrypt_cookie(account.cookie_encrypted or ""))
        # 保存点只回滚角色更新，根凭据与已修复的 Cookie 仍由调用方提交
        async with db.begin_nested():
            roles = await sync_account_roles(db=db, account_id=account.id, role_payloads=payloads)
        result = {
            "roles_sync_status": "success",
            "roles_count": len(roles),
            "message": f"已同步 {len(roles)} 个游戏角色" if roles else "角色同步完成，未发现游戏角色",
        }
    except Exception:
        # 不输出上游响应或异常参数，避免把 Cookie、票据或 SQL 参数写入日志
        logger.warning("账号 %s 角色同步失败，等待重试", account.id)
        result = {
            "roles_sync_status": "pending",
            "roles_count": None,
            "message": "角色同步待重试，请点击“校验登录态”重试",
        }
        account.last_refresh_status = "roles_sync_pending"
    account.last_refresh_message = f"{account.last_refresh_message or '登录态有效'}；{result['message']}"
    return result


def _build_role_identity(*, game_biz: str, game_uid: str, region: str | None) -> tuple[str, str, str]:
    return game_biz, game_uid, region or ""


async def sync_account_roles(
    *,
    db: AsyncSession,
    account_id: int,
    role_payloads: list[dict],
) -> list[GameRole]:
    # 锁定父账号可串行化首次建角色；角色读取也使用当前读，避免并发同步重复插入
    await db.execute(select(MihoyoAccount.id).where(MihoyoAccount.id == account_id).with_for_update())
    existing_result = await db.execute(
        select(GameRole)
        .where(GameRole.account_id == account_id)
        .order_by(GameRole.id.asc())
        .with_for_update()
    )
    existing_roles = existing_result.scalars().all()
    existing_by_identity = {
        _build_role_identity(
            game_biz=role.game_biz,
            game_uid=role.game_uid,
            region=role.region,
        ): role
        for role in existing_roles
    }

    synced_roles: list[GameRole] = []
    incoming_identities: set[tuple[str, str, str]] = set()

    for role_data in role_payloads:
        identity = _build_role_identity(
            game_biz=str(role_data.get("game_biz", "")),
            game_uid=str(role_data.get("game_uid", "")),
            region=role_data.get("region"),
        )
        if identity in incoming_identities:
            continue
        incoming_identities.add(identity)

        existing_role = existing_by_identity.get(identity)
        if existing_role is None:
            existing_role = GameRole(
                account_id=account_id,
                game_biz=identity[0],
                game_uid=identity[1],
                region=role_data.get("region"),
                nickname=role_data.get("nickname", ""),
                level=role_data.get("level", 0),
                is_enabled=True,
            )
            db.add(existing_role)
        else:
            existing_role.nickname = role_data.get("nickname", "")
            existing_role.level = role_data.get("level", 0)
            existing_role.region = role_data.get("region")

        synced_roles.append(existing_role)

    for role in existing_roles:
        identity = _build_role_identity(
            game_biz=role.game_biz,
            game_uid=role.game_uid,
            region=role.region,
        )
        if identity not in incoming_identities:
            # 上游消失的角色保留历史关联并停用，重新出现时也不覆盖本地停用偏好
            role.is_enabled = False

    await db.flush()
    return synced_roles
