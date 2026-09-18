"""
管理员群发服务

这条链路的产品语义是“管理员公告”，不是用户个人签到通知：
- 收件人只看“账号启用 + 已绑定邮箱”
- 不受 `email_notify` 与 `notify_on` 影响
- 单个收件人发送失败不能阻断剩余收件人
"""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_operation_log import AdminOperationLog
from app.models.user import User
from app.schemas.admin_notification import (
    AdminBroadcastEmailFailure,
    AdminBroadcastEmailRequest,
    AdminBroadcastEmailResponse,
)
from app.services.notifier import NotificationService


class AdminBroadcastService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.notification_service = NotificationService()

    async def _load_recipients(self) -> list[User]:
        result = await self.db.execute(
            select(User)
            .where(User.is_active.is_(True))
            .where(User.email.is_not(None))
            .order_by(User.id.asc())
        )
        # 这里必须再做一次 strip 判空，而不是只靠 SQL `IS NOT NULL`。
        # 否则历史脏数据里像 `"   "` 这样的占位值会被误当成真实邮箱，群发时才在 SMTP 层爆炸。
        return [
            user
            for user in result.scalars().all()
            if (user.email or "").strip()
        ]

    async def _send_one(self, *, recipient: User, subject: str, body: str, smtp_config: dict) -> None:
        await self.notification_service.send_admin_broadcast_email(
            to_email=(recipient.email or "").strip(),
            subject=subject,
            body=body,
            smtp_config=smtp_config,
        )

    async def broadcast_email(
        self,
        *,
        admin: User,
        payload: AdminBroadcastEmailRequest,
    ) -> AdminBroadcastEmailResponse:
        recipients = await self._load_recipients()
        if not recipients:
            raise ValueError("当前没有已绑定邮箱且启用的用户")

        smtp_config = await self.notification_service._load_smtp_config(self.db)
        if not smtp_config:
            raise ValueError("系统 SMTP 未配置，无法发送群发通知")

        failures: list[AdminBroadcastEmailFailure] = []
        sent_count = 0
        normalized_subject = payload.subject.strip()
        normalized_body = payload.body.strip()

        for recipient in recipients:
            try:
                await self._send_one(
                    recipient=recipient,
                    subject=normalized_subject,
                    body=normalized_body,
                    smtp_config=smtp_config,
                )
                sent_count += 1
            except Exception as exc:
                failures.append(
                    AdminBroadcastEmailFailure(
                        user_id=recipient.id,
                        username=recipient.username,
                        email=(recipient.email or "").strip(),
                        error=str(exc),
                    )
                )

        operation_log = AdminOperationLog(
            operator_user_id=admin.id,
            action_type="broadcast_email",
            subject=normalized_subject,
            recipient_count=len(recipients),
            sent_count=sent_count,
            failed_count=len(failures),
            failure_details_json=json.dumps(
                [failure.model_dump() for failure in failures],
                ensure_ascii=False,
            ),
        )
        self.db.add(operation_log)
        await self.db.commit()
        await self.db.refresh(operation_log)

        return AdminBroadcastEmailResponse(
            recipient_count=len(recipients),
            sent_count=sent_count,
            failed_count=len(failures),
            failures=failures,
            operation_log_id=operation_log.id,
        )
