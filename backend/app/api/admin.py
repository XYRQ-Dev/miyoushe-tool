"""
管理员接口
- 查看所有用户
- 禁用/启用用户
- 查看系统状态
- 维护系统级 SMTP 发信配置
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.account import MihoyoAccount, GameRole
from app.models.task_log import TaskLog
from app.schemas.system_setting import AdminEmailSettingsResponse, AdminEmailSettingsUpdate
from app.schemas.user import UserResponse
from app.api.auth import require_admin
from app.services.system_settings import SystemSettingsService
from app.utils.crypto import encrypt_text

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


@router.get("/system-settings/email", response_model=AdminEmailSettingsResponse)
async def get_email_settings(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    获取系统邮件配置（仅管理员）。

    这里不会回显密码明文，只返回“是否已配置”，避免前端、抓包或日志误泄露敏感信息。
    """
    config = await SystemSettingsService(db).get_or_create()
    return AdminEmailSettingsResponse(
        smtp_enabled=bool(config.smtp_enabled),
        smtp_host=config.smtp_host or "",
        smtp_port=config.smtp_port or 465,
        smtp_user=config.smtp_user or "",
        smtp_use_ssl=bool(config.smtp_use_ssl),
        smtp_sender_name=config.smtp_sender_name or "",
        smtp_sender_email=config.smtp_sender_email or "",
        smtp_password_configured=bool(config.smtp_password_encrypted),
    )


@router.put("/system-settings/email", response_model=AdminEmailSettingsResponse)
async def update_email_settings(
    payload: AdminEmailSettingsUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    更新系统邮件配置（仅管理员）。

    约束：
    - 密码留空表示“不修改”
    - 若启用 SMTP，则主机/用户名必须具备基础可用性
    """
    if payload.smtp_enabled and (not payload.smtp_host.strip() or not payload.smtp_user.strip()):
        raise HTTPException(status_code=400, detail="启用邮件发送时必须填写 SMTP 主机和用户名")

    config = await SystemSettingsService(db).get_or_create()
    config.smtp_enabled = payload.smtp_enabled
    config.smtp_host = payload.smtp_host.strip()
    config.smtp_port = payload.smtp_port
    config.smtp_user = payload.smtp_user.strip()
    config.smtp_use_ssl = payload.smtp_use_ssl
    config.smtp_sender_name = payload.smtp_sender_name.strip()
    config.smtp_sender_email = payload.smtp_sender_email.strip()

    if payload.smtp_password is not None and payload.smtp_password != "":
        config.smtp_password_encrypted = encrypt_text(payload.smtp_password)

    db.add(config)
    await db.commit()
    await db.refresh(config)

    return AdminEmailSettingsResponse(
        smtp_enabled=bool(config.smtp_enabled),
        smtp_host=config.smtp_host or "",
        smtp_port=config.smtp_port or 465,
        smtp_user=config.smtp_user or "",
        smtp_use_ssl=bool(config.smtp_use_ssl),
        smtp_sender_name=config.smtp_sender_name or "",
        smtp_sender_email=config.smtp_sender_email or "",
        smtp_password_configured=bool(config.smtp_password_encrypted),
    )
