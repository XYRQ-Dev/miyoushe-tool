"""
管理员接口
- 查看所有用户
- 禁用/启用用户
- 查看系统状态
- 维护系统级 SMTP 发信配置
- 维护注册邀请码
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.account import MihoyoAccount, GameRole
from app.models.task_log import TaskConfig, TaskLog
from app.schemas.system_setting import (
    AdminEmailSettingsResponse,
    AdminEmailSettingsUpdate,
    AdminInviteCodeSettingsResponse,
    AdminInviteCodeSettingsUpdate,
    AdminMenuVisibilityResponse,
    AdminMenuVisibilityUpdate,
)
from app.schemas.admin_notification import (
    AdminBroadcastEmailRequest,
    AdminBroadcastEmailResponse,
)
from app.schemas.user import UserResponse
from app.api.auth import require_admin
from app.services.admin_broadcast import AdminBroadcastService
from app.services.system_settings import SystemSettingsService
from app.services.scheduler import scheduler_service
from app.services.user_deletion import UserDeletionService
from app.services.user_operations import user_operation
from app.services.user_activity import require_active_user
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

    with user_operation(user_id):
        return await _toggle_user_active(user_id, db)


async def _toggle_user_active(user_id: int, db: AsyncSession):
    async with scheduler_service.user_schedule_lock(user_id):
        result = await db.execute(
            select(User).where(User.id == user_id).with_for_update()
            .execution_options(populate_existing=True)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        config = (await db.execute(
            select(TaskConfig).where(TaskConfig.user_id == user_id).with_for_update()
            .execution_options(populate_existing=True)
        )).scalar_one_or_none()
        user.is_active = not user.is_active
        is_active = user.is_active
        await db.commit()
        try:
            await scheduler_service.sync_user_activity(user_id, config, user_active=is_active)
        except Exception as exc:
            # 已提交状态不得回滚成启用，也不能返回完全成功或让客户端自动重试切换
            raise HTTPException(
                status_code=503,
                detail=f"用户已{'启用' if is_active else '禁用'}，但调度同步失败；请刷新用户列表，勿重复切换。管理员需检查调度日志并恢复运行态",
            ) from exc
    return {"message": f"用户已{'启用' if is_active else '禁用'}", "is_active": is_active}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """永久删除其他用户及关联业务数据；重复请求会重试运行态清理"""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    with user_operation(admin.id):
        await require_active_user(db, admin.id)
        return await UserDeletionService(db).delete(user_id)


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


@router.get("/system-settings/invite-code", response_model=AdminInviteCodeSettingsResponse)
async def get_invite_code_settings(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    获取注册邀请码配置（仅管理员）。

    这里会回传当前邀请码明文，方便管理员复制给新用户；库内仍是加密存储。
    """
    del admin
    return await SystemSettingsService(db).get_invite_code_settings()


@router.put("/system-settings/invite-code", response_model=AdminInviteCodeSettingsResponse)
async def update_invite_code_settings(
    payload: AdminInviteCodeSettingsUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    更新注册邀请码配置（仅管理员）。

    开启时必须填写合法邀请码；关闭时允许清空。
    """
    del admin
    try:
        return await SystemSettingsService(db).update_invite_code_settings(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/menu-visibility", response_model=AdminMenuVisibilityResponse)
async def get_menu_visibility(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    del admin
    return await SystemSettingsService(db).get_menu_visibility()


@router.put("/menu-visibility", response_model=AdminMenuVisibilityResponse)
async def update_menu_visibility(
    payload: AdminMenuVisibilityUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    del admin
    try:
        return await SystemSettingsService(db).update_menu_visibility(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/notifications/broadcast-email", response_model=AdminBroadcastEmailResponse)
async def send_broadcast_email(
    payload: AdminBroadcastEmailRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    发送管理员公告邮件。

    这里发的是系统级公告，不是用户个人签到通知，因此收件人只按“是否启用 + 是否绑定邮箱”筛选，
    不能再受用户个人 `email_notify` / `notify_on` 偏好控制。
    """
    try:
        return await AdminBroadcastService(db).broadcast_email(admin=admin, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
