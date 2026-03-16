"""
签到核心逻辑
参考 Starward 的 HyperionClient 和 GameRecordService 实现
通过米游社 API 执行每日签到
"""

import asyncio
import json
import logging
import random
from datetime import datetime
from typing import Optional, List

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import MihoyoAccount, GameRole
from app.models.task_log import TaskLog
from app.schemas.task_log import CheckinResult, CheckinSummary
from app.utils.crypto import decrypt_cookie
from app.utils.ds import generate_ds
from app.utils.device import generate_device_id, get_default_headers

logger = logging.getLogger(__name__)

# 米游社签到 API 端点
SIGN_INFO_URL = "https://api-takumi.mihoyo.com/event/luna/info"
SIGN_URL = "https://api-takumi.mihoyo.com/event/luna/sign"
GAME_ROLES_URL = "https://api-takumi.mihoyo.com/binding/api/getUserGameRolesByCookie"

# 各游戏的 ActId（签到活动标识）
GAME_ACT_IDS = {
    "hk4e_cn": "e202311201442471",        # 原神国服
    "hk4e_bilibili": "e202311201442471",   # 原神B站
    "hkrpg_cn": "e202304121516551",        # 星铁国服
    "hkrpg_bilibili": "e202304121516551",  # 星铁B站
    "nap_cn": "e202406031448091",          # 绝区零国服
    "bh3_cn": "e202306201626331",          # 崩坏3国服
}


class CheckinService:
    """签到服务，执行实际的签到 API 调用"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.device_id = generate_device_id()

    async def execute_for_user(self, user_id: int) -> CheckinSummary:
        """
        为指定用户的所有账号执行签到
        遍历每个账号下的每个游戏角色，依次签到
        """
        # 查询该用户所有有效账号
        result = await self.db.execute(
            select(MihoyoAccount).where(
                MihoyoAccount.user_id == user_id,
                MihoyoAccount.cookie_status == "valid",
            )
        )
        accounts = result.scalars().all()

        all_results: List[CheckinResult] = []

        for account in accounts:
            # 解密 Cookie
            try:
                cookie = decrypt_cookie(account.cookie_encrypted)
            except Exception as e:
                logger.error(f"账号 {account.id} Cookie 解密失败: {e}")
                all_results.append(CheckinResult(
                    account_id=account.id,
                    status="failed",
                    message=f"Cookie 解密失败: {str(e)}",
                ))
                continue

            # 获取该账号下所有启用的游戏角色
            roles_result = await self.db.execute(
                select(GameRole).where(
                    GameRole.account_id == account.id,
                    GameRole.is_enabled == True,
                )
            )
            roles = roles_result.scalars().all()

            if not roles:
                logger.info(f"账号 {account.id} 没有启用的游戏角色，跳过")
                continue

            for role in roles:
                # 角色间随机延迟 3-6 秒，避免触发风控
                if all_results:
                    delay = random.uniform(3, 6)
                    logger.info(f"等待 {delay:.1f} 秒后执行下一个角色的签到...")
                    await asyncio.sleep(delay)

                result = await self._checkin_role(account, role, cookie)
                all_results.append(result)

                # 记录到数据库
                log = TaskLog(
                    account_id=account.id,
                    game_role_id=role.id,
                    task_type="checkin",
                    status=result.status,
                    message=result.message,
                    total_sign_days=result.total_sign_days,
                )
                self.db.add(log)

            await self.db.commit()

        # 汇总结果
        summary = CheckinSummary(
            total=len(all_results),
            success=sum(1 for r in all_results if r.status == "success"),
            failed=sum(1 for r in all_results if r.status == "failed"),
            already_signed=sum(1 for r in all_results if r.status == "already_signed"),
            risk=sum(1 for r in all_results if r.status == "risk"),
            results=all_results,
        )

        return summary

    async def _checkin_role(
        self,
        account: MihoyoAccount,
        role: GameRole,
        cookie: str,
    ) -> CheckinResult:
        """
        为单个游戏角色执行签到
        流程：先查询签到状态 → 未签到则执行签到 → 返回结果
        """
        act_id = GAME_ACT_IDS.get(role.game_biz)
        if not act_id:
            return CheckinResult(
                account_id=account.id,
                game_role_id=role.id,
                status="failed",
                message=f"不支持的游戏类型: {role.game_biz}",
            )

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # 步骤 1：查询今日签到状态
                info = await self._get_sign_info(client, cookie, act_id, role)
                if info is None:
                    return CheckinResult(
                        account_id=account.id,
                        game_role_id=role.id,
                        status="failed",
                        message="查询签到状态失败",
                    )

                if info.get("is_sign"):
                    return CheckinResult(
                        account_id=account.id,
                        game_role_id=role.id,
                        status="already_signed",
                        message="今日已签到",
                        total_sign_days=info.get("total_sign_day"),
                    )

                # 步骤 2：随机延迟 1-5 秒后执行签到
                delay = random.uniform(1, 5)
                await asyncio.sleep(delay)

                # 步骤 3：执行签到
                sign_result = await self._do_sign(client, cookie, act_id, role)
                return sign_result

        except Exception as e:
            logger.error(f"角色 {role.game_uid} 签到异常: {e}")
            return CheckinResult(
                account_id=account.id,
                game_role_id=role.id,
                status="failed",
                message=f"签到异常: {str(e)}",
            )

    async def _get_sign_info(
        self,
        client: httpx.AsyncClient,
        cookie: str,
        act_id: str,
        role: GameRole,
    ) -> Optional[dict]:
        """查询签到状态"""
        query = f"act_id={act_id}&region={role.region}&uid={role.game_uid}"
        ds = generate_ds(query=query)
        headers = get_default_headers(cookie, self.device_id, ds)

        try:
            resp = await client.get(
                SIGN_INFO_URL,
                params={"act_id": act_id, "region": role.region, "uid": role.game_uid},
                headers=headers,
            )
            data = resp.json()
            if data.get("retcode") == 0:
                return data.get("data", {})
            else:
                logger.warning(f"查询签到状态失败: {data}")
                return None
        except Exception as e:
            logger.error(f"查询签到状态异常: {e}")
            return None

    async def _do_sign(
        self,
        client: httpx.AsyncClient,
        cookie: str,
        act_id: str,
        role: GameRole,
    ) -> CheckinResult:
        """执行签到请求"""
        body = json.dumps({
            "act_id": act_id,
            "region": role.region,
            "uid": role.game_uid,
        }, separators=(",", ":"))

        ds = generate_ds(body=body)
        headers = get_default_headers(cookie, self.device_id, ds)
        headers["Content-Type"] = "application/json"

        try:
            resp = await client.post(
                SIGN_URL,
                content=body,
                headers=headers,
            )
            data = resp.json()

            retcode = data.get("retcode", -1)

            if retcode == 0:
                sign_data = data.get("data", {})
                # 检查是否触发风控
                if sign_data.get("is_risk") or sign_data.get("gt", ""):
                    return CheckinResult(
                        account_id=role.account_id,
                        game_role_id=role.id,
                        status="risk",
                        message="签到触发风控验证，需要人工处理",
                    )
                return CheckinResult(
                    account_id=role.account_id,
                    game_role_id=role.id,
                    status="success",
                    message="签到成功",
                    total_sign_days=sign_data.get("total_sign_day"),
                )
            elif retcode == -5003:
                # 已经签到过
                return CheckinResult(
                    account_id=role.account_id,
                    game_role_id=role.id,
                    status="already_signed",
                    message="今日已签到",
                )
            else:
                return CheckinResult(
                    account_id=role.account_id,
                    game_role_id=role.id,
                    status="failed",
                    message=f"签到失败: {data.get('message', '未知错误')} (code: {retcode})",
                )

        except Exception as e:
            logger.error(f"签到请求异常: {e}")
            return CheckinResult(
                account_id=role.account_id,
                game_role_id=role.id,
                status="failed",
                message=f"签到请求异常: {str(e)}",
            )

    async def fetch_game_roles(self, cookie: str) -> List[dict]:
        """
        通过 Cookie 获取该账号绑定的所有游戏角色
        用于扫码登录成功后自动导入角色信息
        """
        ds = generate_ds()
        headers = get_default_headers(cookie, self.device_id, ds)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(GAME_ROLES_URL, headers=headers)
            data = resp.json()

            if data.get("retcode") == 0:
                return data.get("data", {}).get("list", [])
            else:
                logger.warning(f"获取游戏角色失败: {data}")
                return []
