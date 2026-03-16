"""
邮件通知服务
签到完成后将结果汇总以 HTML 邮件发送给用户。

发信配置分为两层：
1. 系统 SMTP：决定“系统是否有能力发信”，仅管理员可维护
2. 用户接收邮箱：决定“发给谁、什么时候发”，由用户自行维护

这两层语义不能混用。若未来有人把用户邮箱误当成系统 SMTP 配置来源，
就会出现“用户明明填了邮箱但系统仍无法发送”的排障陷阱。
"""

import logging
from datetime import date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import aiosmtplib
from jinja2 import Template
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User
from app.services.system_settings import SystemSettingsService
from app.utils.crypto import decrypt_text
from app.schemas.task_log import CheckinSummary

logger = logging.getLogger(__name__)

# 签到报告邮件 HTML 模板
EMAIL_TEMPLATE = Template("""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa; margin: 0; padding: 20px; }
    .container { max-width: 600px; margin: 0 auto; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
    .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 24px; text-align: center; }
    .header h1 { margin: 0; font-size: 20px; }
    .header p { margin: 8px 0 0; opacity: 0.9; font-size: 14px; }
    .summary { display: flex; justify-content: space-around; padding: 20px; background: #f8f9ff; }
    .summary-item { text-align: center; }
    .summary-item .num { font-size: 28px; font-weight: bold; }
    .summary-item .label { font-size: 12px; color: #666; margin-top: 4px; }
    .success .num { color: #52c41a; }
    .failed .num { color: #ff4d4f; }
    .signed .num { color: #999; }
    .risk .num { color: #faad14; }
    .details { padding: 20px; }
    .details h3 { margin: 0 0 12px; font-size: 16px; color: #333; }
    table { width: 100%; border-collapse: collapse; }
    th { background: #f5f7fa; padding: 10px; text-align: left; font-size: 13px; color: #666; }
    td { padding: 10px; border-bottom: 1px solid #f0f0f0; font-size: 13px; }
    .status-success { color: #52c41a; font-weight: bold; }
    .status-failed { color: #ff4d4f; font-weight: bold; }
    .status-signed { color: #999; }
    .status-risk { color: #faad14; font-weight: bold; }
    .footer { padding: 16px; text-align: center; color: #999; font-size: 12px; border-top: 1px solid #f0f0f0; }
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>米游社签到报告</h1>
        <p>{{ today }}</p>
    </div>
    <div class="summary">
        <div class="summary-item success"><div class="num">{{ summary.success }}</div><div class="label">成功</div></div>
        <div class="summary-item failed"><div class="num">{{ summary.failed }}</div><div class="label">失败</div></div>
        <div class="summary-item signed"><div class="num">{{ summary.already_signed }}</div><div class="label">已签到</div></div>
        <div class="summary-item risk"><div class="num">{{ summary.risk }}</div><div class="label">风控</div></div>
    </div>
    <div class="details">
        <h3>签到详情</h3>
        <table>
            <tr><th>状态</th><th>信息</th><th>签到天数</th></tr>
            {% for r in summary.results %}
            <tr>
                <td class="status-{{ r.status }}">
                    {% if r.status == 'success' %}成功
                    {% elif r.status == 'failed' %}失败
                    {% elif r.status == 'already_signed' %}已签到
                    {% elif r.status == 'risk' %}风控
                    {% endif %}
                </td>
                <td>{{ r.message }}</td>
                <td>{{ r.total_sign_days or '-' }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>
    <div class="footer">此邮件由米游社自动签到系统发送</div>
</div>
</body>
</html>
""")


class NotificationService:
    """邮件通知服务"""

    async def _load_smtp_config(self, db: AsyncSession) -> dict | None:
        """
        读取系统 SMTP 配置。

        优先使用后台保存的系统配置，后台未配置时才回退环境变量，
        这样既兼容老部署，又允许管理员在 UI 中接管配置。
        """
        config = await SystemSettingsService(db).get_or_create()

        if config.smtp_enabled and config.smtp_host and config.smtp_user:
            return {
                "hostname": config.smtp_host,
                "port": config.smtp_port,
                "username": config.smtp_user,
                "password": decrypt_text(config.smtp_password_encrypted) if config.smtp_password_encrypted else "",
                "use_ssl": config.smtp_use_ssl,
                "sender_name": config.smtp_sender_name or "",
                "sender_email": config.smtp_sender_email or config.smtp_user,
            }

        if settings.SMTP_HOST and settings.SMTP_USER:
            return {
                "hostname": settings.SMTP_HOST,
                "port": settings.SMTP_PORT,
                "username": settings.SMTP_USER,
                "password": settings.SMTP_PASSWORD,
                "use_ssl": settings.SMTP_USE_SSL,
                "sender_name": "",
                "sender_email": settings.SMTP_USER,
            }

        return None

    async def send_checkin_report(
        self,
        user_id: int,
        summary: CheckinSummary,
        db: AsyncSession,
    ):
        """
        发送签到报告邮件
        根据用户设置决定是否发送：
        - email_notify=False → 不发送
        - notify_on='failure_only' 且全部成功 → 不发送
        """
        smtp_config = await self._load_smtp_config(db)
        if not smtp_config:
            logger.debug("SMTP 未配置，跳过邮件发送")
            return

        # 查询用户信息
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user or not user.email or not user.email_notify:
            return

        # 检查通知策略
        if user.notify_on == "failure_only" and summary.failed == 0 and summary.risk == 0:
            logger.debug(f"用户 {user_id} 设置为仅失败通知，本次全部成功，跳过")
            return

        try:
            await self._send_email(user.email, summary, smtp_config)
            logger.info(f"签到报告邮件已发送至 {user.email}")
        except Exception as e:
            # 邮件发送失败不影响签到结果
            logger.error(f"发送邮件失败: {e}")

    async def _send_email(self, to_email: str, summary: CheckinSummary, smtp_config: dict):
        """通过 SMTP 发送 HTML 邮件"""
        today = date.today().isoformat()
        subject = f"[米游社签到] {today} 签到报告"

        # 渲染 HTML 内容
        html_content = EMAIL_TEMPLATE.render(
            today=today,
            summary=summary,
        )

        msg = MIMEMultipart("alternative")
        sender_name = smtp_config.get("sender_name", "").strip()
        sender_email = smtp_config["sender_email"]
        msg["From"] = f"{sender_name} <{sender_email}>" if sender_name else sender_email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        # 使用 aiosmtplib 异步发送
        kwargs = {
            "hostname": smtp_config["hostname"],
            "port": smtp_config["port"],
            "username": smtp_config["username"],
            "password": smtp_config["password"],
        }

        if smtp_config["use_ssl"]:
            kwargs["use_tls"] = True
        else:
            kwargs["start_tls"] = True

        await aiosmtplib.send(msg, **kwargs)


# 全局单例
notification_service = NotificationService()
