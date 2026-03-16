"""
任务配置和签到日志模型
- TaskConfig：用户的调度配置（cron 表达式等）
- TaskLog：每次签到的执行记录
"""

from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from app.database import Base


class TaskConfig(Base):
    __tablename__ = "task_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_type = Column(String(50), default="checkin")
    # cron 表达式，默认每天早上 6 点
    cron_expr = Column(String(50), default="0 6 * * *")
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


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
    executed_at = Column(DateTime, default=datetime.utcnow)
