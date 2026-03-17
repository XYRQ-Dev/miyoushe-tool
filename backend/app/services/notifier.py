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
import hashlib
import json
from datetime import date
from email.header import Header
from email.utils import formataddr
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
from app.utils.timezone import utc_now

logger = logging.getLogger(__name__)

GAME_NAME_MAP = {
    "hk4e_cn": "原神",
    "hk4e_bilibili": "原神(B服)",
    "hkrpg_cn": "星穹铁道",
    "hkrpg_bilibili": "星铁(B服)",
    "nap_cn": "绝区零",
    "bh3_cn": "崩坏3",
}

STATUS_NAME_MAP = {
    "success": "成功",
    "already_signed": "已签到",
    "failed": "失败",
    "risk": "风控",
}

# 签到报告邮件 HTML 模板
EMAIL_TEMPLATE = Template("""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f3f5f9; margin: 0; padding: 12px; color: #1f2937; }
    .container { max-width: 640px; margin: 0 auto; background: #ffffff; border-radius: 18px; overflow: hidden; box-shadow: 0 8px 28px rgba(15, 23, 42, 0.08); }
    .header { background: linear-gradient(160deg, #5b7cfa 0%, #3957d7 100%); color: #ffffff; padding: 24px 20px 18px; }
    .header h1 { margin: 0; font-size: 22px; line-height: 1.3; }
    .header p { margin: 8px 0 0; font-size: 13px; opacity: 0.9; }
    .summary { padding: 18px 16px 8px; background: #ffffff; }
    .summary-title { font-size: 15px; font-weight: 700; color: #111827; margin: 0 0 12px; }
    .summary-highlight { background: #eef4ff; border: 1px solid #dbe7ff; border-radius: 14px; padding: 14px; margin-bottom: 12px; }
    .summary-highlight .label { font-size: 12px; color: #5b6475; margin-bottom: 6px; }
    .summary-highlight .value { font-size: 26px; font-weight: 700; color: #1d4ed8; line-height: 1.2; }
    .summary-highlight .subvalue { font-size: 13px; color: #4b5563; margin-top: 4px; }
    .summary-grid { width: 100%; }
    .summary-grid td { width: 50%; padding: 0 0 10px; vertical-align: top; }
    .summary-chip { display: inline-block; min-width: 110px; background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 12px; padding: 10px 12px; }
    .summary-chip .chip-label { display: block; font-size: 12px; color: #6b7280; margin-bottom: 4px; }
    .summary-chip .chip-value { display: block; font-size: 18px; font-weight: 700; color: #111827; }
    .summary-chip.success .chip-value { color: #15803d; }
    .summary-chip.signed .chip-value { color: #6b7280; }
    .summary-chip.failed .chip-value { color: #dc2626; }
    .summary-chip.risk .chip-value { color: #d97706; }
    .details { padding: 8px 16px 16px; }
    .details h3 { margin: 0 0 12px; font-size: 15px; font-weight: 700; color: #111827; }
    .result-card { border: 1px solid #e5e7eb; border-radius: 14px; padding: 14px; margin-bottom: 12px; background: #ffffff; }
    .result-card:last-child { margin-bottom: 0; }
    .card-head { overflow: hidden; margin-bottom: 10px; }
    .card-title { font-size: 15px; font-weight: 700; color: #111827; line-height: 1.4; }
    .card-subtitle { font-size: 12px; color: #6b7280; margin-top: 4px; line-height: 1.5; }
    .status-tag { float: right; display: inline-block; font-size: 12px; font-weight: 700; border-radius: 999px; padding: 4px 10px; }
    .status-success { color: #166534; background: #dcfce7; }
    .status-already_signed { color: #4b5563; background: #f3f4f6; }
    .status-failed { color: #b91c1c; background: #fee2e2; }
    .status-risk { color: #b45309; background: #fef3c7; }
    .meta-table { width: 100%; border-collapse: collapse; }
    .meta-table td { padding: 6px 0; font-size: 13px; vertical-align: top; }
    .meta-table .meta-label { width: 64px; color: #6b7280; }
    .meta-table .meta-value { color: #111827; word-break: break-word; }
    .footer { padding: 14px 16px 18px; text-align: center; color: #9ca3af; font-size: 12px; border-top: 1px solid #edf2f7; background: #fcfcfd; }
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>米游社签到报告</h1>
        <p>{{ today }}</p>
    </div>
    <div class="summary">
        <div class="summary-title">执行总览</div>
        <div class="summary-highlight">
            <div class="label">执行总数</div>
            <div class="value">{{ summary.total }}</div>
            <div class="subvalue">异常 {{ summary.failed + summary.risk }} 条</div>
        </div>
        <table class="summary-grid" role="presentation">
            <tr>
                <td><span class="summary-chip success"><span class="chip-label">成功</span><span class="chip-value">{{ summary.success }}</span></span></td>
                <td><span class="summary-chip signed"><span class="chip-label">已签到</span><span class="chip-value">{{ summary.already_signed }}</span></span></td>
            </tr>
            <tr>
                <td><span class="summary-chip failed"><span class="chip-label">失败</span><span class="chip-value">{{ summary.failed }}</span></span></td>
                <td><span class="summary-chip risk"><span class="chip-label">风控</span><span class="chip-value">{{ summary.risk }}</span></span></td>
            </tr>
        </table>
    </div>
    <div class="details">
        <h3>结果详情</h3>
        {% for r in ordered_results %}
        <div class="result-card">
            <div class="card-head">
                <span class="status-tag status-{{ r.status }}">{{ status_names.get(r.status, r.status) }}</span>
                <div class="card-title">{{ r.account_nickname or '未命名账号' }}</div>
                <div class="card-subtitle">{{ game_names.get(r.game_biz, r.game_biz or '未知游戏') }} · {{ r.game_nickname or '未命名角色' }}</div>
            </div>
            <table class="meta-table" role="presentation">
                <tr>
                    <td class="meta-label">结果</td>
                    <td class="meta-value">{{ r.message }}</td>
                </tr>
                <tr>
                    <td class="meta-label">签到天数</td>
                    <td class="meta-value">{{ r.total_sign_days or '-' }}</td>
                </tr>
            </table>
        </div>
        {% endfor %}
    </div>
    <div class="footer">此邮件由米游社自动签到系统发送</div>
</div>
</body>
</html>
""")


class NotificationService:
    """邮件通知服务"""

    DEDUPE_WINDOW_SECONDS = 300

    @staticmethod
    def _result_sort_key(result) -> tuple[int, str, int]:
        """
        邮件展示顺序与原始执行顺序解耦。

        用户更关心手机端阅读体验，这里按“成功优先、已签到其次、失败和风控靠后”排序，
        只影响邮件展示，不改变原始签到结果语义。
        """
        priority = {
            "success": 0,
            "already_signed": 1,
            "failed": 2,
            "risk": 3,
        }
        return (
            priority.get(result.status, 99),
            result.account_nickname or "",
            result.account_id,
        )

    def __init__(self):
        # 进程内去重用于拦截“同一用户、同一批结果、短时间内重复发信”的场景。
        # 当前部署以单后端容器为主，不引入数据库迁移；因此这里明确把它定位为轻量幂等保护，
        # 不是跨实例的一致性方案。若后续改成多实例部署，需要升级为持久化去重。
        self._recent_notifications: dict[tuple[int, str], object] = {}

    def _build_summary_fingerprint(self, summary: CheckinSummary) -> str:
        """
        生成签到摘要指纹，用于识别“是否同一批结果”。

        指纹必须基于稳定排序后的结果生成，不能依赖原始返回顺序；
        否则同一批结果只因列表顺序不同就会被误判为两封不同邮件。
        """
        normalized_results = []
        for result in sorted(summary.results, key=self._result_sort_key):
            normalized_results.append({
                "account_id": result.account_id,
                "game_role_id": result.game_role_id,
                "account_nickname": result.account_nickname or "",
                "game_biz": result.game_biz or "",
                "game_nickname": result.game_nickname or "",
                "status": result.status,
                "message": result.message or "",
                "total_sign_days": result.total_sign_days,
            })

        payload = {
            "total": summary.total,
            "success": summary.success,
            "failed": summary.failed,
            "already_signed": summary.already_signed,
            "risk": summary.risk,
            "results": normalized_results,
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _purge_expired_dedupe_entries(self, now):
        expire_before = now.timestamp() - self.DEDUPE_WINDOW_SECONDS
        expired_keys = [
            key
            for key, last_sent_at in self._recent_notifications.items()
            if last_sent_at.timestamp() <= expire_before
        ]
        for key in expired_keys:
            self._recent_notifications.pop(key, None)

    def _should_skip_duplicate_notification(self, user_id: int, fingerprint: str, now) -> bool:
        self._purge_expired_dedupe_entries(now)
        cache_key = (user_id, fingerprint)
        last_sent_at = self._recent_notifications.get(cache_key)
        if not last_sent_at:
            return False
        return (now - last_sent_at).total_seconds() <= self.DEDUPE_WINDOW_SECONDS

    def _remember_notification(self, user_id: int, fingerprint: str, now):
        self._recent_notifications[(user_id, fingerprint)] = now

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
        source: str = "unknown",
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

        fingerprint = self._build_summary_fingerprint(summary)
        now = utc_now()
        if self._should_skip_duplicate_notification(user_id, fingerprint, now):
            logger.warning(
                "检测到重复通知，已跳过发送: user_id=%s, to=%s, source=%s, fingerprint=%s",
                user_id,
                user.email,
                source,
                fingerprint[:12],
            )
            return

        try:
            logger.info(
                "准备发送签到报告邮件: user_id=%s, to=%s, source=%s, fingerprint=%s",
                user_id,
                user.email,
                source,
                fingerprint[:12],
            )
            await self._send_email(user.email, summary, smtp_config)
            self._remember_notification(user_id, fingerprint, now)
            logger.info(
                "签到报告邮件已发送: user_id=%s, to=%s, source=%s, fingerprint=%s",
                user_id,
                user.email,
                source,
                fingerprint[:12],
            )
        except Exception as e:
            # 邮件发送失败不影响签到结果
            logger.error(
                "发送邮件失败: user_id=%s, to=%s, from=%s, source=%s, fingerprint=%s, error=%s",
                user_id,
                user.email,
                smtp_config.get("sender_email", ""),
                source,
                fingerprint[:12],
                e,
            )

    async def _send_email(self, to_email: str, summary: CheckinSummary, smtp_config: dict):
        """通过 SMTP 发送 HTML 邮件"""
        today = date.today().isoformat()
        subject = f"[米游社签到] {today} 签到报告"

        # 渲染 HTML 内容
        html_content = EMAIL_TEMPLATE.render(
            today=today,
            summary=summary,
            game_names=GAME_NAME_MAP,
            status_names=STATUS_NAME_MAP,
            ordered_results=sorted(summary.results, key=self._result_sort_key),
        )

        msg = MIMEMultipart("alternative")
        sender_name = smtp_config.get("sender_name", "").strip()
        sender_email = smtp_config["sender_email"]
        # 发件人名称和邮箱地址必须分别按 RFC 规范编码。
        # 若把“中文名称 <邮箱>”整段直接塞进 From 头，序列化后很容易被当成一个整体编码，
        # 部分 SMTP 服务商（如 QQ 邮箱）会判定该头缺失或格式非法并拒收。
        msg["From"] = (
            formataddr((str(Header(sender_name, "utf-8")), sender_email))
            if sender_name
            else sender_email
        )
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
