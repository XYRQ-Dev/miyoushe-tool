"""
任务调度服务
使用 APScheduler 实现定时签到和网页登录态巡检
"""

import logging
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models.user import User
from app.models.account import MihoyoAccount
from app.models.task_log import TaskConfig
from app.services.checkin import CheckinService
from app.services.login_state import LoginStateService
from app.services.task_config import ensure_all_users_have_task_config

logger = logging.getLogger(__name__)


class ScheduleRegistrationError(Exception):
    """调度注册异常，区分用户可修复错误与服务端异常。"""

    def __init__(self, message: str, *, status_code: int = 400):
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class ScheduleRegistrationResult:
    enabled: bool
    job_registered: bool
    job_id: str | None
    next_run_time: datetime | None
    scheduler_error: str | None = None


class SchedulerService:
    """调度服务，管理所有用户的定时签到任务"""

    def __init__(self):
        # 调度器时区必须与业务约定一致。
        # 如果继续依赖进程宿主机默认时区，用户在非东八区环境保存“每天 6 点”时，
        # 实际触发时刻会偏移，表现上就像“定时任务没生效”。
        self.scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.APP_TIMEZONE))
        self._started = False

    @property
    def is_started(self) -> bool:
        return self._started

    def _build_job_id(self, user_id: int) -> str:
        return f"checkin_user_{user_id}"

    def _build_result(
        self,
        *,
        user_id: int,
        enabled: bool,
        scheduler_error: str | None = None,
    ) -> ScheduleRegistrationResult:
        job_id = self._build_job_id(user_id)
        if not enabled:
            return ScheduleRegistrationResult(
                enabled=False,
                job_registered=False,
                job_id=job_id,
                next_run_time=None,
                scheduler_error=scheduler_error,
            )

        job = self.scheduler.get_job(job_id)
        return ScheduleRegistrationResult(
            enabled=True,
            job_registered=job is not None,
            job_id=job_id,
            next_run_time=job.next_run_time if job else None,
            scheduler_error=scheduler_error,
        )

    def _build_trigger(self, user_id: int, cron_expr: str) -> CronTrigger:
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ScheduleRegistrationError(f"用户 {user_id} 的 Cron 表达式无效: {cron_expr}", status_code=400)

        try:
            return CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
                timezone=self.scheduler.timezone,
            )
        except ValueError as exc:
            raise ScheduleRegistrationError(
                f"用户 {user_id} 的 Cron 表达式无效: {cron_expr} ({exc})",
                status_code=400,
            ) from exc

    async def start(self):
        """启动调度器并加载所有用户的调度配置"""
        if self._started:
            return

        self.scheduler.start()
        self._started = True
        logger.info("任务调度器已启动")

        # 加载所有用户的调度配置
        await self._load_all_schedules()

        # 添加网页登录态巡检任务（每天凌晨 3 点执行）
        self.scheduler.add_job(
            self._check_cookies,
            CronTrigger(hour=3, minute=0),
            id="cookie_check",
            replace_existing=True,
        )
        logger.info("网页登录态巡检任务已注册（每天 03:00）")

    async def _load_all_schedules(self):
        """从数据库加载所有启用的调度配置"""
        async with async_session() as db:
            created_count = await ensure_all_users_have_task_config(db)
            if created_count:
                logger.info("已为 %s 个历史用户补建默认签到调度配置", created_count)

            result = await db.execute(
                select(TaskConfig).where(TaskConfig.is_enabled == True)
            )
            configs = result.scalars().all()

            for config in configs:
                try:
                    await self._add_job(config.user_id, config)
                except ScheduleRegistrationError as exc:
                    logger.error("加载用户 %s 的签到任务失败: %s", config.user_id, exc)

            logger.info(f"已加载 {len(configs)} 个用户的调度配置")

    async def _add_job(self, user_id: int, config: TaskConfig) -> ScheduleRegistrationResult:
        """为指定用户添加签到定时任务"""
        job_id = self._build_job_id(user_id)

        try:
            trigger = self._build_trigger(user_id, config.cron_expr)

            self.scheduler.add_job(
                self._execute_checkin,
                trigger,
                id=job_id,
                replace_existing=True,
                args=[user_id],
            )
            result = self._build_result(user_id=user_id, enabled=True)
            if not result.job_registered:
                raise ScheduleRegistrationError(
                    f"用户 {user_id} 的签到任务注册后未出现在调度器中",
                    status_code=500,
                )

            logger.info(
                "用户 %s 的签到任务已注册: %s, 下次执行时间=%s",
                user_id,
                config.cron_expr,
                result.next_run_time,
            )
            return result

        except ScheduleRegistrationError:
            raise
        except Exception as exc:
            logger.exception("注册用户 %s 的签到任务失败", user_id)
            raise ScheduleRegistrationError(
                f"注册用户 {user_id} 的签到任务失败: {exc}",
                status_code=500,
            ) from exc

    async def update_user_schedule(self, user_id: int, config: TaskConfig) -> ScheduleRegistrationResult:
        """更新用户的调度配置"""
        job_id = self._build_job_id(user_id)

        # 先移除旧任务
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        if config.is_enabled:
            return await self._add_job(user_id, config)

        logger.info(f"用户 {user_id} 的签到任务已禁用")
        return self._build_result(user_id=user_id, enabled=False)

    def get_user_schedule_status(
        self,
        user_id: int,
        *,
        enabled: bool,
        scheduler_error: str | None = None,
    ) -> ScheduleRegistrationResult:
        """查询当前进程内该用户调度任务的运行态。"""
        return self._build_result(
            user_id=user_id,
            enabled=enabled,
            scheduler_error=scheduler_error,
        )

    async def _execute_checkin(self, user_id: int):
        """
        执行签到任务（由调度器自动调用）
        添加随机延迟（0-60 秒），避免所有用户同时请求
        """
        # 自动签到仍保留一个很短的随机窗口，用来避免多个用户在同一秒并发命中上游。
        # 这里已经按产品语义收敛到“1 分钟内执行”，因此不能再把窗口放大回分钟级，
        # 否则用户在设置页看到的预期会与实际行为再次脱节。
        delay = random.uniform(0, 60)  # 0-60 秒
        logger.info(f"用户 {user_id} 的签到任务将在 {delay:.1f} 秒后执行")
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
            await notification_service.send_checkin_report(
                user_id,
                summary,
                db,
                source="scheduled_checkin",
            )

    async def _check_cookies(self):
        """
        检测所有账号的网页登录态。

        这里只做统一调度入口，不再把“过期检测”“自动续期”“签到前置判断”拆成多套逻辑，
        否则账号页、定时任务和签到前置检查很容易看到彼此矛盾的状态。
        """
        logger.info("开始巡检账号网页登录态...")

        async with async_session() as db:
            result = await db.execute(
                select(MihoyoAccount).where(MihoyoAccount.cookie_encrypted.is_not(None))
            )
            accounts = result.scalars().all()

            login_state_service = LoginStateService(db)

            for account in accounts:
                await login_state_service.refresh_account_login_state(account)

            logger.info(f"网页登录态巡检完成，共处理 {len(accounts)} 个账号")

    def stop(self):
        """停止调度器"""
        if self._started:
            self.scheduler.shutdown(wait=False)
            self._started = False
            logger.info("任务调度器已停止")


# 全局单例
scheduler_service = SchedulerService()
