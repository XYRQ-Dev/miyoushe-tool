"""
任务配置和签到日志模型
- TaskConfig：用户的调度配置（cron 表达式等）
- TaskLog：每次签到的执行记录
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.database import Base
from app.utils.timezone import utc_now_naive


class TaskConfig(Base):
    __tablename__ = "task_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_type = Column(String(50), default="checkin")
    # cron 表达式，默认每天早上 6 点
    cron_expr = Column(String(50), default="0 6 * * *")
    is_enabled = Column(Boolean, default=True)
    # 调度配置创建时间沿用“无时区 UTC”存储约定，避免与旧数据比较时出现混乱。
    created_at = Column(DateTime, default=utc_now_naive)


class TaskLog(Base):
    __tablename__ = "task_logs"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("mihoyo_accounts.id"), nullable=False, index=True)
    game_role_id = Column(Integer, ForeignKey("game_roles.id"), nullable=True)
    task_type = Column(String(50), default="checkin")
    # 执行状态：success / failed / already_signed / risk
    status = Column(String(20), nullable=False)
    message = Column(Text, nullable=True)
    total_sign_days = Column(Integer, nullable=True)
    # 日志执行时间会再由 API 层转换成东八区返回前端；此处必须稳定保存 UTC 基准时间。
    executed_at = Column(DateTime, default=utc_now_naive)
