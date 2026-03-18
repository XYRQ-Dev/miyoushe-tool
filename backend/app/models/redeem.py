"""
兑换码批量执行模型
- RedeemBatch：一次兑换码批量执行的批次摘要
- RedeemExecution：批次内单账号执行结果
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.database import Base
from app.utils.timezone import utc_now_naive


class RedeemBatch(Base):
    __tablename__ = "redeem_batches"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_count = Column(Integer, nullable=False, default=0)
    game = Column(String(20), nullable=False, index=True)
    # 兑换码本身不像 authkey / Cookie 那样可直接换取登录态，因此允许按原文留档，
    # 目的是让用户回看历史批次时知道当时执行的是哪一个码。
    # 如果未来产品扩展到“自动抓取待审核码源”，再单独评估是否需要额外脱敏策略。
    code = Column(String(100), nullable=False, index=True)
    # 这些计数字段统一由服务层基于 executions 推导，不允许业务层“顺手改一个数字”。
    # 否则批次摘要会和明细脱节，前端看到的统计就会变成不可追溯的脏数据。
    success_count = Column(Integer, nullable=False, default=0)
    already_redeemed_count = Column(Integer, nullable=False, default=0)
    invalid_code_count = Column(Integer, nullable=False, default=0)
    invalid_cookie_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now_naive, index=True)


class RedeemExecution(Base):
    __tablename__ = "redeem_executions"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("redeem_batches.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("mihoyo_accounts.id"), nullable=False, index=True)
    game = Column(String(20), nullable=False, index=True)
    # 账号昵称和 UID 都可能在后续扫码刷新时变化；这里保留执行当下的展示快照，
    # 是为了避免历史结果页因为账号资料变化而“看起来像给别的账号执行过”。
    account_name = Column(String(120), nullable=False)
    role_uid = Column(String(50), nullable=True)
    region = Column(String(30), nullable=True)
    status = Column(String(30), nullable=False, index=True)
    upstream_code = Column(Integer, nullable=True)
    message = Column(Text, nullable=True)
    executed_at = Column(DateTime, default=utc_now_naive, index=True)
