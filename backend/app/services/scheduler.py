"""
任务调度服务
使用 APScheduler 实现定时签到和网页登录态巡检
"""

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.utils.timezone import SHANGHAI
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
        # cron 的“每天 6 点”固定为东八区 6 点，不跟随部署机器或浏览器时区。
        self.scheduler = AsyncIOScheduler(timezone=SHANGHAI)
        self._started = False
        self._schedule_locks: dict[int, asyncio.Lock] = {}
        self._schedule_errors: dict[int, str] = {}

    def user_schedule_lock(self, user_id: int) -> asyncio.Lock:
        """串行化本进程同一用户的配置读取、更新及补偿"""
        return self._schedule_locks.setdefault(user_id, asyncio.Lock())

    def validate_user_schedule(self, user_id: int, config) -> None:
        """启用配置必须在数据库和运行任务变更前通过 Cron 校验"""
        if config.is_enabled:
            self._build_trigger(user_id, config.cron_expr)

    def snapshot_user_schedule(self, user_id: int) -> SimpleNamespace | None:
        """保存触发器和下次运行时间，不持有会随调度推进而变化的 Job"""
        job = self.scheduler.get_job(self._build_job_id(user_id))
        if job is None:
            return None
        # 显式复制运行参数，避免 Job 序列化改变绑定方法及其参数
        return SimpleNamespace(
            id=job.id, func=job.func, trigger=job.trigger, args=tuple(job.args),
            kwargs=dict(job.kwargs), name=job.name, executor=job.executor,
            misfire_grace_time=job.misfire_grace_time, coalesce=job.coalesce,
            max_instances=job.max_instances, next_run_time=job.next_run_time,
        )

    def restore_user_schedule(self, user_id: int, snapshot, original_error: BaseException) -> bool:
        """恢复原运行态，失败保留最初错误并通过状态接口暴露补偿错误"""
        job_id = self._build_job_id(user_id)
        try:
            current = self.scheduler.get_job(job_id)
            if snapshot is None:
                if current is not None:
                    self.scheduler.remove_job(job_id)
            elif current is None or current.trigger is not snapshot.trigger:
                self.scheduler.add_job(
                    snapshot.func, snapshot.trigger, id=job_id, replace_existing=True,
                    args=snapshot.args, kwargs=snapshot.kwargs, name=snapshot.name,
                    misfire_grace_time=snapshot.misfire_grace_time,
                    coalesce=snapshot.coalesce, max_instances=snapshot.max_instances,
                    executor=snapshot.executor, next_run_time=snapshot.next_run_time,
                )
            return True
        except Exception as exc:
            self._schedule_errors[user_id] = f"调度更新失败: {original_error}；恢复原任务失败: {exc}"
            logger.exception("用户 %s 恢复原任务失败，最初异常: %s", user_id, original_error)
            return False

    def clear_user_schedule_error(self, user_id: int) -> None:
        """仅在配置与运行任务更新成功后清除补偿错误"""
        self._schedule_errors.pop(user_id, None)

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
        scheduler_error = scheduler_error or self._schedule_errors.get(user_id)
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
            job_registered=job is not None and self.scheduler.running,
            job_id=job_id,
            next_run_time=getattr(job, "next_run_time", None) if self.scheduler.running else None,
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
                select(TaskConfig).join(User, User.id == TaskConfig.user_id).where(
                    TaskConfig.is_enabled == True, User.is_active == True,
                )
            )
            configs = result.scalars().all()

            registered_count = 0
            for config in configs:
                runtime = await self.ensure_user_schedule(config, user_active=True)
                registered_count += int(runtime.job_registered)

            logger.info("已注册 %s/%s 个用户的签到任务", registered_count, len(configs))

    async def _add_job(self, user_id: int, config: TaskConfig) -> ScheduleRegistrationResult:
        """为指定用户添加签到定时任务"""
        job_id = self._build_job_id(user_id)

        try:
            trigger = self._build_trigger(user_id, config.cron_expr)
            if not self.scheduler.running:
                raise ScheduleRegistrationError("任务调度器尚未启动", status_code=503)

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
        self.validate_user_schedule(user_id, config)
        job_id = self._build_job_id(user_id)
        snapshot = self.snapshot_user_schedule(user_id)
        try:
            # 启用时按固定 ID 替换，不能提前删除仍有效的旧任务
            if config.is_enabled:
                return await self._add_job(user_id, config)
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
        except Exception as exc:
            self.restore_user_schedule(user_id, snapshot, exc)
            raise

        logger.info(f"用户 {user_id} 的签到任务已禁用")
        return self._build_result(user_id=user_id, enabled=False)

    async def ensure_user_schedule(
        self, config: TaskConfig, *, user_active: bool,
    ) -> ScheduleRegistrationResult:
        """仅为已提交的启用配置补注册缺失任务；失败返回运行态，供调用方重试"""
        enabled = bool(config.is_enabled and user_active)
        try:
            # 补偿失败时不能把仍存在的新任务误报为旧配置已恢复
            if config.user_id in self._schedule_errors:
                return self._build_result(user_id=config.user_id, enabled=enabled)
            if not enabled:
                return self._build_result(user_id=config.user_id, enabled=False)
            if not self.scheduler.running:
                raise ScheduleRegistrationError("任务调度器尚未启动", status_code=503)
            runtime = self._build_result(user_id=config.user_id, enabled=True)
            if runtime.job_registered:
                return runtime
            # 检查到注册之间没有异步 I/O，重复调用保留已有任务的下次执行时间
            return await self._add_job(config.user_id, config)
        except Exception as exc:
            logger.exception("恢复用户 %s 的签到任务失败", config.user_id)
            return ScheduleRegistrationResult(
                enabled=enabled,
                job_registered=False,
                job_id=self._build_job_id(config.user_id),
                next_run_time=None,
                scheduler_error=str(exc),
            )

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
