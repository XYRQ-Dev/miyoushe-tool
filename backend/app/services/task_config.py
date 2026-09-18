"""
签到调度配置服务。

这里把“确保用户存在 TaskConfig”的逻辑集中管理，避免注册、设置页和调度器启动各自写一套：
- 任一入口忘记补配置，都会导致“用户以为自动签到默认开启，实际数据库里没有调度记录”
- 后续若默认 cron 或启用策略需要调整，也必须保持所有入口语义一致
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task_log import TaskConfig
from app.models.user import User

# 默认值继续与当前产品文案保持一致：每天 06:00 自动签到。
# 这里故意不直接读取 settings.DEFAULT_CRON_HOUR / MINUTE，
# 因为那组配置当前并不等价于现网界面展示和数据库默认值，贸然切换会造成行为漂移。
DEFAULT_TASK_CRON_EXPR = "0 6 * * *"


async def get_or_create_task_config(
    db: AsyncSession,
    user_id: int,
    *,
    auto_commit: bool = False,
) -> tuple[TaskConfig, bool]:
    """获取用户调度配置；若不存在则补建默认配置。"""
    result = await db.execute(select(TaskConfig).where(TaskConfig.user_id == user_id))
    config = result.scalar_one_or_none()
    if config is not None:
        return config, False

    config = TaskConfig(
        user_id=user_id,
        cron_expr=DEFAULT_TASK_CRON_EXPR,
        is_enabled=True,
    )
    db.add(config)
    await db.flush()

    if auto_commit:
        await db.commit()
        await db.refresh(config)

    return config, True


async def ensure_all_users_have_task_config(db: AsyncSession) -> int:
    """
    为所有缺失调度配置的用户补建默认 TaskConfig。

    旧版本用户往往已经有账号和签到数据，但从未打开过设置页；
    如果这里不做启动期自愈，这些用户就会永久处于“功能宣传存在、调度实际缺席”的黑盒状态。
    """
    user_ids = set((await db.execute(select(User.id))).scalars().all())
    configured_user_ids = set((await db.execute(select(TaskConfig.user_id))).scalars().all())

    missing_user_ids = sorted(user_ids - configured_user_ids)
    for user_id in missing_user_ids:
        db.add(
            TaskConfig(
                user_id=user_id,
                cron_expr=DEFAULT_TASK_CRON_EXPR,
                is_enabled=True,
            )
        )

    if missing_user_ids:
        await db.commit()

    return len(missing_user_ids)
