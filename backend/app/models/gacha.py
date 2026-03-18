"""
抽卡记录模型
- GachaImportJob：一次抽卡链接导入任务的摘要
- GachaRecord：单条抽卡记录
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.database import Base
from app.utils.timezone import utc_now_naive


class GachaImportJob(Base):
    __tablename__ = "gacha_import_jobs"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("mihoyo_accounts.id"), nullable=False, index=True)
    game = Column(String(20), nullable=False, index=True)
    # 原始链接里通常会带 authkey 等高敏感参数。
    # 这里必须只保存脱敏后的链接摘要，而不是把完整链接直接落库，
    # 否则数据库泄露时，风险不再是“能看到导入历史”，而是“能直接重放抽卡记录接口请求”。
    source_url_masked = Column(Text, nullable=False)
    status = Column(String(20), default="success")
    fetched_count = Column(Integer, default=0)
    inserted_count = Column(Integer, default=0)
    duplicate_count = Column(Integer, default=0)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)


class GachaRecord(Base):
    __tablename__ = "gacha_records"
    __table_args__ = (
        UniqueConstraint("account_id", "game", "record_id", name="uq_gacha_record_account_game_record"),
    )

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("mihoyo_accounts.id"), nullable=False, index=True)
    game = Column(String(20), nullable=False, index=True)
    record_id = Column(String(50), nullable=False)
    pool_type = Column(String(20), nullable=False, index=True)
    pool_name = Column(String(50), nullable=True)
    item_name = Column(String(100), nullable=False)
    item_type = Column(String(20), nullable=True)
    rank_type = Column(String(5), nullable=False, index=True)
    # 上游返回的是没有时区语义的本地时间字符串。
    # 这里先原样保存文本，避免误判为 UTC 后再错误换算，导致“最近出货”排序和展示都错位。
    time_text = Column(String(30), nullable=False, index=True)
    imported_at = Column(DateTime, default=utc_now_naive)
