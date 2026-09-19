"""
米哈游账号管理 API
- 获取当前用户的所有米哈游账号列表
- 发起扫码登录（创建二维码会话）
- 删除账号
- 刷新 Cookie
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.account import MihoyoAccount, GameRole
from app.models.task_log import TaskLog
from app.services.user_activity import require_active_user
from app.services.user_operations import user_operation
from app.services.account_operations import account_operation, load_current_account
from app.schemas.account import AccountResponse, AccountListResponse, LoginStateResponse, QrLoginStartResponse
from app.api.auth import get_current_user
from app.services.login_state import LoginStateService
from app.services.passport_login import PassportLoginService, passport_login_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/accounts", tags=["米哈游账号"])


class SmsLoginCaptchaRequest(BaseModel):
    """
    短信验证码发送请求。

    当前 Task 3 只负责把短信登录后端链路打通，不做账号落库。
    这里故意只收手机号和可选 aigis，避免把“发送验证码”和“保存账号”提前耦合，
    否则后续一旦风控参数变化，接口边界会被持久化逻辑一并拖着改。
    """

    mobile: str
    aigis: str | None = None


class SmsLoginVerifyRequest(BaseModel):
    """
    短信验证码校验请求。

    `action_type` 必须由“发送验证码”接口返回后原样回传；不要在前端或其他调用方自造，
    否则当官方后续调整动作标识时，会出现“验证码明明正确但登录始终失败”的隐蔽问题。
    """

    mobile: str
    captcha: str
    action_type: str
    aigis: str | None = None


def _has_high_privilege_auth(account: MihoyoAccount) -> bool:
    return bool(account.stoken_encrypted and account.stuid and account.mid)


def _is_legacy_cookie_only_account(account: MihoyoAccount) -> bool:
    return bool(account.cookie_encrypted and not _has_high_privilege_auth(account))


async def _build_account_response(
    *,
    db: AsyncSession,
    account: MihoyoAccount,
    roles: list[GameRole],
) -> AccountResponse:
    # 账号列表是前端判断“这个账号能不能继续作为正式登录入口使用”的唯一稳定协议面。
    # 这里必须把旧 Cookie-only 账号统一收口为升级语义，而不是信任库里历史残留的
    # `credential_status`。否则旧版本曾写入的 `valid/None` 会被原样透出，前端就会把
    # 实际只能依赖低权限网页登录 Cookie 的账号误判成“高权限凭据正常”或“尚未检查”。
    has_high_privilege_auth = _has_high_privilege_auth(account)
    upgrade_required = _is_legacy_cookie_only_account(account)
    credential_status = "reauth_required" if upgrade_required else account.credential_status

    return AccountResponse(
        id=account.id,
        user_id=account.user_id,
        nickname=account.nickname,
        mihoyo_uid=account.mihoyo_uid,
        has_high_privilege_auth=has_high_privilege_auth,
        credential_status=credential_status,
        credential_source=account.credential_source,
        upgrade_required=upgrade_required,
        cookie_status=account.cookie_status,
        last_cookie_check=account.last_cookie_check,
        last_refresh_attempt_at=account.last_refresh_attempt_at,
        last_refresh_status=account.last_refresh_status,
        last_refresh_message=account.last_refresh_message,
        reauth_notified_at=account.reauth_notified_at,
        created_at=account.created_at,
        game_roles=[
            {
                "id": r.id,
                "game_biz": r.game_biz,
                "game_uid": r.game_uid,
                "nickname": r.nickname,
                "region": r.region,
                "level": r.level,
                "is_enabled": r.is_enabled,
            }
            for r in roles
        ],
    )


@router.get("", response_model=AccountListResponse)
async def list_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的所有米哈游账号。"""
    result = await db.execute(
        select(MihoyoAccount)
        .where(MihoyoAccount.user_id == current_user.id)
        .order_by(MihoyoAccount.created_at.desc())
    )
    accounts = result.scalars().all()

    account_responses = []
    for acc in accounts:
        roles_result = await db.execute(
            select(GameRole).where(GameRole.account_id == acc.id)
        )
        roles = roles_result.scalars().all()
        resp = await _build_account_response(db=db, account=acc, roles=roles)
        account_responses.append(resp)

    return AccountListResponse(accounts=account_responses, total=len(account_responses))


@router.post("/qr-login", response_model=QrLoginStartResponse)
async def start_qr_login(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    发起官方 Passport 扫码登录会话。
    返回会话 ID 和短期一次性凭证，凭证仅通过 WebSocket 首帧提交。
    """
    with user_operation(current_user.id):
        await require_active_user(db, current_user.id)
        return QrLoginStartResponse(**passport_login_manager.issue_session(current_user.id))


@router.post("/sms-login/captcha")
async def create_sms_login_captcha(
    request: SmsLoginCaptchaRequest,
    current_user: User = Depends(get_current_user),
):
    """
    发送 Passport 短信登录验证码。

    当前接口只返回风控透传参数和动作标识，不直接创建账号。
    若在这里提前落库，会把“验证码发送成功”和“账号已完成高权限登录”混成同一个状态，
    让后续维护者很难判断失败到底发生在发送阶段还是凭据解析阶段。
    """
    _ = current_user
    service = PassportLoginService()
    return await service.create_login_captcha(request.mobile, aigis=request.aigis)


@router.post("/sms-login/verify")
async def verify_sms_login(
    request: SmsLoginVerifyRequest,
    current_user: User = Depends(get_current_user),
):
    """
    校验短信验证码并返回 Passport 根凭据。

    Task 3 到此为止只负责“拿到统一结构的登录结果”，
    持久化和工作 Cookie 补齐交给后续任务处理，避免当前接口越权承担多阶段职责。
    """
    _ = current_user
    service = PassportLoginService()
    return await service.login_by_mobile_captcha(
        mobile=request.mobile,
        captcha=request.captcha,
        action_type=request.action_type,
        aigis=request.aigis,
    )


@router.delete("/{account_id}")
async def delete_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """原子删除当前用户的账号、全部角色及签到日志；账号忙时返回 409。"""
    result = await db.execute(
        select(MihoyoAccount).where(
            MihoyoAccount.id == account_id,
            MihoyoAccount.user_id == current_user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    async with account_operation(db, account_id):
        account = await load_current_account(db, account_id)
        if account.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="账号不存在")
        # 显式按外键依赖顺序删除，包含没有角色 ID 的账号级日志
        await db.execute(delete(TaskLog).where(TaskLog.account_id == account_id))
        await db.execute(delete(GameRole).where(GameRole.account_id == account_id))
        await db.delete(account)
        await db.commit()
    return {"message": "账号已删除"}


@router.post("/{account_id}/refresh-cookie", response_model=QrLoginStartResponse)
async def refresh_cookie(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    重新发起指定账号的高权限扫码登录。
    返回新的 session_id，与 qr-login 流程一致。
    """
    with user_operation(current_user.id):
        await require_active_user(db, current_user.id)
        result = await db.execute(select(MihoyoAccount).where(
            MihoyoAccount.id == account_id,
            MihoyoAccount.user_id == current_user.id,
        ))
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        return QrLoginStartResponse(
            **passport_login_manager.issue_session(current_user.id, account_id),
            message="请重新扫码以更新高权限登录态",
        )


@router.post("/{account_id}/refresh-login-state", response_model=LoginStateResponse)
async def refresh_login_state(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    手动执行一次登录态校验。

    当前实现只校验网页登录 Cookie 是否仍可用：
    - 这里不会再尝试自动续期
    - `/refresh-cookie` 明确表示进入重新扫码流程
    """
    result = await db.execute(
        select(MihoyoAccount).where(
            MihoyoAccount.id == account_id,
            MihoyoAccount.user_id == current_user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    service = LoginStateService(db)
    return await service.refresh_account_login_state(account)
