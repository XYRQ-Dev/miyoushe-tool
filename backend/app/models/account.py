"""
米哈游账号和游戏角色模型
- MihoyoAccount：米游社账号（一个用户可绑定多个米游社账号）
- GameRole：游戏角色（一个米游社账号下可有多个游戏角色）
"""

from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from app.database import Base


class MihoyoAccount(Base):
    __tablename__ = "mihoyo_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    nickname = Column(String(100), nullable=True)
    mihoyo_uid = Column(String(50), nullable=True)
    # Cookie 使用 AES-256 加密存储，绝不明文落库
    cookie_encrypted = Column(Text, nullable=True)
    # Cookie 状态：valid / expired / unknown
    cookie_status = Column(String(20), default="valid")
    last_cookie_check = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class GameRole(Base):
    __tablename__ = "game_roles"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("mihoyo_accounts.id"), nullable=False, index=True)
    # 游戏业务标识：hk4e_cn（原神国服）、hkrpg_cn（星铁国服）等
    game_biz = Column(String(30), nullable=False)
    game_uid = Column(String(50), nullable=False)
    nickname = Column(String(100), nullable=True)
    region = Column(String(20), nullable=True)
    level = Column(Integer, nullable=True)
    # 是否启用签到
    is_enabled = Column(Boolean, default=True)
