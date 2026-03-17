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
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.config import settings
from app.database import init_db, async_session
from app.models.account import MihoyoAccount, GameRole
from app.services.browser import browser_manager
from app.services.qr_login import qr_login_manager
from app.services.scheduler import scheduler_service
from app.services.checkin import CheckinService
from app.services.login_state import LoginStateService
from app.utils.crypto import encrypt_cookie
from app.utils.timezone import utc_now_naive

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
    logger.info("正在初始化数据库...")
    await init_db()
    logger.info("数据库初始化完成")

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


@app.websocket("/ws/qr/{session_id}")
async def qr_login_websocket(
    websocket: WebSocket,
    session_id: str,
    user_id: int = Query(...),
    account_id: int | None = Query(default=None),
):
    """
    扫码登录 WebSocket 端点
    流程：
    1. 前端连接 WebSocket
    2. 后端启动 Playwright 会话，截取二维码图片
    3. 通过 WebSocket 推送 base64 二维码图片
    4. 轮询登录状态，推送状态更新
    5. 登录成功后提取 Cookie 并保存
    """
    await websocket.accept()

    session = qr_login_manager.create_session(session_id, user_id)

    try:
        # 推送初始状态
        await websocket.send_json({"type": "status", "status": "initializing"})

        # 启动浏览器会话
        await session.start()

        # 获取二维码
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

        # 轮询登录状态（最多 3 分钟）
        max_polls = 90  # 每 2 秒一次，共 3 分钟
        for _ in range(max_polls):
            await asyncio.sleep(2)

            status = await session.poll_login_status()
            await websocket.send_json({"type": "status", "status": status})

            if status == "success":
                # 登录成功，提取 Cookie
                cookie_str = await session.extract_cookies()
                if cookie_str:
                    # 保存到数据库
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
                            old_roles = await db.execute(
                                select(GameRole).where(GameRole.account_id == account.id)
                            )
                            for role in old_roles.scalars().all():
                                await db.delete(role)
                        else:
                            account = MihoyoAccount(user_id=user_id)
                            db.add(account)
                            await db.flush()

                        account.cookie_encrypted = encrypt_cookie(cookie_str)
                        account.cookie_status = "valid"
                        account.stoken_encrypted = (
                            encrypt_cookie(token_info["stoken"]) if token_info["stoken"] else None
                        )
                        account.stuid = token_info["stuid"]
                        account.mid = token_info["mid"]
                        account.last_cookie_check = utc_now_naive()
                        account.cookie_token_updated_at = utc_now_naive()
                        account.last_refresh_status = "success"
                        account.last_refresh_message = "登录成功并已更新登录态维护凭据"
                        account.last_refresh_attempt_at = utc_now_naive()
                        account.reauth_notified_at = None

                        # 获取并保存游戏角色
                        checkin_service = CheckinService(db)
                        roles = await checkin_service.fetch_game_roles(cookie_str)
                        for role_data in roles:
                            role = GameRole(
                                account_id=account.id,
                                game_biz=role_data.get("game_biz", ""),
                                game_uid=role_data.get("game_uid", ""),
                                nickname=role_data.get("nickname", ""),
                                region=role_data.get("region", ""),
                                level=role_data.get("level", 0),
                            )
                            db.add(role)

                        # 更新账号昵称
                        if roles:
                            account.nickname = roles[0].get("nickname", "")
                            account.mihoyo_uid = roles[0].get("game_uid", "")

                        await db.commit()
                        await db.refresh(account)

                    await websocket.send_json({
                        "type": "success",
                        "message": "登录成功",
                        "account_id": account.id,
                        "roles_count": len(roles),
                    })
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": "提取 Cookie 失败",
                    })
                break

            elif status == "failed":
                await websocket.send_json({
                    "type": "error",
                    "message": session.error_message or "登录失败",
                })
                break

        else:
            # 超时
            await websocket.send_json({
                "type": "timeout",
                "message": "扫码登录超时（3分钟），请重试",
            })

    except WebSocketDisconnect:
        logger.info(f"[{session_id}] WebSocket 连接断开")
    except Exception as e:
        logger.error(f"[{session_id}] WebSocket 错误: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
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
