import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "mysql+asyncmy://demo:demo@127.0.0.1:3306/miyoushe?charset=utf8mb4"

from app.api import accounts as accounts_api
from app.models.user import User
from app.services.passport_login import PassportLoginService


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if not self._responses:
            raise AssertionError("测试桩未提供足够的响应")
        return _FakeResponse(self._responses.pop(0))


class PassportLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_qr_login_returns_ticket_and_url(self):
        fake_client = _FakeAsyncClient([
            {
                "retcode": 0,
                "message": "OK",
                "data": {
                    "ticket": "ticket-1",
                    "url": "https://user.mihoyo.com/qr?ticket=ticket-1",
                },
            }
        ])
        service = PassportLoginService()

        with patch("app.services.passport_login.httpx.AsyncClient", new=lambda *args, **kwargs: fake_client):
            result = await service.create_qr_login()

        self.assertEqual(result["ticket"], "ticket-1")
        self.assertEqual(result["url"], "https://user.mihoyo.com/qr?ticket=ticket-1")
        self.assertEqual(
            fake_client.calls[0]["url"],
            "https://passport-api.mihoyo.com/account/ma-cn-passport/app/createQRLogin",
        )
        self.assertEqual(fake_client.calls[0]["json"], {})

    async def test_query_qr_login_status_returns_root_credentials_when_confirmed(self):
        fake_client = _FakeAsyncClient([
            {
                "retcode": 0,
                "message": "OK",
                "data": {
                    "status": "Confirmed",
                    "tokens": [
                        {"token_type": 2, "token": "ignore-me"},
                        {"token_type": 1, "token": "v2_test_stoken"},
                    ],
                    "user_info": {
                        "aid": "10001",
                        "mid": "mid-10001",
                    },
                    "login_ticket": "ticket-1",
                },
            }
        ])
        service = PassportLoginService()

        with patch("app.services.passport_login.httpx.AsyncClient", new=lambda *args, **kwargs: fake_client):
            result = await service.query_qr_login_status("ticket-1")

        self.assertEqual(result["status"], "Confirmed")
        self.assertEqual(result["stoken"], "v2_test_stoken")
        self.assertEqual(result["stuid"], "10001")
        self.assertEqual(result["mid"], "mid-10001")
        self.assertEqual(result["login_ticket"], "ticket-1")
        self.assertEqual(result["credential_source"], "passport_qr")
        self.assertEqual(
            fake_client.calls[0]["url"],
            "https://passport-api.mihoyo.com/account/ma-cn-passport/app/queryQRLoginStatus",
        )
        self.assertEqual(fake_client.calls[0]["json"], {"ticket": "ticket-1"})

    async def test_create_login_captcha_returns_message_and_action_type(self):
        fake_client = _FakeAsyncClient([
            {
                "retcode": 0,
                "message": "OK",
                "data": {
                    "action_type": "login",
                },
            }
        ])
        service = PassportLoginService()

        with patch("app.services.passport_login.httpx.AsyncClient", new=lambda *args, **kwargs: fake_client):
            result = await service.create_login_captcha("13800000000")

        self.assertEqual(result["message"], "验证码已发送")
        self.assertEqual(result["action_type"], "login")
        self.assertIsNone(result["aigis"])
        self.assertEqual(
            fake_client.calls[0]["url"],
            "https://passport-api.mihoyo.com/account/ma-cn-verifier/verifier/createLoginCaptcha",
        )
        self.assertNotEqual(fake_client.calls[0]["json"]["area_code"], "+86")
        self.assertNotEqual(fake_client.calls[0]["json"]["mobile"], "13800000000")

    async def test_login_by_mobile_captcha_returns_root_tokens(self):
        fake_client = _FakeAsyncClient([
            {
                "retcode": 0,
                "message": "OK",
                "data": {
                    "tokens": [
                        {"token_type": 1, "token": "v2_sms_stoken"},
                    ],
                    "user_info": {
                        "aid": "10002",
                        "mid": "mid-10002",
                    },
                    "login_ticket": "ticket-2",
                },
            }
        ])
        service = PassportLoginService()

        with patch("app.services.passport_login.httpx.AsyncClient", new=lambda *args, **kwargs: fake_client):
            result = await service.login_by_mobile_captcha(
                mobile="13800000000",
                captcha="246810",
                action_type="login",
                aigis="risk-ticket",
            )

        self.assertEqual(result["stoken"], "v2_sms_stoken")
        self.assertEqual(result["stuid"], "10002")
        self.assertEqual(result["mid"], "mid-10002")
        self.assertEqual(result["login_ticket"], "ticket-2")
        self.assertEqual(result["credential_source"], "passport_sms")
        self.assertEqual(
            fake_client.calls[0]["url"],
            "https://passport-api.mihoyo.com/account/ma-cn-passport/app/loginByMobileCaptcha",
        )
        self.assertEqual(fake_client.calls[0]["json"]["action_type"], "login")
        self.assertEqual(fake_client.calls[0]["json"]["captcha"], "246810")
        self.assertNotEqual(fake_client.calls[0]["json"]["area_code"], "+86")
        self.assertNotEqual(fake_client.calls[0]["json"]["mobile"], "13800000000")
        self.assertEqual(fake_client.calls[0]["headers"]["x-rpc-aigis"], "risk-ticket")

    async def test_qr_and_sms_login_share_same_parse_function(self):
        fake_client = _FakeAsyncClient([
            {
                "retcode": 0,
                "message": "OK",
                "data": {
                    "status": "Confirmed",
                    "tokens": [
                        {"token_type": 1, "token": "v2_qr_stoken"},
                    ],
                    "user_info": {
                        "aid": "10001",
                        "mid": "mid-10001",
                    },
                    "login_ticket": "ticket-1",
                },
            },
            {
                "retcode": 0,
                "message": "OK",
                "data": {
                    "tokens": [
                        {"token_type": 1, "token": "v2_sms_stoken"},
                    ],
                    "user_info": {
                        "aid": "10002",
                        "mid": "mid-10002",
                    },
                    "login_ticket": "ticket-2",
                },
            },
        ])
        service = PassportLoginService()

        with (
            patch("app.services.passport_login.httpx.AsyncClient", new=lambda *args, **kwargs: fake_client),
            patch.object(
                PassportLoginService,
                "parse_login_result",
                side_effect=PassportLoginService.parse_login_result,
            ) as mock_parse,
        ):
            qr_result = await service.query_qr_login_status("ticket-1")
            sms_result = await service.login_by_mobile_captcha(
                mobile="13800000000",
                captcha="246810",
                action_type="login",
            )

        self.assertEqual(qr_result["credential_source"], "passport_qr")
        self.assertEqual(sms_result["credential_source"], "passport_sms")
        self.assertEqual(mock_parse.call_count, 2)
        self.assertEqual(mock_parse.call_args_list[0].kwargs["credential_source"], "passport_qr")
        self.assertEqual(mock_parse.call_args_list[1].kwargs["credential_source"], "passport_sms")

    async def test_create_sms_login_captcha_endpoint_returns_service_payload(self):
        fake_service = AsyncMock()
        fake_service.create_login_captcha.return_value = {
            "message": "验证码已发送",
            "action_type": "login",
            "aigis": "risk-ticket",
        }
        current_user = User(username="tester", password_hash="x", role="user", is_active=True)

        with patch("app.api.accounts.PassportLoginService", return_value=fake_service):
            response = await accounts_api.create_sms_login_captcha(
                accounts_api.SmsLoginCaptchaRequest(mobile="13800000000", aigis="risk-ticket"),
                current_user=current_user,
            )

        self.assertEqual(response["message"], "验证码已发送")
        self.assertEqual(response["action_type"], "login")
        self.assertEqual(response["aigis"], "risk-ticket")
        fake_service.create_login_captcha.assert_awaited_once_with("13800000000", aigis="risk-ticket")

    async def test_verify_sms_login_endpoint_returns_root_credentials(self):
        fake_service = AsyncMock()
        fake_service.login_by_mobile_captcha.return_value = {
            "stoken": "v2_sms_stoken",
            "stuid": "10002",
            "mid": "mid-10002",
            "login_ticket": "ticket-2",
            "credential_source": "passport_sms",
        }
        current_user = User(username="tester", password_hash="x", role="user", is_active=True)

        with patch("app.api.accounts.PassportLoginService", return_value=fake_service):
            response = await accounts_api.verify_sms_login(
                accounts_api.SmsLoginVerifyRequest(
                    mobile="13800000000",
                    captcha="246810",
                    action_type="login",
                    aigis="risk-ticket",
                ),
                current_user=current_user,
            )

        self.assertEqual(response["stoken"], "v2_sms_stoken")
        self.assertEqual(response["credential_source"], "passport_sms")
        fake_service.login_by_mobile_captcha.assert_awaited_once_with(
            mobile="13800000000",
            captcha="246810",
            action_type="login",
            aigis="risk-ticket",
        )


if __name__ == "__main__":
    unittest.main()
