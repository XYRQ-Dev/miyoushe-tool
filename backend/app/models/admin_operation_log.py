"""
管理员操作日志模型

当前只承载“管理员群发邮件”这类需要追溯的后台动作摘要。
这里刻意不复用 TaskLog：
- TaskLog 语义是“面向账号/角色的签到执行结果”
- 管理员群发属于后台操作审计，若硬塞进 TaskLog，会把日志查询和状态语义一起污染
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.database import Base
from app.utils.timezone import utc_now_naive


class AdminOperationLog(Base):
    __tablename__ = "admin_operation_logs"

    id = Column(Integer, primary_key=True, index=True)
    operator_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action_type = Column(String(50), nullable=False, default="broadcast_email")
    subject = Column(String(255), nullable=False)
    recipient_count = Column(Integer, nullable=False, default=0)
    sent_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    failure_details_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
