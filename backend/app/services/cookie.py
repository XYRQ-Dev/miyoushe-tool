"""
Cookie 管理服务
- 加密存储
- 有效性验证
- 自动刷新（通过重新扫码）
"""

import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import MihoyoAccount
from app.utils.crypto import encrypt_cookie, decrypt_cookie
from app.utils.ds import generate_ds
from app.utils.device import get_default_headers, generate_device_id
from app.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)

# 用于验证 Cookie 有效性的 API
VERIFY_URL = "https://api-takumi.mihoyo.com/binding/api/getUserGameRolesByCookie"


class CookieService:
    """Cookie 管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def save_cookie(self, account: MihoyoAccount, cookie_str: str):
        """加密并保存 Cookie"""
        account.cookie_encrypted = encrypt_cookie(cookie_str)
        account.cookie_status = "valid"
        account.last_cookie_check = utc_now_naive()
        await self.db.commit()

    async def get_cookie(self, account: MihoyoAccount) -> str:
        """获取解密后的 Cookie"""
        if not account.cookie_encrypted:
            raise ValueError("该账号没有存储 Cookie")
        return decrypt_cookie(account.cookie_encrypted)

    async def verify_cookie(self, account: MihoyoAccount) -> bool:
        """
        验证 Cookie 是否仍然有效
        通过调用游戏角色查询 API 判断：
        - retcode == 0 → 有效
        - retcode == -100 或 -101 → 已过期
        """
        try:
            cookie = decrypt_cookie(account.cookie_encrypted)
        except Exception:
            logger.warning(f"账号 {account.id} Cookie 解密失败")
            return False

        device_id = generate_device_id()
        ds = generate_ds()
        headers = get_default_headers(cookie, device_id, ds)

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(VERIFY_URL, headers=headers)
                data = resp.json()
                retcode = data.get("retcode", -1)

                if retcode == 0:
                    return True
                elif retcode in (-100, -101):
                    logger.info(f"账号 {account.id} Cookie 已过期")
                    return False
                else:
                    logger.warning(f"账号 {account.id} Cookie 验证返回未知状态: {retcode}")
                    return False

        except Exception as e:
            logger.error(f"验证 Cookie 异常: {e}")
            # 网络异常不标记为过期
            return True
