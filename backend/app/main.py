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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.config import detect_setting_source, settings
from app.database import init_db, async_session
from app.models.account import MihoyoAccount
from app.services.browser import browser_manager
from app.services.qr_login import qr_login_manager
from app.services.scheduler import scheduler_service
from app.services.checkin import CheckinService
from app.services.account_role_sync import sync_account_roles
from app.services.login_state import LoginStateService
from app.services.system_settings import SystemSettingsService
from app.utils.crypto import encrypt_cookie, encrypt_text
from app.utils.timezone import utc_now_naive

# Windows 下如果事件循环策略退回到 SelectorEventLoop，`asyncio.create_subprocess_exec`
# 会直接抛 `NotImplementedError`，而扫码登录对 Playwright 子进程是硬依赖。
# 这里在应用导入阶段统一切到 Proactor，避免“接口都正常，唯独二维码通道必挂”的隐性环境问题。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# 配置日志
# 这里的 %(asctime)s 走的是进程所在系统时区，而不是 settings.APP_TIMEZONE。
# 因此 Docker 场景下若希望业务日志与 Uvicorn 访问日志都显示东八区，
# 必须在容器层统一 TZ；不要只改这里的格式串，否则会造成“前端时间是东八区、docker logs 还是 UTC”的割裂。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
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
from app.api.assets import router as assets_router
from app.api.gacha import router as gacha_router
from app.api.health_center import router as health_center_router
from app.api.redeem import router as redeem_router
from app.api.tasks import router as tasks_router
from app.api.logs import router as logs_router
from app.api.admin import router as admin_router

app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(assets_router)
app.include_router(gacha_router)
app.include_router(health_center_router)
app.include_router(redeem_router)
app.include_router(tasks_router)
app.include_router(logs_router)
app.include_router(admin_router)


@app.websocket("/ws/qr/{session_id}")
async def qr_login_websocket(
    websocket: WebSocket,
    session_id: str,
    user_id: int = Query(...),
    account_id: int | None = Query(default=None),
):
    """
    扫码登录 WebSocket 端点。

    流程：
    1. 前端连接 WebSocket
    2. 后端启动网页登录二维码会话并推送二维码图片
    3. 轮询扫码状态并向前端同步进度
    4. 登录成功后提取网页登录 Cookie 并保存
    5. 保存后返回成功结果，不再附带已下线能力的额外探测状态
    """
    await websocket.accept()

    session = qr_login_manager.create_session(session_id, user_id)

    try:
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
                cookie_str = await session.extract_cookies()
                if not cookie_str:
                    await websocket.send_json({
                        "type": "error",
                        "message": session.error_message or "提取 Cookie 失败",
                    })
                    return

                async with async_session() as db:
                    token_info = LoginStateService.parse_login_tokens(cookie_str)
                    if account_id is not None:
                        account_result = await db.execute(
                            select(MihoyoAccount).where(
                                MihoyoAccount.id == account_id,
                                MihoyoAccount.user_id == user_id,
                            )
                        )
                        account = account_result.scalar_one_or_none()
                        if account is None:
                            await websocket.send_json({
                                "type": "error",
                                "message": "待刷新的账号不存在",
                            })
                            return
                    else:
                        account = MihoyoAccount(user_id=user_id)
                        db.add(account)
                        await db.flush()

                    account.cookie_encrypted = encrypt_cookie(cookie_str)
                    account.cookie_status = "valid"
                    account.stoken_encrypted = (
                        encrypt_text(token_info["stoken"]) if token_info["stoken"] else None
                    )
                    account.stuid = token_info["stuid"]
                    account.mid = token_info["mid"]
                    account.last_cookie_check = utc_now_naive()
                    account.cookie_token_updated_at = utc_now_naive()
                    account.last_refresh_status = "success"
                    # 用户当前能稳定依赖的是“网页登录态已更新”这件事。
                    # 即便底层偶发拿到额外字段，也不再把它包装成自动续期或 App 凭据能力，
                    # 以免后续维护者再次把不可稳定获得的数据误判成正式支持范围。
                    account.last_refresh_message = "登录成功并已更新网页登录态"
                    account.last_refresh_attempt_at = utc_now_naive()
                    account.reauth_notified_at = None

                    checkin_service = CheckinService(db)
                    roles = await checkin_service.fetch_game_roles(cookie_str)
                    await sync_account_roles(
                        db=db,
                        account_id=account.id,
                        role_payloads=roles,
                    )

                    if roles:
                        account.nickname = roles[0].get("nickname", "")
                        account.mihoyo_uid = roles[0].get("game_uid", "")
                    elif session.account_mihoyo_uid:
                        account.mihoyo_uid = session.account_mihoyo_uid

                    await db.commit()
                    await db.refresh(account)

                await websocket.send_json({
                    "type": "success",
                    "message": "登录成功",
                    "account_id": account.id,
                    "roles_count": len(roles),
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

    except WebSocketDisconnect:
        logger.info(f"[{session_id}] WebSocket 连接断开")
    except Exception:
        logger.exception("[%s] WebSocket 错误", session_id)
        try:
            await websocket.send_json({"type": "error", "message": "二维码登录通道异常，请关闭页面后重试"})
        except Exception:
            pass
    finally:
        await qr_login_manager.remove_session(session_id)


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


