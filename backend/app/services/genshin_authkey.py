"""
原神 authkey 适配服务。

这里专门收口 HuTao 对齐后的 `POST JSON + SToken + DS(LK2)` 上游契约。
`GachaService` 只负责角色选择与导入编排，不能再把 Cookie/DS/XRpc 头散落在业务层，
否则后续任何协议调整都会重新退化成“先改一半、剩下一半忘在旧代码里”的高回归结构。
"""

from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import GameRole, MihoyoAccount
from app.services.account_credentials import AccountCredentialService, RootCredentialRefreshError
from app.utils.device import build_genshin_authkey_headers, generate_device_id
from app.utils.ds import generate_cn_gen1_ds_lk2

GENSHIN_AUTHKEY_API_URL = "https://api-takumi.mihoyo.com/binding/api/genAuthKey"
GENSHIN_GACHA_LOG_API_URL = "https://public-operation-hk4e.mihoyo.com/gacha_info/api/getGachaLog"
# 历史库里有一批国服角色缺失 `region`，这里只允许按 `hk4e_cn -> cn_gf01` 做最小补齐。
# 国际服不在本轮支持范围内，绝不能借 fallback 让它“顺手穿过去”。
GENSHIN_REGION_BY_GAME_BIZ = {
    "hk4e_cn": "cn_gf01",
}


class GenshinAuthkeyService:
    def __init__(self, db: AsyncSession, timeout: float = 15.0):
        self.db = db
        self.timeout = timeout

    async def generate_import_url(self, account: MihoyoAccount, role: GameRole) -> str:
        try:
            AccountCredentialService(self.db).get_root_credential_snapshot(account)
        except RootCredentialRefreshError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        payload = self._build_payload(role)
        response_payload = await self._request_authkey(account, payload)

        if response_payload.get("retcode") != 0:
            message = response_payload.get("message") or response_payload.get("msg") or "上游返回失败"
            raise HTTPException(status_code=400, detail=f"原神 authkey 生成失败：{message}")

        data_payload = response_payload.get("data") or {}
        if not isinstance(data_payload, dict):
            raise HTTPException(status_code=400, detail="原神 authkey 生成失败：上游返回了不符合预期的响应结构")

        authkey = str(data_payload.get("authkey") or "").strip()
        authkey_ver = str(data_payload.get("authkey_ver") or "").strip()
        sign_type = str(data_payload.get("sign_type") or "").strip()
        if not authkey or not authkey_ver or not sign_type:
            raise HTTPException(status_code=400, detail="原神 authkey 生成失败：上游未返回完整票据")

        params = {
            "authkey": authkey,
            "authkey_ver": authkey_ver,
            "sign_type": sign_type,
            "lang": "zh-cn",
            "gacha_type": "301",
        }
        return f"{GENSHIN_GACHA_LOG_API_URL}?{urlencode(params)}"

    def _normalize_supported_role(self, role: GameRole) -> tuple[str, str]:
        if role.game_biz != "hk4e_cn":
            raise HTTPException(status_code=400, detail="当前仅支持原神国服账号自动导入")

        region = (role.region or GENSHIN_REGION_BY_GAME_BIZ.get(role.game_biz) or "").strip()
        if not region:
            raise HTTPException(status_code=400, detail="该原神角色缺少区域信息，无法自动导入")

        return "hk4e_cn", region

    def _build_payload(self, role: GameRole) -> dict[str, Any]:
        game_biz, region = self._normalize_supported_role(role)
        try:
            game_uid = int(str(role.game_uid or "").strip())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="该原神角色 UID 非法，无法自动导入") from exc

        return {
            "auth_appid": "webview_gacha",
            "game_biz": game_biz,
            "game_uid": game_uid,
            "region": region,
        }

    async def _request_authkey(self, account: MihoyoAccount, payload: dict[str, Any]) -> dict[str, Any]:
        cookie = AccountCredentialService(self.db).build_stoken_cookie_for_root_api(account)
        headers = build_genshin_authkey_headers(
            cookie,
            device_id=generate_device_id(),
            ds=generate_cn_gen1_ds_lk2(),
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    GENSHIN_AUTHKEY_API_URL,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=400, detail=f"原神 authkey 生成失败：上游接口返回异常状态 {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=400, detail="原神 authkey 生成失败：无法连接上游接口") from exc

        try:
            response_payload = response.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="原神 authkey 生成失败：上游返回了无法解析的响应") from exc

        if not isinstance(response_payload, dict):
            raise HTTPException(status_code=400, detail="原神 authkey 生成失败：上游返回了不符合预期的响应结构")
        return response_payload
