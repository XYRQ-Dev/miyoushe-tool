"""
账号角色同步服务。

这里的关键目标不是“把上游角色列表写进库里”这么简单，而是稳定维护角色身份：
1. TaskLog 等历史数据会通过 `game_role_id` 关联角色；如果刷新账号时删库重建，历史日志会立刻断链
2. 用户对角色的本地选择（例如 `is_enabled`）属于本系统状态，不应因为重新扫码就被重置
3. 因此同步时必须优先复用同一业务角色的现有行，只在确实新增/删除角色时才改动记录集合
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import GameRole


def _build_role_identity(*, game_biz: str, game_uid: str, region: str | None) -> tuple[str, str, str]:
    return game_biz, game_uid, region or ""


async def sync_account_roles(
    *,
    db: AsyncSession,
    account_id: int,
    role_payloads: list[dict],
) -> list[GameRole]:
    existing_result = await db.execute(
        select(GameRole)
        .where(GameRole.account_id == account_id)
        .order_by(GameRole.id.asc())
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
            await db.delete(role)

    await db.flush()
    return synced_roles
