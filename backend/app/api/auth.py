"""
用户认证 API
- 注册：首个用户自动成为管理员
- 登录：返回 JWT access_token + refresh_token
- 获取当前用户信息
- 刷新 token
"""

from datetime import timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError
from passlib.context import CryptContext

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.services.user_operations import user_operation
from app.services.user_activity import require_active_user
from app.services.task_config import get_or_create_task_config
from app.services.scheduler import scheduler_service
from app.services.menu_visibility import resolve_visible_menu_keys
from app.services.system_settings import SystemSettingsService
from app.schemas.system_setting import RegisterOptionsResponse
from app.schemas.user import (
    UserCreate, UserLogin, UserResponse, UserUpdate,
    TokenResponse,
)
from app.utils.timezone import utc_now

router = APIRouter(prefix="/api/auth", tags=["认证"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security_scheme = HTTPBearer()


def create_token(data: dict, expires_delta: timedelta) -> str:
    """生成 JWT Token"""
    to_encode = data.copy()
    to_encode["exp"] = utc_now() + expires_delta
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_token_pair(user: User) -> TokenResponse:
    """登录与刷新共用的令牌签发入口"""
    return TokenResponse(
        access_token=create_token(
            {"user_id": user.id, "username": user.username, "role": user.role, "type": "access"},
            timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        ),
        refresh_token=create_token(
            {"user_id": user.id, "type": "refresh"},
            timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        ),
    )


def decode_token_user_id(token: str, expected_type: Literal["access", "refresh"]) -> int:
    """校验令牌用途及必要身份字段，不接受旧的无类型访问令牌"""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM],
            options={"require_exp": True},
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="认证凭据已过期或无效")
    user_id = payload.get("user_id")
    # bool 也是 int 的子类，必须排除，避免异常标识被数据库隐式转换
    if payload.get("type") != expected_type or type(user_id) is not int or user_id <= 0:
        raise HTTPException(status_code=401, detail="无效的认证凭据")
    return user_id


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """从请求头中的 JWT 解析并验证当前用户"""
    user_id = decode_token_user_id(credentials.credentials, "access")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")
    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """要求管理员权限"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user


async def build_user_response(*, user: User, db: AsyncSession) -> UserResponse:
    settings = await SystemSettingsService(db).get_or_create()
    return UserResponse.model_validate(
        {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "email_notify": user.email_notify,
            "notify_on": user.notify_on,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "visible_menu_keys": resolve_visible_menu_keys(
                role=user.role,
                raw_value=settings.menu_visibility_json,
            ),
        }
    )


@router.get("/register-options", response_model=RegisterOptionsResponse)
async def get_register_options(db: AsyncSession = Depends(get_db)):
    """
    公开注册探测。只返回是否需要邀请码，不回传邀请码本身。
    """
    return await SystemSettingsService(db).get_register_options()


@router.post("/register", response_model=UserResponse)
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)):
    """
    用户注册
    - 首个注册用户自动成为管理员
    - 用户名不可重复
    - 系统开启邀请码后，后续注册必须携带正确邀请码
    """
    # 邀请码必须在用户名查重之前校验，避免未获邀请求通过“用户名已存在”枚举账号。
    try:
        await SystemSettingsService(db).assert_register_invite_allowed(data.invite_code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # 检查用户名是否已存在
    existing = await db.execute(select(User).where(User.username == data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 首个用户自动成为管理员
    count_result = await db.execute(select(func.count(User.id)))
    user_count = count_result.scalar()
    role = "admin" if user_count == 0 else "user"

    user = User(
        username=data.username,
        password_hash=pwd_context.hash(data.password),
        role=role,
    )
    db.add(user)
    await db.flush()

    with user_operation(user.id):
        config, _ = await get_or_create_task_config(db, user.id)
        await db.commit()
        # 用户与默认配置提交后才能注册任务；运行态失败不回滚注册，读取配置时可重试
        await scheduler_service.ensure_user_schedule(config, user_active=user.is_active)
        await db.refresh(user)
        return await build_user_response(user=user, db=db)


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    """用户登录，返回 JWT Token 对"""
    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()

    if not user or not pwd_context.verify(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    return create_token_pair(user)


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户信息"""
    return await build_user_response(user=current_user, db=db)


@router.put("/me", response_model=UserResponse)
async def update_me(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新当前用户设置（邮箱、通知偏好）"""
    with user_operation(current_user.id):
        await require_active_user(db, current_user.id)
        if data.email is not None:
            current_user.email = data.email
        if data.email_notify is not None:
            current_user.email_notify = data.email_notify
        if data.notify_on is not None:
            current_user.notify_on = data.notify_on

        await db.commit()
        await db.refresh(current_user)
        return await build_user_response(user=current_user, db=db)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    credentials: HTTPAuthorizationCredentials = Security(security_scheme),
    db: AsyncSession = Depends(get_db),
):
    """使用 refresh_token 换取新的 token 对"""
    user_id = decode_token_user_id(credentials.credentials, "refresh")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")

    return create_token_pair(user)
