"""
米游社官方 Passport / HoyoPlay 二维码登录服务。

当前文件只承载 Task 2 所需的最小能力：
1. 创建官方二维码
2. 轮询扫码确认状态
3. 在确认后解析高权限根凭据字段

这里明确不回退到 Playwright 网页 Cookie 抽取链路。
原因不是“旧链路代码不能跑”，而是两条链路拿到的是不同层级的凭据：
- Passport 二维码返回的是后续可继续补齐/续期的根凭据
- 网页 Cookie 只是某一时刻的工作态

如果在这里偷偷用网页 Cookie 兜底，后续维护者会再次把“高权限登录”和“网页登录态”
混成一件事，最终让账号页、抽卡导入和自愈逻辑都建立在错误前提上。
"""

import base64
import io
import logging
import random
import string
from typing import Any, Optional

import httpx
import qrcode
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger(__name__)

CREATE_QR_LOGIN_URL = "https://passport-api.mihoyo.com/account/ma-cn-passport/app/createQRLogin"
QUERY_QR_LOGIN_STATUS_URL = "https://passport-api.mihoyo.com/account/ma-cn-passport/app/queryQRLoginStatus"
CREATE_LOGIN_CAPTCHA_URL = "https://passport-api.mihoyo.com/account/ma-cn-verifier/verifier/createLoginCaptcha"
LOGIN_BY_MOBILE_CAPTCHA_URL = "https://passport-api.mihoyo.com/account/ma-cn-passport/app/loginByMobileCaptcha"
HOYOPLAY_USER_AGENT = "HYPContainer/1.1.4.133"
HOYOPLAY_APP_ID = "ddxf5dufpuyo"
STOKEN_TOKEN_TYPE = 1
QR_LOGIN_EXPIRED_RETCODES = {-3501, -106}
PASSPORT_RSA_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDDvekdPMHN3AYhm/vktJT+YJr7
cI5DcsNKqdsx5DZX0gDuWFuIjzdwButrIYPNmRJ1G8ybDIF7oDW2eEpm5sMbL9zs
9ExXCdvqrn51qELbqj0XxtMTIpaCHFSI50PfPpTFV9Xt/hmyVwokoOXFlAEgCn+Q
CgGs52bFoYMtyi+xEQIDAQAB
-----END PUBLIC KEY-----"""


def _generate_hoyoplay_device_id(length: int = 53) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


class PassportLoginService:
    """
    官方 Passport 登录服务。

    这里显式把“接口调用”和“登录结果解析”集中在一个服务里，避免后续在 WebSocket、
    短信登录、凭据持久化等多个入口里各自复制 token 解析逻辑，导致字段语义漂移。
    """

    def __init__(self, *, timeout: float = 15.0):
        self.timeout = timeout
        self.device_id = _generate_hoyoplay_device_id()

    def _build_headers(self, *, aigis: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": HOYOPLAY_USER_AGENT,
            "x-rpc-app_id": HOYOPLAY_APP_ID,
            "x-rpc-client_type": "3",
            "x-rpc-device_id": self.device_id,
        }
        # `x-rpc-aigis` 是米哈游风控挑战透传字段。
        # 这里只按调用方显式提供时原样转发，避免后续维护时把“短信登录必须总是带 aigis”
        # 或“完全不需要处理风控”这两种极端误判写死在底层服务里。
        if aigis:
            headers["x-rpc-aigis"] = aigis
        return headers

    @staticmethod
    def _encrypt_login_value(value: str) -> str:
        """
        对短信登录接口要求的手机号、区号做 RSA 加密。

        这里不能偷懒直接明文发送：测试里会锁定“请求体不是原始手机号”，
        真机联调时若误改成明文，接口通常只会回一个笼统失败码，排障成本很高。
        """
        public_key = serialization.load_pem_public_key(PASSPORT_RSA_PUBLIC_KEY.encode("ascii"))
        encrypted = public_key.encrypt(value.encode("utf-8"), padding.PKCS1v15())
        return base64.b64encode(encrypted).decode("ascii")

    @staticmethod
    def _unwrap_response(payload: dict[str, Any], *, action: str) -> dict[str, Any]:
        retcode = int(payload.get("retcode", -1))
        if retcode == 0:
            data = payload.get("data")
            if isinstance(data, dict):
                return data
            raise RuntimeError(f"{action} 返回缺少 data")

        message = str(payload.get("message") or payload.get("msg") or "未知错误")
        raise RuntimeError(f"{action} 失败（retcode={retcode}）：{message}")

    async def create_qr_login(self) -> dict[str, str]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                CREATE_QR_LOGIN_URL,
                json={},
                headers=self._build_headers(),
            )
            response.raise_for_status()
            data = self._unwrap_response(response.json(), action="创建官方二维码")

        ticket = str(data.get("ticket") or "").strip()
        url = str(data.get("url") or "").strip()
        if not ticket or not url:
            raise RuntimeError("官方二维码响应缺少 ticket 或 url")
        return {"ticket": ticket, "url": url}

    async def query_qr_login_status(self, ticket: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                QUERY_QR_LOGIN_STATUS_URL,
                json={"ticket": ticket},
                headers=self._build_headers(),
            )
            response.raise_for_status()
            payload = response.json()

        retcode = int(payload.get("retcode", -1))
        if retcode in QR_LOGIN_EXPIRED_RETCODES:
            return {
                "status": "Expired",
                "message": str(payload.get("message") or payload.get("msg") or "二维码已过期"),
            }

        data = self._unwrap_response(payload, action="查询二维码状态")
        status = str(data.get("status") or "").strip()
        if status == "Confirmed":
            result = self.parse_login_result(data, credential_source="passport_qr")
            result["status"] = status
            return result
        return {"status": status}

    @staticmethod
    def parse_login_result(payload: dict[str, Any], *, credential_source: str) -> dict[str, Any]:
        """
        解析官方登录成功后的最小根凭据结果。

        二维码和短信验证码必须共用这里的解析逻辑，原因不是“代码复用更好看”，
        而是两条链路最终都要落成同一份根凭据语义。若后续维护者在两个入口各改一份，
        很容易出现某一条链路漏掉 `login_ticket`、改错 `token_type` 或写出不同字段名，
        进而把后续凭据持久化、自愈、抽卡链路拖进隐性兼容泥潭。

        当前主链路仍只认 `token_type == 1` 为 `SToken`。不要擅自放宽成
        “任意 token 都算成功”，否则会把非根凭据 token 当成正式登录结果。
        """
        tokens = payload.get("tokens")
        if not isinstance(tokens, list):
            raise RuntimeError("官方登录结果缺少 tokens")

        stoken: Optional[str] = None
        for item in tokens:
            if not isinstance(item, dict):
                continue
            if int(item.get("token_type", -1)) == STOKEN_TOKEN_TYPE:
                stoken = str(item.get("token") or "").strip()
                break

        user_info = payload.get("user_info")
        if not isinstance(user_info, dict):
            raise RuntimeError("官方登录结果缺少 user_info")

        stuid = str(user_info.get("aid") or "").strip()
        mid = str(user_info.get("mid") or "").strip()
        if not stoken or not stuid or not mid:
            raise RuntimeError("官方登录结果缺少 stoken/stuid/mid")

        return {
            "stoken": stoken,
            "stuid": stuid,
            "mid": mid,
            "login_ticket": payload.get("login_ticket"),
            "credential_source": credential_source,
        }

    @staticmethod
    def parse_qr_login_result(payload: dict[str, Any]) -> dict[str, Any]:
        # 兼容 Task 2 已存在的方法名，统一转到新的公共解析函数。
        # 若后续直接删除这个别名，历史调用点会悄悄分叉出第二份解析逻辑。
        return PassportLoginService.parse_login_result(payload, credential_source="passport_qr")

    async def create_login_captcha(self, mobile: str, aigis: str | None = None) -> dict[str, Any]:
        payload = {
            "area_code": self._encrypt_login_value("+86"),
            "mobile": self._encrypt_login_value(mobile),
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                CREATE_LOGIN_CAPTCHA_URL,
                json=payload,
                headers=self._build_headers(aigis=aigis),
            )
            response.raise_for_status()
            data = self._unwrap_response(response.json(), action="发送登录验证码")

        response_headers = getattr(response, "headers", None)
        response_aigis = None
        if response_headers:
            response_aigis = response_headers.get("x-rpc-aigis") or response_headers.get("X-Rpc-Aigis")

        return {
            "message": "验证码已发送",
            "action_type": str(data.get("action_type") or "login").strip() or "login",
            "aigis": response_aigis,
        }

    async def login_by_mobile_captcha(
        self,
        *,
        mobile: str,
        captcha: str,
        action_type: str,
        aigis: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "area_code": self._encrypt_login_value("+86"),
            "action_type": action_type,
            "captcha": captcha,
            "mobile": self._encrypt_login_value(mobile),
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                LOGIN_BY_MOBILE_CAPTCHA_URL,
                json=payload,
                headers=self._build_headers(aigis=aigis),
            )
            response.raise_for_status()
            data = self._unwrap_response(response.json(), action="提交短信验证码登录")

        return self.parse_login_result(data, credential_source="passport_sms")

    @staticmethod
    def build_qr_png_base64(url: str) -> str:
        """
        把官方返回的二维码 URL 转成前端现有可直接展示的 base64 PNG。

        旧前端已经稳定消费“base64 PNG 图片”协议；当前任务不改前端，所以这里在后端做格式适配。
        若后续有人直接把 URL 原样发给旧前端，页面会表现为“连接成功但永远没有二维码图片”，
        排障时非常容易误判成 WebSocket 问题。
        """
        qr = qrcode.QRCode(border=2, box_size=8)
        qr.add_data(url)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")


class PassportQrLoginSession:
    """单次官方 Passport 二维码登录会话。"""

    def __init__(
        self,
        session_id: str,
        user_id: int,
        *,
        login_service: PassportLoginService | None = None,
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.login_service = login_service or PassportLoginService()
        self.status = "pending"
        self.ticket: Optional[str] = None
        self.qr_url: Optional[str] = None
        self.login_result: Optional[dict[str, Any]] = None
        self.error_message: Optional[str] = None

    async def start(self):
        try:
            qr_login = await self.login_service.create_qr_login()
            self.ticket = qr_login["ticket"]
            self.qr_url = qr_login["url"]
            self.status = "pending"
        except Exception as exc:
            self.status = "failed"
            self.error_message = f"创建官方二维码失败: {exc}"
            logger.warning("[%s] %s", self.session_id, self.error_message)
            raise

    async def get_qr_image(self) -> Optional[str]:
        if not self.qr_url:
            self.status = "failed"
            self.error_message = "二维码会话尚未初始化"
            return None

        try:
            image = PassportLoginService.build_qr_png_base64(self.qr_url)
            self.status = "qr_ready"
            return image
        except Exception as exc:
            self.status = "failed"
            self.error_message = f"生成二维码图片失败: {exc}"
            logger.warning("[%s] %s", self.session_id, self.error_message)
            return None

    async def poll_login_status(self) -> str:
        if self.status in ("success", "failed", "timeout"):
            return self.status

        if not self.ticket:
            self.status = "failed"
            self.error_message = "二维码票据缺失，无法轮询"
            return self.status

        try:
            result = await self.login_service.query_qr_login_status(self.ticket)
        except Exception as exc:
            self.status = "failed"
            self.error_message = f"查询二维码状态失败: {exc}"
            logger.warning("[%s] %s", self.session_id, self.error_message)
            return self.status

        status = str(result.get("status") or "").strip()
        if status == "Confirmed":
            self.login_result = result
            self.status = "success"
            return self.status
        if status == "Scanned":
            self.status = "scanned"
            return self.status
        if status == "Expired":
            self.status = "timeout"
            self.error_message = str(result.get("message") or "官方二维码已过期，请重新扫码")
            return self.status

        self.status = "pending"
        return self.status

    def get_login_result(self) -> Optional[dict[str, Any]]:
        return self.login_result

    async def close(self):
        # 官方 Passport 链路当前只走 HTTP 请求，不持有浏览器资源。
        # 保留统一关闭入口，是为了让 main.py 可以无差别管理旧/新登录会话生命周期，
        # 后续若在这里加入额外轮询资源，也不会再回头改 WebSocket finally 结构。
        return None


class PassportQrLoginManager:
    """管理活跃的官方 Passport 二维码登录会话。"""

    def __init__(self):
        self._sessions: dict[str, PassportQrLoginSession] = {}

    def create_session(self, session_id: str, user_id: int) -> PassportQrLoginSession:
        session = PassportQrLoginSession(session_id, user_id)
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[PassportQrLoginSession]:
        return self._sessions.get(session_id)

    async def remove_session(self, session_id: str):
        session = self._sessions.pop(session_id, None)
        if session:
            await session.close()


passport_login_manager = PassportQrLoginManager()
