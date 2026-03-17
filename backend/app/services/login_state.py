"""
账号登录态维护服务

集中处理 Cookie 校验、stoken 自动续期、状态流转与失效通知，避免：
1. 调度器、手动签到、账号页各自维护一套判定逻辑
2. 同一个账号在不同入口里被写成不同状态
3. 续期失败时既没有通知，也没有明确告诉用户“下一步该做什么”
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
from app.utils.crypto import decrypt_cookie, decrypt_text, encrypt_cookie
from app.utils.device import generate_device_id, get_default_headers
from app.utils.ds import generate_ds
from app.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)

VERIFY_URL = "https://api-takumi.mihoyo.com/binding/api/getUserGameRolesByCookie"
GET_COOKIE_BY_STOKEN_URL = "https://api-takumi.mihoyo.com/auth/api/getCookieAccountInfoBySToken"
GET_TOKEN_BY_STOKEN_URL = "https://passport-api.mihoyo.com/account/ma-cn-session/app/getTokenBySToken"


class LoginStateService:
    """负责米游社账号登录态维护。"""

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
    def _replace_cookie_value(cls, cookie_str: str, key: str, value: str) -> str:
        segments: list[str] = []
        replaced = False
        for part in cookie_str.split(";"):
            normalized = part.strip()
            if not normalized:
                continue
            if normalized.startswith(f"{key}="):
                segments.append(f"{key}={value}")
                replaced = True
            else:
                segments.append(normalized)
        if not replaced:
            segments.append(f"{key}={value}")
        return "; ".join(segments)

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

    @staticmethod
    def _requires_mid(stoken: str | None) -> bool:
        return bool(stoken and stoken.startswith("v2_"))

    @classmethod
    def is_auto_refresh_available(cls, account: MihoyoAccount) -> bool:
        if not account.stoken_encrypted or not account.stuid:
            return False
        try:
            stoken = decrypt_text(account.stoken_encrypted)
        except Exception:
            return False
        if cls._requires_mid(stoken) and not account.mid:
            return False
        return True

    def _build_headers(self, cookie: str) -> dict[str, str]:
        return get_default_headers(cookie, device_id=generate_device_id(), ds=generate_ds())

    def _build_result(self, account: MihoyoAccount, message: str) -> dict[str, Any]:
        return {
            "account_id": account.id,
            "cookie_status": account.cookie_status,
            "message": message,
            "last_refresh_status": account.last_refresh_status,
            "last_refresh_message": account.last_refresh_message,
            "last_refresh_attempt_at": account.last_refresh_attempt_at,
            "last_cookie_check": account.last_cookie_check,
            "reauth_notified_at": account.reauth_notified_at,
            "auto_refresh_available": self.is_auto_refresh_available(account),
        }

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

    async def refresh_cookie_token(self, account: MihoyoAccount) -> dict[str, Any]:
        if not self.is_auto_refresh_available(account):
            return {"success": False, "state": "reauth_required", "message": "缺少自动续期凭据，需要重新扫码"}

        try:
            stoken = decrypt_text(account.stoken_encrypted or "")
        except Exception:
            return {"success": False, "state": "reauth_required", "message": "续期凭据损坏，需要重新扫码"}

        stoken_cookie = f"stuid={account.stuid}; stoken={stoken}"
        if self._requires_mid(stoken):
            if not account.mid:
                return {"success": False, "state": "reauth_required", "message": "缺少 mid，无法自动续期，请重新扫码"}
            stoken_cookie += f"; mid={account.mid}"

        headers = self._build_headers(stoken_cookie)

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                token_probe = await client.get(GET_TOKEN_BY_STOKEN_URL, headers=headers)
                token_probe_data = token_probe.json()
                if int(token_probe_data.get("retcode", -1)) != 0:
                    return {"success": False, "state": "reauth_required", "message": "续期凭据已失效，需要重新扫码"}

                response = await client.get(GET_COOKIE_BY_STOKEN_URL, headers=headers)
                data = response.json()
        except Exception as exc:
            logger.warning("账号 %s 自动续期网络异常: %s", account.id, exc)
            return {"success": False, "state": "expired", "message": f"自动续期暂时失败: {exc}"}

        if int(data.get("retcode", -1)) != 0:
            return {"success": False, "state": "reauth_required", "message": "续期凭据已失效，需要重新扫码"}

        cookie_token = (data.get("data") or {}).get("cookie_token")
        if not cookie_token:
            return {"success": False, "state": "reauth_required", "message": "未获取到新的 CookieToken，需要重新扫码"}

        try:
            cookie = decrypt_cookie(account.cookie_encrypted or "")
        except Exception:
            return {"success": False, "state": "reauth_required", "message": "账号 Cookie 无法解密，需要重新扫码"}

        new_cookie = self._replace_cookie_value(cookie, "cookie_token", cookie_token)
        account.cookie_encrypted = encrypt_cookie(new_cookie)
        account.cookie_token_updated_at = utc_now_naive()
        return {"success": True, "message": "自动续期成功", "cookie": new_cookie}

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
            return self._build_result(account, verify_result["message"])

        if verify_result["state"] == "network_error":
            account.last_refresh_status = "network_error"
            account.last_refresh_message = verify_result["message"]
            await self.db.commit()
            return self._build_result(account, verify_result["message"])

        account.cookie_status = "refreshing"
        account.last_refresh_status = "refreshing"
        account.last_refresh_message = "检测到登录态异常，正在尝试自动续期"
        await self.db.commit()

        refresh_result = await self.refresh_cookie_token(account)
        if refresh_result.get("success"):
            reverify_result = await self.verify_cookie(account)
            if reverify_result["state"] == "valid":
                account.cookie_status = "valid"
                account.last_cookie_check = utc_now_naive()
                if not account.cookie_token_updated_at:
                    account.cookie_token_updated_at = utc_now_naive()
                account.last_refresh_status = "success"
                account.last_refresh_message = refresh_result["message"]
                account.reauth_notified_at = None
                await self.db.commit()
                return self._build_result(account, refresh_result["message"])

            account.cookie_status = "expired"
            account.last_refresh_status = "warning"
            account.last_refresh_message = "自动续期已执行，但复验未恢复为有效登录态"
            await self.db.commit()
            return self._build_result(account, account.last_refresh_message)

        account.cookie_status = refresh_result["state"]
        account.last_refresh_status = refresh_result["state"]
        account.last_refresh_message = refresh_result["message"]

        if account.cookie_status == "reauth_required" and previous_status != "reauth_required" and not account.reauth_notified_at:
            sent = await notification_service.send_reauth_required_notification(account.user_id, account, self.db)
            if sent:
                account.reauth_notified_at = utc_now_naive()

        await self.db.commit()
        return self._build_result(account, account.last_refresh_message or refresh_result["message"])

    async def ensure_account_ready_for_checkin(self, account: MihoyoAccount) -> dict[str, Any]:
        if account.cookie_status == "valid":
            return self._build_result(account, account.last_refresh_message or "登录态有效")
        return await self.refresh_account_login_state(account)

    async def get_user(self, user_id: int) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
