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

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.database import Base
from app.utils.timezone import utc_now_naive


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

    # 菜单可见性是系统级全局配置：管理员维护后，所有登录态都需要按同一套策略渲染与拦截。
    # 这里保存 JSON 文本而不是拆成多行配置，是为了让“菜单目录默认值 + 旧库补列 + MySQL 迁移”
    # 都保持简单一致；如果误改成自由格式文本，前端路由守卫就会在运行期失去稳定输入。
    menu_visibility_json = Column(Text, nullable=True)

    # 设备标识必须稳定复用。若每次签到都随机生成，容易造成“参数看起来齐全但依然高频风控”的假象。
    hyperion_device_id = Column(String(64), nullable=True)
    hyperion_device_fp = Column(String(64), nullable=True)
    hyperion_device_fp_updated_at = Column(DateTime, nullable=True)

    # 系统配置更新时间需要与其余 DateTime 字段保持同一套 UTC 语义；
    # default/onupdate 若继续直接挂 datetime.utcnow，会在 SQLAlchemy 调用时触发弃用告警。
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)
