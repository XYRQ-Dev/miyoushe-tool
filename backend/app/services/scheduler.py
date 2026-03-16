"""
任务调度服务
使用 APScheduler 实现定时签到和 Cookie 过期检测
"""

import logging
import random
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.user import User
from app.models.account import MihoyoAccount
from app.models.task_log import TaskConfig
from app.services.checkin import CheckinService

logger = logging.getLogger(__name__)


class SchedulerService:
    """调度服务，管理所有用户的定时签到任务"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._started = False

    async def start(self):
        """启动调度器并加载所有用户的调度配置"""
        if self._started:
            return

        self.scheduler.start()
        self._started = True
        logger.info("任务调度器已启动")

        # 加载所有用户的调度配置
        await self._load_all_schedules()

        # 添加 Cookie 过期检测任务（每天凌晨 3 点执行）
        self.scheduler.add_job(
            self._check_cookies,
            CronTrigger(hour=3, minute=0),
            id="cookie_check",
            replace_existing=True,
        )
        logger.info("Cookie 过期检测任务已注册（每天 03:00）")

    async def _load_all_schedules(self):
        """从数据库加载所有启用的调度配置"""
        async with async_session() as db:
            result = await db.execute(
                select(TaskConfig).where(TaskConfig.is_enabled == True)
            )
            configs = result.scalars().all()

            for config in configs:
                await self._add_job(config.user_id, config)

            logger.info(f"已加载 {len(configs)} 个用户的调度配置")

    async def _add_job(self, user_id: int, config: TaskConfig):
        """为指定用户添加签到定时任务"""
        job_id = f"checkin_user_{user_id}"

        try:
            # 解析 cron 表达式（格式：分 时 日 月 周）
            parts = config.cron_expr.strip().split()
            if len(parts) != 5:
                logger.warning(f"用户 {user_id} 的 cron 表达式无效: {config.cron_expr}")
                return

            trigger = CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
            )

            self.scheduler.add_job(
                self._execute_checkin,
                trigger,
                id=job_id,
                replace_existing=True,
                args=[user_id],
            )
            logger.info(f"用户 {user_id} 的签到任务已注册: {config.cron_expr}")

        except Exception as e:
            logger.error(f"注册用户 {user_id} 的签到任务失败: {e}")

    async def update_user_schedule(self, user_id: int, config: TaskConfig):
        """更新用户的调度配置"""
        job_id = f"checkin_user_{user_id}"

        # 先移除旧任务
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        if config.is_enabled:
            await self._add_job(user_id, config)
        else:
            logger.info(f"用户 {user_id} 的签到任务已禁用")

    async def _execute_checkin(self, user_id: int):
        """
        执行签到任务（由调度器自动调用）
        添加随机延迟（0-120 分钟），避免所有用户同时请求
        """
        # 随机延迟，分散请求
        delay = random.uniform(0, 120 * 60)  # 0-120 分钟
        logger.info(f"用户 {user_id} 的签到任务将在 {delay/60:.1f} 分钟后执行")
        import asyncio
        await asyncio.sleep(delay)

        async with async_session() as db:
            checkin_service = CheckinService(db)
            summary = await checkin_service.execute_for_user(user_id)

            logger.info(
                f"用户 {user_id} 签到完成: "
                f"成功={summary.success}, 失败={summary.failed}, "
                f"已签={summary.already_signed}, 风控={summary.risk}"
            )

            # 触发邮件通知
            from app.services.notifier import notification_service
            await notification_service.send_checkin_report(user_id, summary, db)

    async def _check_cookies(self):
        """
        检测所有账号的 Cookie 是否过期
        通过调用米游社 API 验证 Cookie 有效性
        """
        logger.info("开始检测 Cookie 有效性...")

        async with async_session() as db:
            result = await db.execute(
                select(MihoyoAccount).where(MihoyoAccount.cookie_status == "valid")
            )
            accounts = result.scalars().all()

            from app.services.cookie import CookieService
            cookie_service = CookieService(db)

            for account in accounts:
                is_valid = await cookie_service.verify_cookie(account)
                account.cookie_status = "valid" if is_valid else "expired"
                account.last_cookie_check = datetime.utcnow()

            await db.commit()
            logger.info(f"Cookie 检测完成，共检测 {len(accounts)} 个账号")

    def stop(self):
        """停止调度器"""
        if self._started:
            self.scheduler.shutdown(wait=False)
            self._started = False
            logger.info("任务调度器已停止")


# 全局单例
scheduler_service = SchedulerService()
