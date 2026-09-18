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
    # 高权限登录底座切到 Passport 后，`ltoken / cookie_token / login_ticket`
    # 不再只是“偶尔调试时会看到的附属字段”，而是工作 Cookie 重建与票据换取的根凭据。
    # 这些字段必须和 `stoken` 一样按高敏感凭据对待：统一加密落库、绝不明文存储。
    # 如果后续维护者为了图省事改成明文，风险不是“单个接口多暴露一点信息”，
    # 而是数据库泄露后可直接重放高权限登录态维护链路。
    ltoken_encrypted = Column(Text, nullable=True)
    cookie_token_encrypted = Column(Text, nullable=True)
    login_ticket_encrypted = Column(Text, nullable=True)
    stuid = Column(String(50), nullable=True)
    mid = Column(String(100), nullable=True)
    # `credential_*` 描述的是“根凭据状态”，而不是当前工作 Cookie 是否还能直接拿去请求业务接口。
    # 这组字段存在的意义，是把“可以自愈重建 Cookie”和“只能让用户重新登录”这两类状态分开。
    # 如果误把它和 `cookie_status` 混用，最常见的后果就是：
    # 1. 根凭据明明还有效，系统却错误提示用户重登
    # 2. 工作 Cookie 虽然失效，但页面还误显示“高权限登录正常”
    credential_source = Column(String(30), nullable=True)
    credential_status = Column(String(30), nullable=True, default="reauth_required")
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
    # `last_token_refresh_*` 只记录“根凭据补齐/刷新”的结果，不承载工作 Cookie 校验结论。
    # 这里显式拆开，是为了避免后续排障时把“Cookie 校验失败”和“根凭据刷新失败”混成同一类错误。
    # 一旦把两者揉在一起，运维面板和通知就会失去指导意义。
    last_token_refresh_at = Column(DateTime, nullable=True)
    last_token_refresh_status = Column(String(30), nullable=True)
    last_token_refresh_message = Column(Text, nullable=True)
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
