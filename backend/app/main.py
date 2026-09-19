"""
FastAPI 应用入口
- 注册所有路由
- 初始化数据库
- 启动任务调度器
- WebSocket 端点（二维码推送）
- CORS 跨域配置
- 静态文件（前端）
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import detect_setting_source, settings
from app.database import init_db, async_session
from app.models.account import MihoyoAccount
from app.models.user import User
from app.services.account_credentials import AccountCredentialService, AccountUidMismatchError
from app.services.account_role_sync import refresh_account_roles
from app.services.browser import browser_manager
from app.services.passport_login import PassportQrLoginSession, QrAuthorizationError, passport_login_manager
from app.services.scheduler import scheduler_service
from app.services.system_settings import SystemSettingsService
from app.utils.timezone import configure_shanghai_logging

# Windows 下如果事件循环策略退回到 SelectorEventLoop，`asyncio.create_subprocess_exec`
# 会直接抛 `NotImplementedError`，而扫码登录对 Playwright 子进程是硬依赖。
# 这里在应用导入阶段统一切到 Proactor，避免“接口都正常，唯独二维码通道必挂”的隐性环境问题。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# 业务日志和 Uvicorn 访问日志的墙上时间一律固定东八区，不跟随宿主时区。
configure_shanghai_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # Uvicorn 可能在导入后才挂上自己的 handler；启动时再刷一次，避免访问日志退回宿主时区。
    configure_shanghai_logging()
    encryption_key_source = detect_setting_source("ENCRYPTION_KEY")
    # 这里必须在启动期显式提示 ENCRYPTION_KEY 是否为固定来源。
    # 否则当服务重启后旧密文突然无法解密时，排障现场只会看到“Cookie 损坏”，
    # 但根因其实是密钥仍在走随机默认值，和业务登录链路无关。
    logger.info(
        "配置诊断: ENCRYPTION_KEY source=%s persistent=%s",
        encryption_key_source,
        encryption_key_source != "generated_default",
    )
    if encryption_key_source == "generated_default":
        logger.warning(
            "ENCRYPTION_KEY 尚未固定；当前进程使用运行期随机默认值，服务重启后旧 Cookie 与旧敏感密文可能无法解密"
        )

    logger.info("正在初始化数据库...")
    await init_db()
    logger.info("数据库初始化完成")

    logger.info("正在准备系统配置存储结构...")
    async with async_session() as db:
        # 登录态恢复、菜单守卫、签到配置都会读取 system_settings。
        # 若把旧库补表补列继续留在这些高频路径里，每次 `/auth/me` 都会触发 schema inspect；
        # 因此这里在启动阶段先做一次结构准备，把兼容成本收敛到冷启动。
        await SystemSettingsService(db).ensure_storage_ready()
    logger.info("系统配置存储结构准备完成")

    logger.info("正在启动任务调度器...")
    await scheduler_service.start()

    yield

    # 关闭时
    logger.info("正在关闭服务...")
    scheduler_service.stop()
    await browser_manager.close()
    logger.info("服务已关闭")


app = FastAPI(
    title=settings.APP_NAME,
    description="米游社自动签到 Web 管理平台",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 跨域配置（开发环境允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
from app.api.auth import router as auth_router
from app.api.accounts import router as accounts_router
from app.api.tasks import router as tasks_router
from app.api.logs import router as logs_router
from app.api.admin import router as admin_router

app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(tasks_router)
app.include_router(logs_router)
app.include_router(admin_router)


async def _check_qr_authorization(
    db: AsyncSession, session: PassportQrLoginSession, *, lock: bool = False,
) -> MihoyoAccount | None:
    """领取及保存时使用新事务核对服务端身份，保存时锁定授权对象。"""
    user_query = select(User).where(User.id == session.user_id, User.is_active.is_(True))
    if lock:
        user_query = user_query.with_for_update()
    if (await db.execute(user_query)).scalar_one_or_none() is None:
        raise QrAuthorizationError("用户已停用或不存在，请重新登录")
    if session.account_id is None:
        return None
    account_query = select(MihoyoAccount).where(
        MihoyoAccount.id == session.account_id,
        MihoyoAccount.user_id == session.user_id,
    )
    if lock:
        account_query = account_query.with_for_update()
    account = (await db.execute(account_query)).scalar_one_or_none()
    if account is None:
        raise QrAuthorizationError("待刷新的账号不存在或不属于当前用户")
    return account


@app.websocket("/ws/qr/{session_id}")
async def qr_login_websocket(
    websocket: WebSocket,
    session_id: str,
):
    """
    扫码登录 WebSocket 端点。

    流程：
    1. 前端首帧提交已认证 HTTP 入口签发的一次性凭证
    2. 后端创建官方 Passport 二维码并推送二维码图片
    3. 轮询扫码状态并向前端同步进度
    4. 重新核对授权后保存高权限根凭据，并由凭据服务尝试补齐工作 Cookie
    5. 提交成功后推送绑定结果
    """
    await websocket.accept()

    session = None

    try:
        try:
            frame = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        except (asyncio.TimeoutError, ValueError, RuntimeError):
            raise QrAuthorizationError("未收到有效扫码凭证，请刷新页面后重新获取二维码") from None
        if (
            not isinstance(frame, dict)
            or frame.get("type") != "authenticate"
            or not isinstance(frame.get("credential"), str)
            or not 1 <= len(frame["credential"]) <= 128
        ):
            raise QrAuthorizationError("扫码协议已更新，请刷新页面后重试")
        session = passport_login_manager.claim_session(session_id, frame["credential"])
        async with async_session() as db:
            await _check_qr_authorization(db, session)
        await websocket.send_json({"type": "status", "status": "initializing"})
        await session.start()

        qr_image = await session.get_qr_image()
        if qr_image:
            await websocket.send_json({
                "type": "qr_code",
                "image": qr_image,
                "status": "qr_ready",
            })
        else:
            await websocket.send_json({
                "type": "error",
                "message": session.error_message or "获取二维码失败",
            })
            return

        max_polls = 90
        for _ in range(max_polls):
            await asyncio.sleep(2)
            status = await session.poll_login_status()
            await websocket.send_json({"type": "status", "status": status})

            if status == "success":
                login_result = session.get_login_result()
                if not login_result:
                    await websocket.send_json({
                        "type": "error",
                        "message": session.error_message or "解析官方登录结果失败",
                    })
                    return

                async with async_session() as db:
                    # 新事务重新检查并锁定用户与目标账号，避免等待扫码期间授权已变化
                    account = await _check_qr_authorization(db, session, lock=True)
                    if account is None:
                        account = MihoyoAccount(user_id=session.user_id)
                        db.add(account)
                        await db.flush()

                    # 登录成功后的字段写库、自愈补齐、工作 Cookie 重建必须统一走同一个服务入口。
                    # 如果继续在 WebSocket 成功分支手写一组字段，后续短信登录、自愈重建和旧账号升级
                    # 很快就会出现状态字段不一致的问题，维护者也无法再判断“哪个入口才是准绳”。
                    credential_service = AccountCredentialService(db)
                    credential_result = await credential_service.persist_login_result(account, login_result)
                    roles_result = {"roles_sync_status": "pending", "roles_count": None}
                    if credential_result["state"] == "valid":
                        roles_result = await refresh_account_roles(db=db, account=account)
                    else:
                        account.last_refresh_message = (
                            f"{account.last_refresh_message}；角色同步待重试，请先通过“校验登录态”恢复工作 Cookie"
                        )

                    await db.commit()
                    await db.refresh(account)

                await websocket.send_json({
                    "type": "success",
                    "message": f"账号已绑定；{account.last_refresh_message or '高权限根凭据已保存'}",
                    "account_id": account.id,
                    "roles_count": roles_result["roles_count"],
                    "roles_sync_status": roles_result["roles_sync_status"],
                })
                break

            if status == "failed":
                await websocket.send_json({
                    "type": "error",
                    "message": session.error_message or "登录失败",
                })
                break

            if status == "timeout":
                await websocket.send_json({
                    "type": "timeout",
                    "message": session.error_message or "扫码登录超时（3分钟），请重试",
                })
                break
        else:
            await websocket.send_json({
                "type": "timeout",
                "message": "扫码登录超时（3分钟），请重试",
            })

    except (QrAuthorizationError, AccountUidMismatchError) as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except (RuntimeError, WebSocketDisconnect):
            pass
    except WebSocketDisconnect:
        logger.info("扫码 WebSocket 连接断开")
    except Exception:
        # 异常内容可能包含上游票据或数据库参数，通道日志只记录固定事件
        logger.error("扫码 WebSocket 通道异常")
        try:
            await websocket.send_json({"type": "error", "message": "二维码登录通道异常，请关闭页面后重试"})
        except Exception:
            pass
    finally:
        if session is not None:
            await passport_login_manager.remove_session(session)
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect):
            pass


@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "app": settings.APP_NAME}


# 尝试挂载前端静态文件（生产环境使用）
import os
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """所有非 API 请求返回前端 index.html（SPA 路由）"""
        index_file = os.path.join(frontend_dist, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"detail": "前端文件未找到"}


