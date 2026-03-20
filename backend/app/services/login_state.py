"""
账号登录态校验服务

当前系统只承诺“网页登录 Cookie 是否仍可用”的统一判定，不再承诺自动续期。
这里继续集中处理状态流转与失效通知，避免：
1. 调度器、手动签到、账号页各自维护一套判定逻辑
2. 同一个账号在不同入口里被写成不同状态
3. 登录态失效后没有一致的下一步指引
"""

import logging
import re
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import ensure_account_columns
from app.models.account import MihoyoAccount
from app.models.user import User
from app.services.notifier import notification_service
from app.utils.crypto import decrypt_cookie
from app.utils.device import generate_device_id, get_default_headers
from app.utils.ds import generate_ds
from app.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)

VERIFY_URL = "https://api-takumi.mihoyo.com/binding/api/getUserGameRolesByCookie"


class LoginStateService:
    """负责米游社账号网页登录态校验。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _extract_cookie_value(cookie_str: str, keys: tuple[str, ...]) -> str | None:
        for key in keys:
            match = re.search(rf"{re.escape(key)}=([^;]+)", cookie_str)
            if match:
                return match.group(1)
        return None

    @classmethod
    def parse_login_tokens(cls, cookie_str: str) -> dict[str, str | None]:
        return {
            "stoken": cls._extract_cookie_value(cookie_str, ("stoken", "stoken_v2")),
            "stuid": cls._extract_cookie_value(
                cookie_str,
                ("stuid", "ltuid", "ltuid_v2", "account_id", "account_id_v2", "login_uid"),
            ),
            "mid": cls._extract_cookie_value(cookie_str, ("mid", "ltmid_v2", "account_mid_v2")),
        }

    def _build_headers(self, cookie: str) -> dict[str, str]:
        return get_default_headers(cookie, device_id=generate_device_id(), ds=generate_ds())

    async def _build_result(self, account: MihoyoAccount, message: str) -> dict[str, Any]:
        return {
            "account_id": account.id,
            "cookie_status": account.cookie_status,
            "message": message,
            "last_refresh_status": account.last_refresh_status,
            "last_refresh_message": account.last_refresh_message,
            "last_refresh_attempt_at": account.last_refresh_attempt_at,
            "last_cookie_check": account.last_cookie_check,
            "reauth_notified_at": account.reauth_notified_at,
        }

    @staticmethod
    def _build_reauth_message(reason: str) -> str:
        """
        统一生成“需要重新扫码”的用户提示。

        字段名里虽然还保留 `last_refresh_*` 历史命名，但当前业务语义已经收敛为
        “最近一次登录态校验结果”；这里统一口径，避免旧文案继续暗示系统仍会自动续期。
        """
        normalized_reason = reason.strip() or "登录态失效"
        if "重新扫码" in normalized_reason:
            return normalized_reason
        return f"{normalized_reason}，请重新扫码更新网页登录态"

    async def verify_cookie(self, account: MihoyoAccount) -> dict[str, str]:
        try:
            cookie = decrypt_cookie(account.cookie_encrypted or "")
        except Exception:
            return {"state": "reauth_required", "message": "账号 Cookie 无法解密，需要重新扫码"}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(VERIFY_URL, headers=self._build_headers(cookie))
                data = response.json()
        except Exception as exc:
            logger.warning("账号 %s 登录态校验网络异常: %s", account.id, exc)
            return {"state": "network_error", "message": f"网络异常，暂未确认失效: {exc}"}

        retcode = int(data.get("retcode", -1))
        if retcode == 0:
            return {"state": "valid", "message": "登录态有效"}
        if retcode in (-100, -101):
            return {"state": "expired", "message": "Cookie 已过期"}
        return {"state": "expired", "message": f"Cookie 校验失败（code: {retcode}）"}

    async def refresh_account_login_state(self, account: MihoyoAccount) -> dict[str, Any]:
        await ensure_account_columns(self.db.bind)
        previous_status = account.cookie_status
        now = utc_now_naive()
        account.last_refresh_attempt_at = now

        verify_result = await self.verify_cookie(account)
        if verify_result["state"] == "valid":
            account.cookie_status = "valid"
            account.last_cookie_check = now
            account.last_refresh_status = "valid"
            account.last_refresh_message = verify_result["message"]
            account.reauth_notified_at = None
            await self.db.commit()
            return await self._build_result(account, verify_result["message"])

        if verify_result["state"] == "network_error":
            account.last_refresh_status = "network_error"
            account.last_refresh_message = verify_result["message"]
            await self.db.commit()
            return await self._build_result(account, verify_result["message"])

        account.cookie_status = "reauth_required"
        account.last_refresh_status = "reauth_required"
        account.last_refresh_message = self._build_reauth_message(verify_result["message"])

        if account.cookie_status == "reauth_required" and previous_status != "reauth_required" and not account.reauth_notified_at:
            sent = await notification_service.send_reauth_required_notification(account.user_id, account, self.db)
            if sent:
                account.reauth_notified_at = utc_now_naive()

        await self.db.commit()
        return await self._build_result(account, account.last_refresh_message)

    async def ensure_account_ready_for_checkin(self, account: MihoyoAccount) -> dict[str, Any]:
        if account.cookie_status == "valid":
            return await self._build_result(account, account.last_refresh_message or "登录态有效")
        return await self.refresh_account_login_state(account)

    async def get_user(self, user_id: int) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()


