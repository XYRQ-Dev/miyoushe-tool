"""后台业务边界读取已提交的用户状态，不复用调用方的事务快照"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserInactiveError(HTTPException):
    def __init__(self):
        super().__init__(status_code=403, detail="用户已禁用或不存在，任务已停止")


async def is_user_active(db: AsyncSession, user_id: int) -> bool:
    # 独立短事务既能看见其他连接的新提交，也不会提交或回滚业务 session
    async with AsyncSession(bind=db.bind) as state_db:
        return bool(await state_db.scalar(select(User.is_active).where(User.id == user_id)))


async def require_active_user(db: AsyncSession, user_id: int) -> None:
    if not await is_user_active(db, user_id):
        raise UserInactiveError()
