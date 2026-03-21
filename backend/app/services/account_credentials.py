"""
账号根凭据补齐与工作 Cookie 重建服务。

本文件解决的是“高权限根凭据”和“工作 Cookie”两层状态长期被混在一起的问题：
1. `stoken / ltoken / cookie_token / login_ticket` 是根凭据，负责后续补齐与自愈
2. `cookie_encrypted` 只是当前可直接给签到、兑换等旧模块消费的派生工作态

这里必须把两层拆开处理，而不能继续沿用“登录成功时顺手写一串 Cookie 就算完成”的旧思路。
否则后续维护会持续踩到三个高频误区：
- 误以为数据库里那串工作 Cookie 才是唯一真实凭据，导致根凭据丢失后无法自愈
- 误把 `cookie_status` 当作高权限登录状态，根凭据明明还有效却提示用户重登
- 误在不同入口各自拼 Cookie，最终让字段名、状态机和排障口径慢慢漂移
"""

import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import MihoyoAccount
from app.utils.crypto import decrypt_text, encrypt_cookie, encrypt_text
from app.utils.device import build_hyperion_user_agent, generate_device_id
from app.utils.ds import generate_ds_v2
from app.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)

GET_LTOKEN_BY_STOKEN_URL = "https://passport-api.mihoyo.com/account/auth/api/getLTokenBySToken"
GET_COOKIE_TOKEN_BY_STOKEN_URL = "https://passport-api.mihoyo.com/account/auth/api/getCookieAccountInfoBySToken"
ROOT_CREDENTIAL_REAUTH_MESSAGE = "高权限根凭据已失效，请重新扫码升级高权限登录"


class RootCredentialRefreshError(RuntimeError):
    """服务端明确拒绝当前根凭据时抛出的业务异常。"""


class RootCredentialNetworkError(RuntimeError):
    """与官方接口通信失败时抛出的网络异常。"""


class AccountCredentialService:
    """
    管理账号根凭据与派生工作 Cookie。

    注意：本服务不在内部 `commit`。
    原因不是“省几行代码”，而是同一个调用链里通常还要连带更新账号、角色或通知状态；
    如果在这里偷偷提交事务，外层调用者会失去事务边界控制，后续很难定位“哪一步把半成品状态落库了”。
    """

    def __init__(self, db: AsyncSession, *, timeout: float = 15.0):
        self.db = db
        self.timeout = timeout

    def _build_stoken_cookie(self, account: MihoyoAccount, stoken: str) -> str:
        cookie_parts = [
            f"stuid={account.stuid}",
            f"ltuid={account.stuid}",
            f"ltuid_v2={account.stuid}",
            f"account_id={account.stuid}",
            f"account_id_v2={account.stuid}",
            f"login_uid={account.stuid}",
            f"stoken_v2={stoken}",
        ]
        if account.mid:
            cookie_parts.extend(
                [
                    f"mid={account.mid}",
                    f"ltmid_v2={account.mid}",
                    f"account_mid_v2={account.mid}",
                ]
            )
        return "; ".join(cookie_parts)

    def _build_request_headers(self, cookie: str) -> dict[str, str]:
        # 这里显式按“移动端 + DS + 设备号”组织请求头。
        # 若后续维护者把它简化成只带 Cookie，测试通常不会立刻暴露问题，
        # 但真机联调时很容易变成“本地偶尔能过、线上稳定失败”的风控噪音。
        return {
            "Accept": "application/json",
            "User-Agent": build_hyperion_user_agent(),
            "Referer": "https://app.mihoyo.com/",
            "x-rpc-app_version": "2.90.1",
            "x-rpc-client_type": "5",
            "x-rpc-device_id": generate_device_id(),
            "DS": generate_ds_v2(),
            "Cookie": cookie,
        }

    @staticmethod
    def _unwrap_response(payload: dict[str, Any], *, action: str) -> dict[str, Any]:
        retcode = int(payload.get("retcode", -1))
        if retcode == 0:
            data = payload.get("data")
            if isinstance(data, dict):
                return data
            raise RootCredentialRefreshError(f"{action} 返回缺少 data")

        message = str(payload.get("message") or payload.get("msg") or "未知错误")
        raise RootCredentialRefreshError(f"{action}失败（retcode={retcode}）：{message}")

    @staticmethod
    def _build_reauth_message(reason: str) -> str:
        normalized_reason = reason.strip() or ROOT_CREDENTIAL_REAUTH_MESSAGE
        if "重新扫码" in normalized_reason:
            return normalized_reason
        return f"{normalized_reason}，请重新扫码升级高权限登录"

    def _mark_root_credentials_invalid(self, account: MihoyoAccount, reason: str) -> dict[str, str]:
        message = self._build_reauth_message(reason)
        now = utc_now_naive()
        # 自愈失败时必须同时打落 `credential_status` 和 `cookie_status`。
        # 如果只改其中一个，界面会出现“高权限登录正常但 Cookie 失效无法修复”
        # 或“Cookie 需要重登但根凭据仍显示可用”的矛盾状态，排障会直接失焦。
        account.credential_status = "reauth_required"
        account.cookie_status = "reauth_required"
        account.last_token_refresh_at = now
        account.last_token_refresh_status = "reauth_required"
        account.last_token_refresh_message = message
        account.last_refresh_status = "reauth_required"
        account.last_refresh_message = message
        return {"state": "reauth_required", "message": message}

    async def _get_json(self, url: str, *, cookie: str, action: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=self._build_request_headers(cookie))
                response.raise_for_status()
                payload = response.json()
        except RootCredentialRefreshError:
            raise
        except Exception as exc:
            raise RootCredentialNetworkError(f"{action}遇到网络异常: {exc}") from exc

        return self._unwrap_response(payload, action=action)

    async def persist_login_result(self, account: MihoyoAccount, login_result: dict[str, Any]) -> dict[str, str]:
        """
        保存登录成功后的根凭据，并立即尝试补齐工作 Cookie。

        这里统一收口“登录成功后账号该怎么写库”的入口，避免 WebSocket、短信登录、
        后续票据换取各自直接改模型字段。只要入口一分叉，字段含义和默认状态迟早会不一致。
        """
        account.stoken_encrypted = encrypt_text(login_result["stoken"])
        account.login_ticket_encrypted = (
            encrypt_text(login_result["login_ticket"])
            if login_result.get("login_ticket")
            else None
        )
        account.ltoken_encrypted = None
        account.cookie_token_encrypted = None
        account.cookie_encrypted = None
        account.stuid = str(login_result["stuid"])
        account.mid = str(login_result["mid"])
        account.mihoyo_uid = str(login_result["stuid"])
        account.credential_source = login_result.get("credential_source", "passport_qr")
        account.credential_status = "valid"
        account.cookie_status = "unknown"
        account.last_cookie_check = None
        account.cookie_token_updated_at = None
        account.last_refresh_attempt_at = utc_now_naive()
        account.last_refresh_status = "pending"
        account.last_refresh_message = "官方高权限根凭据已保存，正在补齐工作 Cookie"
        account.reauth_notified_at = None

        ensure_result = await self.ensure_work_cookie(account)
        if ensure_result["state"] == "valid":
            account.last_refresh_status = "success"
            account.last_refresh_message = "高权限根凭据已保存并已补齐工作 Cookie"
        elif ensure_result["state"] == "network_error":
            # 登录刚成功时保住根凭据本身比把整条链路直接打成“重登”更重要；
            # 否则一次瞬时网络抖动就会把刚扫码成功的账号误标成必须重新登录。
            account.credential_status = "valid"
            account.cookie_status = "unknown"
            account.last_refresh_status = "network_error"
            account.last_refresh_message = ensure_result["message"]
        else:
            account.last_refresh_status = "reauth_required"
            account.last_refresh_message = ensure_result["message"]

        return ensure_result

    async def refresh_root_tokens(self, account: MihoyoAccount) -> dict[str, str]:
        """
        用 `SToken` 向官方接口补齐 `ltoken` 和 `cookie_token`。

        之所以把两个字段单独加密保存，而不是每次都从工作 Cookie 里拆，是因为它们本身属于可重建
        工作态的根凭据。若只把它们埋在 Cookie 串里，后续一旦 Cookie 过期、字段名变体增多或某次
        重建遗漏，就会失去“自愈所需的最小真相”。
        """
        now = utc_now_naive()
        account.last_token_refresh_at = now

        if not account.stoken_encrypted or not account.stuid:
            return self._mark_root_credentials_invalid(account, "缺少高权限根凭据")

        try:
            stoken = decrypt_text(account.stoken_encrypted)
        except Exception:
            return self._mark_root_credentials_invalid(account, "高权限根凭据无法解密")

        stoken_cookie = self._build_stoken_cookie(account, stoken)
        try:
            ltoken_payload = await self._get_json(
                GET_LTOKEN_BY_STOKEN_URL,
                cookie=stoken_cookie,
                action="获取 ltoken",
            )
            cookie_token_payload = await self._get_json(
                GET_COOKIE_TOKEN_BY_STOKEN_URL,
                cookie=stoken_cookie,
                action="获取 cookie_token",
            )
        except RootCredentialNetworkError as exc:
            message = str(exc)
            account.last_token_refresh_status = "network_error"
            account.last_token_refresh_message = message
            return {"state": "network_error", "message": message}
        except RootCredentialRefreshError as exc:
            return self._mark_root_credentials_invalid(account, str(exc))

        ltoken = str(ltoken_payload.get("ltoken") or ltoken_payload.get("ltoken_v2") or "").strip()
        cookie_token = str(
            cookie_token_payload.get("cookie_token") or cookie_token_payload.get("cookie_token_v2") or ""
        ).strip()
        cookie_token_uid = str(
            cookie_token_payload.get("uid") or cookie_token_payload.get("stuid") or account.stuid or ""
        ).strip()

        if not ltoken or not cookie_token:
            return self._mark_root_credentials_invalid(account, "官方接口未返回完整根凭据")

        account.ltoken_encrypted = encrypt_text(ltoken)
        account.cookie_token_encrypted = encrypt_text(cookie_token)
        if cookie_token_uid:
            account.stuid = cookie_token_uid
            account.mihoyo_uid = cookie_token_uid
        account.credential_status = "valid"
        account.cookie_token_updated_at = now
        account.last_token_refresh_status = "valid"
        account.last_token_refresh_message = "已使用高权限根凭据补齐 ltoken 与 cookie_token"
        return {"state": "valid", "message": account.last_token_refresh_message}

    def rebuild_work_cookie(self, account: MihoyoAccount) -> dict[str, str]:
        """
        用已保存的根凭据重建工作 Cookie。

        工作 Cookie 必须被视为“可随时丢弃并重建的派生物”，而不是唯一事实来源。
        如果后续维护继续把它当唯一真相，任何一次 Cookie 过期都会把系统重新拖回“只能让用户重登”
        的旧设计，完全浪费掉已经接入的 Passport 高权限登录。
        """
        try:
            stoken = decrypt_text(account.stoken_encrypted or "")
            ltoken = decrypt_text(account.ltoken_encrypted or "")
            cookie_token = decrypt_text(account.cookie_token_encrypted or "")
        except Exception:
            return self._mark_root_credentials_invalid(account, "高权限根凭据无法解密")

        if not account.stuid or not stoken or not ltoken or not cookie_token:
            return self._mark_root_credentials_invalid(account, "高权限根凭据不完整")

        cookie_parts = [
            f"stuid={account.stuid}",
            f"ltuid={account.stuid}",
            f"ltuid_v2={account.stuid}",
            f"account_id={account.stuid}",
            f"account_id_v2={account.stuid}",
            f"login_uid={account.stuid}",
            f"stoken_v2={stoken}",
            f"ltoken_v2={ltoken}",
            f"cookie_token={cookie_token}",
        ]
        if account.mid:
            cookie_parts.extend(
                [
                    f"mid={account.mid}",
                    f"ltmid_v2={account.mid}",
                    f"account_mid_v2={account.mid}",
                ]
            )

        rebuilt_cookie = "; ".join(cookie_parts)
        now = utc_now_naive()
        account.cookie_encrypted = encrypt_cookie(rebuilt_cookie)
        account.cookie_status = "valid"
        account.last_cookie_check = now
        account.last_refresh_status = "valid"
        account.last_refresh_message = "工作 Cookie 已使用根凭据自愈重建"
        account.reauth_notified_at = None
        return {"state": "valid", "message": account.last_refresh_message, "cookie": rebuilt_cookie}

    async def ensure_work_cookie(self, account: MihoyoAccount) -> dict[str, str]:
        """
        确保账号具备可直接消费的工作 Cookie。

        这里故意拆成“先补齐根凭据，再派生工作 Cookie”两步，而不是直接从旧 Cookie 上修修补补。
        原因是旧 Cookie 可能已经过期、字段不全或混入历史命名；若继续在旧串上做增量拼接，
        最终得到的只会是难以验证、难以排障的半残状态。
        """
        refresh_result = await self.refresh_root_tokens(account)
        if refresh_result["state"] != "valid":
            return refresh_result
        return self.rebuild_work_cookie(account)
