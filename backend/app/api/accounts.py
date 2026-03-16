"""
米哈游账号管理 API
- 获取当前用户的所有米哈游账号列表
- 发起扫码登录（创建 Playwright 会话）
- 删除账号
- 刷新 Cookie
"""

import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import User
from app.models.account import MihoyoAccount, GameRole
from app.schemas.account import AccountResponse, AccountListResponse, QrLoginStartResponse
from app.api.auth import get_current_user
from app.services.qr_login import QrLoginManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/accounts", tags=["米哈游账号"])


@router.get("", response_model=AccountListResponse)
async def list_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的所有米哈游账号"""
    result = await db.execute(
        select(MihoyoAccount)
        .where(MihoyoAccount.user_id == current_user.id)
        .order_by(MihoyoAccount.created_at.desc())
    )
    accounts = result.scalars().all()

    # 加载每个账号的游戏角色
    account_responses = []
    for acc in accounts:
        roles_result = await db.execute(
            select(GameRole).where(GameRole.account_id == acc.id)
        )
        roles = roles_result.scalars().all()
        resp = AccountResponse(
            id=acc.id,
            user_id=acc.user_id,
            nickname=acc.nickname,
            mihoyo_uid=acc.mihoyo_uid,
            cookie_status=acc.cookie_status,
            last_cookie_check=acc.last_cookie_check,
            created_at=acc.created_at,
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
        account_responses.append(resp)

    return AccountListResponse(accounts=account_responses, total=len(account_responses))


@router.post("/qr-login", response_model=QrLoginStartResponse)
async def start_qr_login(current_user: User = Depends(get_current_user)):
    """
    发起扫码登录会话
    返回 session_id，前端通过 WebSocket 连接获取二维码图片
    """
    session_id = str(uuid.uuid4())
    return QrLoginStartResponse(session_id=session_id)


@router.delete("/{account_id}")
async def delete_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除米哈游账号及其关联的游戏角色"""
    result = await db.execute(
        select(MihoyoAccount).where(
            MihoyoAccount.id == account_id,
            MihoyoAccount.user_id == current_user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    # 删除关联的游戏角色
    roles = await db.execute(
        select(GameRole).where(GameRole.account_id == account_id)
    )
    for role in roles.scalars().all():
        await db.delete(role)

    await db.delete(account)
    await db.commit()
    return {"message": "账号已删除"}


@router.post("/{account_id}/refresh-cookie")
async def refresh_cookie(
    account_id: int,
    current_user: User = Depends(get_current_user),
):
    """
    刷新指定账号的 Cookie（重新扫码）
    返回新的 session_id，与 qr-login 流程一致
    """
    session_id = str(uuid.uuid4())
    return QrLoginStartResponse(
        session_id=session_id,
        message="请重新扫码以刷新 Cookie",
    )
