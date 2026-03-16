"""
用户模型
- 支持 admin / user 两种角色
- 首个注册用户自动成为管理员
"""

from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    # 是否开启邮件通知
    email_notify = Column(Boolean, default=True)
    # 通知策略：always=每次都通知，failure_only=仅失败时通知
    notify_on = Column(String(20), default="always")
    # 角色：admin 或 user
    role = Column(String(10), default="user")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
