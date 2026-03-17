"""
签到核心逻辑

本模块的签到链路明确按 Starward 的 Hyperion 实现对齐，尤其是：
1. act_id / signgame 的游戏映射
2. DS 生成方式
3. device_id / device_fp / 移动端 UA 的整套请求参数
4. 查询后短延迟 + 角色间 finally 延迟的风控规避策略

这些机制必须成套存在，不能只改其中某一项。
如果后续维护时“看起来某个字段没用”而被删掉，最常见的后果就是：
- 原神还能工作，星穹铁道 / 崩坏3 / 绝区零中的某一条链路稳定失败
- 接口偶发返回风控或参数校验错误，但日志只能看到泛化失败
"""

import asyncio
import json
import logging
import random
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import MihoyoAccount, GameRole
from app.models.task_log import TaskLog
from app.schemas.task_log import CheckinResult, CheckinSummary
from app.services.login_state import LoginStateService
from app.services.system_settings import SystemSettingsService
from app.utils.crypto import decrypt_cookie
from app.utils.device import (
    DEVICE_FP_URL,
    HYPERION_APP_VERSION,
    HYPERION_SIGN_SALT,
    build_device_fp_payload,
    build_hyperion_headers,
    generate_device_fp,
    generate_device_id,
)
from app.utils.ds import generate_cn_dynamic_secret, generate_ds
from app.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)

SIGN_INFO_URL = "https://api-takumi.mihoyo.com/event/luna/info"
SIGN_URL = "https://api-takumi.mihoyo.com/event/luna/sign"
SIGN_REWARDS_URL = "https://api-takumi.mihoyo.com/event/luna/home"
GAME_ROLES_URL = "https://api-takumi.mihoyo.com/binding/api/getUserGameRolesByCookie"


@dataclass(frozen=True)
class CheckinGameConfig:
    act_id: str
    sign_game: str
    # 并非所有签到活动都会接受 x-rpc-signgame。
    # 崩坏3当前需按参考实现显式关闭该请求头；若误恢复为统一下发，
    # 最直观的现象通常不是“参数非法”，而是上游持续返回业务态失败，排障成本很高。
    send_sign_game: bool = True
    info_url: str = SIGN_INFO_URL
    sign_url: str = SIGN_URL
    rewards_url: str = SIGN_REWARDS_URL
    referer: str = "https://act.mihoyo.com/"
    origin: str = "https://act.mihoyo.com"


CHECKIN_GAME_CONFIGS: dict[str, CheckinGameConfig] = {
    "hk4e_cn": CheckinGameConfig(act_id="e202311201442471", sign_game="hk4e"),
    "hk4e_bilibili": CheckinGameConfig(act_id="e202311201442471", sign_game="hk4e"),
    "hkrpg_cn": CheckinGameConfig(act_id="e202304121516551", sign_game="hkrpg"),
    "hkrpg_bilibili": CheckinGameConfig(act_id="e202304121516551", sign_game="hkrpg"),
    # 崩坏3国服官服这里故意向参考仓库对齐为新的活动号，并关闭 x-rpc-signgame：
    # 1. 用户实测旧 act_id 会稳定落入 -500007 维护态，说明“能打到接口”不等于“活动参数正确”
    # 2. 参考实现对 bh3 只保留专用活动页 Referer，不发送 x-rpc-signgame
    # 如果后续要改回统一头部，必须重新做真实账号验证，否则很容易回退到“查询链路表面可达、业务上始终失败”。
    "bh3_cn": CheckinGameConfig(
        act_id="e202306201626331",
        sign_game="bh3",
        send_sign_game=False,
        referer="https://webstatic.mihoyo.com/bbs/event/signin/bh3/index.html?bbs_auth_required=true&act_id=e202306201626331&bbs_presentation_style=fullscreen&utm_source=bbs&utm_medium=mys&utm_campaign=icon",
        origin="https://webstatic.mihoyo.com",
    ),
    # 绝区零国服官服不走通用 event/luna/info|sign，而是使用 act-nap-api 的 zzz 专属路径。
    # 如果误复用旧链路，最常见症状不是“明确报参数错”，而是查询/签到始终落在业务失败里，难以定位。
    "nap_cn": CheckinGameConfig(
        act_id="e202406242138391",
        sign_game="zzz",
        info_url="https://act-nap-api.mihoyo.com/event/luna/zzz/info",
        sign_url="https://act-nap-api.mihoyo.com/event/luna/zzz/sign",
        rewards_url="https://act-nap-api.mihoyo.com/event/luna/zzz/home",
        referer="https://act.hoyolab.com/bbs/event/signin/zzz/e202406242138391.html?act_id=e202406242138391",
        origin="https://act.hoyolab.com",
    ),
}
SUPPORTED_CHECKIN_BIZ = tuple(CHECKIN_GAME_CONFIGS.keys())


def is_checkin_supported_game(game_biz: str) -> bool:
    """
    当前仅原神、星穹铁道、崩坏3、绝区零的国服官服签到链路已完成适配。

    其他未接入角色即便已通过账号导入拿到，也不能误导性地继续走签到流程，
    否则最坏情况不是“签到失败”，而是向未验证接口发请求并制造脏日志。
    """
    return game_biz in CHECKIN_GAME_CONFIGS


class CheckinApiError(Exception):
    """把上游 retcode/message 包装成结构化异常，避免业务层只能拿到一个 None。"""

    def __init__(self, stage: str, retcode: int, message: str, game_biz: str):
        self.stage = stage
        self.retcode = retcode
        self.game_biz = game_biz
        self.upstream_message = message or "未知错误"
        super().__init__(f"{stage}失败: {self.upstream_message} (code: {retcode}, game: {game_biz})")


class CheckinService:
    """签到服务，执行实际的签到 API 调用"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings_service = SystemSettingsService(db)

    def _build_result_context(self, account: MihoyoAccount, role: GameRole | None = None) -> dict[str, Any]:
        """
        为签到结果补充展示上下文。

        邮件通知和结果页都需要知道“哪一个账号、哪一个游戏、哪一个角色”出了结果；
        如果这里只有状态和消息，用户看到“签到成功/失败”时无法定位对象，排障成本会很高。
        """
        return {
            "account_nickname": account.nickname or account.mihoyo_uid or f"账号#{account.id}",
            "game_biz": role.game_biz if role else None,
            "game_nickname": (role.nickname or role.game_uid) if role else None,
        }

    async def execute_for_user(self, user_id: int) -> CheckinSummary:
        """
        为指定用户的所有账号执行签到。

        角色级风控延迟必须放在批处理主流程，而不是底层 HTTP 工具里：
        - 查询后短延迟只对“未签到 -> 立即签到”的链路生效
        - 角色间延迟需要覆盖成功、失败、异常等所有调用过 API 的分支
        """
        result = await self.db.execute(
            select(MihoyoAccount).where(
                MihoyoAccount.user_id == user_id,
                MihoyoAccount.cookie_encrypted.is_not(None),
            )
        )
        accounts = result.scalars().all()

        all_results: list[CheckinResult] = []
        login_state_service = LoginStateService(self.db)

        async with httpx.AsyncClient(timeout=30) as client:
            device_state = await self._ensure_device_state(client)

            for account in accounts:
                roles_result = await self.db.execute(
                    select(GameRole).where(
                        GameRole.account_id == account.id,
                        GameRole.is_enabled.is_(True),
                        GameRole.game_biz.in_(SUPPORTED_CHECKIN_BIZ),
                    )
                )
                roles = roles_result.scalars().all()

                if not roles:
                    logger.info("账号 %s 没有已启用且已适配签到的游戏角色，跳过", account.id)
                    continue

                if account.cookie_status != "valid":
                    login_state = await login_state_service.refresh_account_login_state(account)
                    if login_state["cookie_status"] != "valid":
                        for role in roles:
                            all_results.append(
                                CheckinResult(
                                    account_id=account.id,
                                    game_role_id=role.id,
                                    status="failed",
                                    message=login_state["message"],
                                    **self._build_result_context(account, role),
                                )
                            )
                            self.db.add(
                                TaskLog(
                                    account_id=account.id,
                                    game_role_id=role.id,
                                    task_type="checkin",
                                    status="failed",
                                    message=login_state["message"],
                                )
                            )
                        await self.db.commit()
                        continue

                try:
                    cookie = decrypt_cookie(account.cookie_encrypted)
                except Exception as exc:
                    logger.error("账号 %s Cookie 解密失败: %s", account.id, exc)
                    all_results.append(
                        CheckinResult(
                            account_id=account.id,
                            status="failed",
                            message=f"Cookie 解密失败: {exc}",
                            **self._build_result_context(account),
                        )
                    )
                    continue

                for role in roles:
                    result = await self._checkin_role(account, role, cookie, client, device_state)
                    all_results.append(result)
                    self.db.add(
                        TaskLog(
                            account_id=account.id,
                            game_role_id=role.id,
                            task_type="checkin",
                            status=result.status,
                            message=result.message,
                            total_sign_days=result.total_sign_days,
                        )
                    )

                await self.db.commit()

        return CheckinSummary(
            total=len(all_results),
            success=sum(1 for item in all_results if item.status == "success"),
            failed=sum(1 for item in all_results if item.status == "failed"),
            already_signed=sum(1 for item in all_results if item.status == "already_signed"),
            risk=sum(1 for item in all_results if item.status == "risk"),
            results=all_results,
        )

    async def _checkin_role(
        self,
        account: MihoyoAccount,
        role: GameRole,
        cookie: str,
        client: httpx.AsyncClient,
        device_state: tuple[str, str],
    ) -> CheckinResult:
        """
        为单个角色执行签到。

        注意这里不能把延迟写进 `_get_sign_info` 或 `_do_sign`：
        - 查询后短延迟只应发生在“确认未签到后”
        - 角色间长延迟必须覆盖异常分支，因此应放在 finally
        """
        config = CHECKIN_GAME_CONFIGS.get(role.game_biz)
        if not config:
            return CheckinResult(
                account_id=account.id,
                game_role_id=role.id,
                status="failed",
                message=f"不支持的签到游戏类型: {role.game_biz}",
                **self._build_result_context(account, role),
            )

        called_api = False
        try:
            called_api = True
            info = await self._get_sign_info(client, cookie, config, role, device_state)

            if info.get("is_sign"):
                return CheckinResult(
                    account_id=account.id,
                    game_role_id=role.id,
                    status="already_signed",
                    message="今日已签到",
                    total_sign_days=info.get("total_sign_day"),
                    **self._build_result_context(account, role),
                )

            # 查询成功且确认“未签到”后再等待短延迟，避免把无意义等待扩散到失败分支。
            await self._sleep_between_info_and_sign()
            return await self._do_sign(client, cookie, config, account, role, device_state)

        except CheckinApiError as exc:
            logger.warning("角色 %s 签到阶段失败: %s", role.game_uid, exc)
            return CheckinResult(
                account_id=account.id,
                game_role_id=role.id,
                status="failed",
                message=str(exc),
                **self._build_result_context(account, role),
            )
        except Exception as exc:
            logger.error("角色 %s 签到异常: %s", role.game_uid, exc)
            return CheckinResult(
                account_id=account.id,
                game_role_id=role.id,
                status="failed",
                message=f"签到异常: {exc}",
                **self._build_result_context(account, role),
            )
        finally:
            # 与 Starward 的处理一致：只要本角色已经调用过签到 API，就统一等待后再处理下一个角色。
            # 这样即使本次请求报错，也不会因为“异常分支没有延迟”而形成高频连续请求。
            if called_api:
                await self._sleep_between_roles()

    async def _get_sign_info(
        self,
        client: httpx.AsyncClient,
        cookie: str,
        config: CheckinGameConfig,
        role: GameRole,
        device_state: tuple[str, str],
    ) -> dict[str, Any]:
        device_id, device_fp = device_state
        headers = self._build_checkin_headers(
            cookie,
            device_id=device_id,
            device_fp=device_fp,
            config=config,
        )
        response = await client.get(
            config.info_url,
            params={"act_id": config.act_id, "region": role.region, "uid": role.game_uid},
            headers=headers,
        )
        data = response.json()
        self._raise_for_api_error("查询签到状态", role.game_biz, data)
        return data.get("data", {})

    async def _do_sign(
        self,
        client: httpx.AsyncClient,
        cookie: str,
        config: CheckinGameConfig,
        account: MihoyoAccount,
        role: GameRole,
        device_state: tuple[str, str],
    ) -> CheckinResult:
        device_id, device_fp = device_state
        payload = {
            "act_id": config.act_id,
            "region": role.region,
            # Starward 这里明确把 uid 作为字符串发送，避免不同序列化器对数字类型的隐式处理差异。
            "uid": str(role.game_uid),
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        headers = self._build_checkin_headers(
            cookie,
            device_id=device_id,
            device_fp=device_fp,
            config=config,
            content_type="application/json",
        )

        response = await client.post(
            config.sign_url,
            content=body,
            headers=headers,
        )
        data = response.json()
        self._raise_for_api_error("执行签到", role.game_biz, data, ignored_codes={-5003})

        retcode = data.get("retcode", -1)
        if retcode == -5003:
            return CheckinResult(
                account_id=role.account_id,
                game_role_id=role.id,
                status="already_signed",
                message="今日已签到",
                account_nickname=account.nickname or account.mihoyo_uid or f"账号#{account.id}",
                game_biz=role.game_biz,
                game_nickname=role.nickname or role.game_uid,
            )

        sign_data = data.get("data", {}) or {}
        if sign_data.get("is_risk") or sign_data.get("gt"):
            return CheckinResult(
                account_id=role.account_id,
                game_role_id=role.id,
                status="risk",
                message="签到触发风控验证，需要人工处理",
                account_nickname=account.nickname or account.mihoyo_uid or f"账号#{account.id}",
                game_biz=role.game_biz,
                game_nickname=role.nickname or role.game_uid,
            )

        return CheckinResult(
            account_id=role.account_id,
            game_role_id=role.id,
            status="success",
            message="签到成功",
            total_sign_days=sign_data.get("total_sign_day"),
            account_nickname=account.nickname or account.mihoyo_uid or f"账号#{account.id}",
            game_biz=role.game_biz,
            game_nickname=role.nickname or role.game_uid,
        )

    async def _ensure_device_state(self, client: httpx.AsyncClient) -> tuple[str, str]:
        """
        获取稳定可复用的设备标识。

        Starward 会复用 device_id / device_fp，而不是每次都临时生成。
        若这里退化成“请求前随机一个”，日志表面上看只是签到失败，
        实际根因却是设备画像不稳定，后续会非常难排查。
        """
        config = await self.settings_service.get_or_create()

        changed = False
        if not config.hyperion_device_id:
            config.hyperion_device_id = generate_device_id()
            changed = True

        if not config.hyperion_device_fp:
            try:
                config.hyperion_device_fp = await self._refresh_device_fp(client, config.hyperion_device_id)
            except Exception as exc:
                # 设备指纹接口本身并不稳定，且其失败不应该把整个手动签到接口打成 500。
                # 这里退回本地生成的占位 device_fp，至少保证任务能继续执行并把真实签到结果写入日志。
                logger.warning("获取设备指纹失败，退回本地生成的设备指纹继续执行: %s", exc)
                config.hyperion_device_fp = generate_device_fp()
            config.hyperion_device_fp_updated_at = utc_now_naive()
            changed = True

        if changed:
            await self.db.commit()
            await self.db.refresh(config)

        return config.hyperion_device_id, config.hyperion_device_fp

    async def _refresh_device_fp(self, client: httpx.AsyncClient, device_id: str) -> str:
        placeholder_fp = generate_device_fp()
        payload = build_device_fp_payload(device_id, placeholder_fp)
        response = await client.post(
            DEVICE_FP_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "User-Agent": build_hyperion_headers(
                    "",
                    device_id=device_id,
                    device_fp=placeholder_fp,
                    app_version=HYPERION_APP_VERSION,
                )["User-Agent"],
            },
        )
        data = response.json()
        # 线上接口的真实返回是：
        # {"retcode":0,"message":"OK","data":{"device_fp":"xxx","code":403,"msg":"传入的参数有误"}}
        # 也就是说，只要顶层成功且给出了 device_fp，就应该接受该值，不能误把 data.code 当成整体失败。
        device_fp = data.get("device_fp") or (data.get("data") or {}).get("device_fp")
        if data.get("retcode") != 0 or not device_fp:
            raise RuntimeError(f"获取设备指纹失败: {data.get('message') or data}")
        return str(device_fp)

    def _build_checkin_headers(
        self,
        cookie: str,
        *,
        device_id: str,
        device_fp: str,
        config: CheckinGameConfig,
        content_type: str | None = None,
    ) -> dict[str, str]:
        headers = build_hyperion_headers(
            cookie,
            device_id=device_id,
            device_fp=device_fp,
            sign_game=config.sign_game if config.send_sign_game else None,
            ds=generate_cn_dynamic_secret(HYPERION_SIGN_SALT),
            app_version=HYPERION_APP_VERSION,
        )
        headers["Referer"] = config.referer
        headers["Origin"] = config.origin
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _raise_for_api_error(
        self,
        stage: str,
        game_biz: str,
        response_data: dict[str, Any],
        *,
        ignored_codes: set[int] | None = None,
    ) -> None:
        retcode = int(response_data.get("retcode", -1))
        if ignored_codes and retcode in ignored_codes:
            return
        if retcode == 0:
            return

        raise CheckinApiError(
            stage=stage,
            retcode=retcode,
            message=str(response_data.get("message") or "未知错误"),
            game_biz=game_biz,
        )

    async def _sleep_between_info_and_sign(self) -> None:
        delay_ms = random.randrange(1000, 3000)
        logger.info("查询签到状态后等待 %.3f 秒再执行签到，降低连续请求风控概率", delay_ms / 1000)
        await asyncio.sleep(delay_ms / 1000)

    async def _sleep_between_roles(self) -> None:
        delay_ms = random.randrange(3000, 6000)
        logger.info("角色签到结束后等待 %.3f 秒再处理下一个角色，避免高频串行触发风控", delay_ms / 1000)
        await asyncio.sleep(delay_ms / 1000)

    async def fetch_game_roles(self, cookie: str) -> list[dict[str, Any]]:
        """
        通过 Cookie 获取该账号绑定的所有游戏角色。

        这里仍沿用现有通用接口，不强行复用签到风控延迟逻辑，
        以免把“签到节流”误扩散到账号导入链路。
        """
        device_id = generate_device_id()
        headers = build_hyperion_headers(
            cookie,
            device_id=device_id,
            device_fp=generate_device_fp(),
            ds=generate_ds(),
            app_version=HYPERION_APP_VERSION,
        )

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(GAME_ROLES_URL, headers=headers)
            data = response.json()
            if data.get("retcode") == 0:
                return data.get("data", {}).get("list", [])

            logger.warning("获取游戏角色失败: %s", data)
            return []
