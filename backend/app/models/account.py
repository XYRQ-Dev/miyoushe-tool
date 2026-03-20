"""
米哈游账号和游戏角色模型
- MihoyoAccount：米游社账号（一个用户可绑定多个米游社账号）
- GameRole：游戏角色（一个米游社账号下可有多个游戏角色）
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.database import Base
from app.utils.timezone import utc_now_naive


class MihoyoAccount(Base):
    __tablename__ = "mihoyo_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    nickname = Column(String(100), nullable=True)
    mihoyo_uid = Column(String(50), nullable=True)
    # Cookie 使用 AES-256 加密存储，绝不明文落库
    cookie_encrypted = Column(Text, nullable=True)
    # 自动续期所需的 stoken 同样属于高敏感凭据，必须与 Cookie 一样加密存储。
    # 若后续有人为了“方便排障”改成明文，等价于把整套登录态维护入口直接暴露到数据库层。
    stoken_encrypted = Column(Text, nullable=True)
    stuid = Column(String(50), nullable=True)
    mid = Column(String(100), nullable=True)
    # Cookie 状态：valid / expired / unknown
    cookie_status = Column(String(20), default="valid")
    last_cookie_check = Column(DateTime, nullable=True)
    cookie_token_updated_at = Column(DateTime, nullable=True)
    # 这三列的字段名来自历史“登录态维护/续期”设计，当前为了兼容旧库与现有接口继续沿用。
    # 但自 2026-03 起，业务语义已收敛为“最近一次登录态校验结果”，后续维护时不要再把它们
    # 默认理解成“系统一定会自动续期成功”的承诺。
    last_refresh_attempt_at = Column(DateTime, nullable=True)
    last_refresh_status = Column(String(30), nullable=True)
    last_refresh_message = Column(Text, nullable=True)
    reauth_notified_at = Column(DateTime, nullable=True)
    # 当前模型字段仍以“无时区 UTC”存库；若直接继续引用 datetime.utcnow，
    # Python 3.12+ 会产生弃用告警，且容易让后续维护者误以为这里是推荐写法。
    created_at = Column(DateTime, default=utc_now_naive)


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
