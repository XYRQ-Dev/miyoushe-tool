"""
管理员接口
- 查看所有用户
- 禁用/启用用户
- 查看系统状态
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.account import MihoyoAccount, GameRole
from app.models.task_log import TaskLog
from app.schemas.user import UserResponse
from app.api.auth import require_admin

router = APIRouter(prefix="/api/admin", tags=["管理员"])


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取所有用户列表（仅管理员）"""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.put("/users/{user_id}/toggle-active")
async def toggle_user_active(
    user_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """启用/禁用用户（仅管理员）"""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能禁用自己的账号")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.is_active = not user.is_active
    await db.commit()
    return {"message": f"用户已{'启用' if user.is_active else '禁用'}", "is_active": user.is_active}


@router.get("/stats")
async def get_system_stats(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取系统统计信息（仅管理员）"""
    user_count = (await db.execute(select(func.count(User.id)))).scalar()
    account_count = (await db.execute(select(func.count(MihoyoAccount.id)))).scalar()
    role_count = (await db.execute(select(func.count(GameRole.id)))).scalar()
    log_count = (await db.execute(select(func.count(TaskLog.id)))).scalar()

    return {
        "user_count": user_count,
        "account_count": account_count,
        "role_count": role_count,
        "log_count": log_count,
    }
