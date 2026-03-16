"""
系统级配置模型

当前主要承载两类信息：
1. 管理员可维护的 SMTP 发信配置
2. 米游社移动端设备标识缓存

之所以放在同一张表，是因为这两类数据都属于“全局单例配置”：
- 需要跨进程/跨任务稳定复用
- 不能每次执行时重新随机生成
- 后续若继续扩展系统级配置，也能保持入口一致
"""

from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.database import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, default=1)

    # SMTP 系统发信配置。密码以加密后的密文保存，避免接口层或日志误输出明文。
    smtp_enabled = Column(Boolean, default=False)
    smtp_host = Column(String(255), nullable=True)
    smtp_port = Column(Integer, default=465)
    smtp_user = Column(String(255), nullable=True)
    smtp_password_encrypted = Column(String(1024), nullable=True)
    smtp_use_ssl = Column(Boolean, default=True)
    smtp_sender_name = Column(String(255), nullable=True)
    smtp_sender_email = Column(String(255), nullable=True)

    # 设备标识必须稳定复用。若每次签到都随机生成，容易造成“参数看起来齐全但依然高频风控”的假象。
    hyperion_device_id = Column(String(64), nullable=True)
    hyperion_device_fp = Column(String(64), nullable=True)
    hyperion_device_fp_updated_at = Column(DateTime, nullable=True)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
