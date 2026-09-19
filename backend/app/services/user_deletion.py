"""永久删除用户及其业务数据，不保留软删除记录"""

import json
import logging

from fastapi import HTTPException
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import GameRole, MihoyoAccount
from app.models.admin_operation_log import AdminOperationLog
from app.models.task_log import TaskConfig, TaskLog
from app.models.user import User
from app.services.notifier import notification_service
from app.services.passport_login import passport_login_manager
from app.services.scheduler import scheduler_service
from app.services.user_operations import user_deletion

logger = logging.getLogger(__name__)


class UserDeletionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def delete(self, user_id: int) -> dict:
        with user_deletion(user_id):
            async with scheduler_service.user_schedule_lock(user_id):
                try:
                    # 当前读避开管理员鉴权建立的旧事务快照
                    user = (await self.db.execute(
                        select(User).where(User.id == user_id).with_for_update()
                        .execution_options(populate_existing=True)
                    )).scalar_one_or_none()
                    deleted = user is not None
                    if deleted:
                        await self._delete_records(user_id)
                    await self.db.commit()
                except BaseException:
                    await self.db.rollback()
                    raise

                # 数据库提交后清理可重入的运行态；即使用户已不存在，重试仍会走完这里
                failed = False
                for cleanup in (
                    scheduler_service.remove_user_runtime,
                    passport_login_manager.remove_user_sessions,
                ):
                    try:
                        await cleanup(user_id)
                    except Exception:
                        failed = True
                        # 不输出异常对象，避免底层错误带出历史凭据或个人信息
                        logger.error("删除用户后的运行态清理失败: %s", cleanup.__name__)
                notification_service.clear_user_notifications(user_id)
                if failed:
                    raise HTTPException(
                        status_code=503,
                        detail="用户数据已删除，但运行态清理未完成，请再次点击删除重试清理",
                    )
                return {
                    "message": "用户已永久删除" if deleted else "用户已不存在，运行态已清理",
                    "deleted": deleted,
                }

    async def _delete_records(self, user_id: int):
        account_ids = list((await self.db.scalars(
            select(MihoyoAccount.id).where(MihoyoAccount.user_id == user_id).with_for_update()
        )).all())
        role_ids = select(GameRole.id).where(GameRole.account_id.in_(account_ids))
        # 同时覆盖账号级日志及角色引用，先删除子记录再删除父记录
        await self.db.execute(delete(TaskLog).where(or_(
            TaskLog.account_id.in_(account_ids), TaskLog.game_role_id.in_(role_ids),
        )))
        await self.db.execute(delete(GameRole).where(GameRole.account_id.in_(account_ids)))
        await self.db.execute(delete(MihoyoAccount).where(MihoyoAccount.user_id == user_id))
        await self.db.execute(delete(TaskConfig).where(TaskConfig.user_id == user_id))

        # 两个用户同时删除时按同一顺序锁定共享群发记录，避免 JSON 更新覆盖彼此
        logs = (await self.db.scalars(
            select(AdminOperationLog).where(
                AdminOperationLog.failure_details_json.is_not(None),
                AdminOperationLog.failure_details_json != "[]",
            ).order_by(AdminOperationLog.id).with_for_update()
            .execution_options(populate_existing=True)
        )).all()
        for log in logs:
            if log.operator_user_id == user_id:
                continue
            try:
                details = json.loads(log.failure_details_json)
                if not isinstance(details, list) or any(not isinstance(item, dict) for item in details):
                    raise ValueError()
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=409,
                    detail="历史群发失败记录损坏，无法完整清理；本次删除已回滚，请先修复记录",
                ) from None
            remaining = [item for item in details if str(item.get("user_id")) != str(user_id)]
            if len(remaining) != len(details):
                log.failure_details_json = json.dumps(remaining, ensure_ascii=False)
        await self.db.flush()
        await self.db.execute(delete(AdminOperationLog).where(AdminOperationLog.operator_user_id == user_id))
        await self.db.execute(delete(User).where(User.id == user_id))
