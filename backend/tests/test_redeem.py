import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "mysql+asyncmy://demo:demo@127.0.0.1:3306/miyoushe?charset=utf8mb4"

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import GameRole, MihoyoAccount
from app.models.user import User
from app.schemas.redeem import RedeemExecuteRequest
from app.utils.crypto import encrypt_cookie
from tests.mysql_test_case import MySqlIsolatedAsyncioTestCase


class FakeRedeemResponse:
    def __init__(self, payload=None, *, http_error: Exception | None = None, json_error: Exception | None = None):
        self._payload = payload or {}
        self._http_error = http_error
        self._json_error = json_error

    def raise_for_status(self):
        if self._http_error:
            raise self._http_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


class FakeRedeemAsyncClient:
    def __init__(self, response: FakeRedeemResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, *args, **kwargs):
        return self._response


class RedeemTests(MySqlIsolatedAsyncioTestCase):

    async def _create_user(self, session: AsyncSession, username: str) -> User:
        user = User(username=username, password_hash="x", role="user", is_active=True)
        session.add(user)
        await session.flush()
        await session.refresh(user)
        return user

    async def _create_account(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        nickname: str,
        mihoyo_uid: str,
        game_roles: list[tuple[str, str]],
        with_cookie: bool = True,
    ) -> MihoyoAccount:
        account = MihoyoAccount(
            user_id=user_id,
            nickname=nickname,
            mihoyo_uid=mihoyo_uid,
            cookie_status="valid" if with_cookie else "expired",
            cookie_encrypted=encrypt_cookie("ltuid=10001; cookie_token=test-token") if with_cookie else None,
        )
        session.add(account)
        await session.flush()

        for game_biz, game_uid in game_roles:
            session.add(
                GameRole(
                    account_id=account.id,
                    game_biz=game_biz,
                    game_uid=game_uid,
                    nickname=f"{nickname}-角色",
                    region="cn_gf01" if game_biz.startswith("hk4e_") else "prod_gf_cn",
                )
            )

        await session.flush()
        await session.refresh(account)
        return account

    async def test_get_redeem_accounts_only_returns_supported_accounts(self):
        from app.api.redeem import get_redeem_accounts

        async with await self._new_session() as session:
            user = await self._create_user(session, "redeem-account-user")
            await self._create_account(
                session,
                user_id=user.id,
                nickname="双游账号",
                mihoyo_uid="10001",
                game_roles=[("hk4e_cn", "10001"), ("hkrpg_cn", "20001")],
            )
            await self._create_account(
                session,
                user_id=user.id,
                nickname="未适配账号",
                mihoyo_uid="10002",
                game_roles=[("nap_cn", "30001")],
            )
            await session.commit()
            await session.refresh(user)

            response = await get_redeem_accounts(current_user=user, db=session)

        self.assertEqual(response.total, 1)
        self.assertEqual(response.accounts[0].nickname, "双游账号")
        self.assertEqual(response.accounts[0].supported_games, ["genshin", "starrail"])

    async def test_execute_redeem_batch_maps_upstream_statuses_and_persists_history(self):
        from app.api.redeem import execute_redeem_batch, get_redeem_batch_detail, list_redeem_batches
        from app.models.redeem import RedeemBatch, RedeemExecution

        async with await self._new_session() as session:
            user = await self._create_user(session, "redeem-execute-user")
            success_account = await self._create_account(
                session,
                user_id=user.id,
                nickname="成功账号",
                mihoyo_uid="20001",
                game_roles=[("hk4e_cn", "80001")],
            )
            duplicated_account = await self._create_account(
                session,
                user_id=user.id,
                nickname="重复账号",
                mihoyo_uid="20002",
                game_roles=[("hk4e_cn", "80002")],
            )
            invalid_account = await self._create_account(
                session,
                user_id=user.id,
                nickname="无效账号",
                mihoyo_uid="20003",
                game_roles=[("hk4e_cn", "80003")],
            )
            await session.commit()
            await session.refresh(user)

            upstream_mock = AsyncMock(side_effect=[
                {"retcode": 0, "message": "OK"},
                {"retcode": -5008, "message": "兑换码已使用"},
                {"retcode": -2003, "message": "兑换码无效"},
            ])

            with patch("app.services.redeem.RedeemService._execute_upstream_redeem", upstream_mock):
                response = await execute_redeem_batch(
                    RedeemExecuteRequest(
                        game="genshin",
                        code="  springgift2026  ",
                        account_ids=[success_account.id, duplicated_account.id, invalid_account.id],
                    ),
                    current_user=user,
                    db=session,
                )

            self.assertEqual(response.code, "SPRINGGIFT2026")
            self.assertEqual(response.total_accounts, 3)
            self.assertEqual(response.success_count, 1)
            self.assertEqual(response.already_redeemed_count, 1)
            self.assertEqual(response.invalid_code_count, 1)
            self.assertEqual(response.failed_count, 1)
            self.assertEqual(response.error_count, 0)
            self.assertEqual({item.status for item in response.executions}, {"success", "already_redeemed", "invalid_code"})

            batch_total = (await session.execute(select(func.count(RedeemBatch.id)))).scalar_one()
            execution_total = (await session.execute(select(func.count(RedeemExecution.id)))).scalar_one()
            self.assertEqual(batch_total, 1)
            self.assertEqual(execution_total, 3)

            batches = await list_redeem_batches(current_user=user, db=session)
            self.assertEqual(batches.total, 1)
            self.assertEqual(batches.items[0].success_count, 1)
            self.assertEqual(batches.items[0].already_redeemed_count, 1)

            detail = await get_redeem_batch_detail(batch_id=response.batch_id, current_user=user, db=session)
            self.assertEqual(detail.batch_id, response.batch_id)
            self.assertEqual(len(detail.executions), 3)
            self.assertEqual(
                {item.account_id for item in detail.executions},
                {success_account.id, duplicated_account.id, invalid_account.id},
            )

        self.assertEqual(upstream_mock.await_count, 3)

    async def test_execute_redeem_batch_marks_invalid_cookie_without_upstream_request(self):
        from app.api.redeem import execute_redeem_batch

        async with await self._new_session() as session:
            user = await self._create_user(session, "redeem-invalid-cookie-user")
            account = await self._create_account(
                session,
                user_id=user.id,
                nickname="失效账号",
                mihoyo_uid="30001",
                game_roles=[("hk4e_cn", "81001")],
                with_cookie=False,
            )
            await session.commit()
            await session.refresh(user)

            upstream_mock = AsyncMock()
            with patch("app.services.redeem.RedeemService._execute_upstream_redeem", upstream_mock):
                response = await execute_redeem_batch(
                    RedeemExecuteRequest(
                        game="genshin",
                        code="HELLO2026",
                        account_ids=[account.id],
                    ),
                    current_user=user,
                    db=session,
                )

        self.assertEqual(response.total_accounts, 1)
        self.assertEqual(response.invalid_cookie_count, 1)
        self.assertEqual(response.failed_count, 1)
        self.assertEqual(response.error_count, 0)
        self.assertEqual(response.executions[0].status, "invalid_cookie")
        self.assertEqual(upstream_mock.await_count, 0)

    async def test_execute_redeem_batch_does_not_flush_batch_before_upstream_requests(self):
        from app.api.redeem import execute_redeem_batch

        async with await self._new_session() as session:
            user = await self._create_user(session, "redeem-order-user")
            account = await self._create_account(
                session,
                user_id=user.id,
                nickname="顺序账号",
                mihoyo_uid="50001",
                game_roles=[("hk4e_cn", "83001")],
            )
            await session.commit()
            await session.refresh(user)

            events: list[str] = []
            original_flush = session.flush

            async def flush_wrapper(*args, **kwargs):
                events.append("flush")
                return await original_flush(*args, **kwargs)

            async def upstream_stub(*args, **kwargs):
                events.append("upstream")
                return {"retcode": 0, "message": "OK"}

            with patch.object(session, "flush", new=flush_wrapper):
                with patch("app.services.redeem.RedeemService._execute_upstream_redeem", new=upstream_stub):
                    await execute_redeem_batch(
                        RedeemExecuteRequest(
                            game="genshin",
                            code="ORDER2026",
                            account_ids=[account.id],
                        ),
                        current_user=user,
                        db=session,
                    )

        self.assertGreaterEqual(events.count("upstream"), 1)
        self.assertIn("flush", events)
        self.assertLess(events.index("upstream"), events.index("flush"))

    async def test_execute_redeem_batch_maps_network_errors_to_sanitized_error_summary(self):
        from app.api.redeem import execute_redeem_batch

        async with await self._new_session() as session:
            user = await self._create_user(session, "redeem-network-user")
            account = await self._create_account(
                session,
                user_id=user.id,
                nickname="网络账号",
                mihoyo_uid="50002",
                game_roles=[("hk4e_cn", "83002")],
            )
            await session.commit()
            await session.refresh(user)

            async def upstream_stub(*args, **kwargs):
                raise RuntimeError("token=secret upstream boom")

            with patch("app.services.redeem.RedeemService._execute_upstream_redeem", new=upstream_stub):
                response = await execute_redeem_batch(
                    RedeemExecuteRequest(
                        game="genshin",
                        code="SAFE2026",
                        account_ids=[account.id],
                    ),
                    current_user=user,
                    db=session,
                )

        self.assertEqual(response.error_count, 1)
        self.assertEqual(response.failed_count, 1)
        self.assertEqual(response.executions[0].status, "error")
        self.assertNotIn("token=secret", response.executions[0].message or "")
        self.assertEqual(response.executions[0].message, "兑换执行异常，请稍后重试")

    async def test_execute_redeem_batch_maps_upstream_http_failure_to_network_error(self):
        from app.api.redeem import execute_redeem_batch

        async with await self._new_session() as session:
            user = await self._create_user(session, "redeem-http-user")
            account = await self._create_account(
                session,
                user_id=user.id,
                nickname="HTTP账号",
                mihoyo_uid="50003",
                game_roles=[("hk4e_cn", "83003")],
            )
            await session.commit()
            await session.refresh(user)

            request = httpx.Request("GET", "https://example.com/redeem")
            response = httpx.Response(502, request=request)
            client = FakeRedeemAsyncClient(
                FakeRedeemResponse(http_error=httpx.HTTPStatusError("bad gateway", request=request, response=response))
            )

            with patch("app.services.redeem.httpx.AsyncClient", return_value=client):
                result = await execute_redeem_batch(
                    RedeemExecuteRequest(
                        game="genshin",
                        code="HTTP2026",
                        account_ids=[account.id],
                    ),
                    current_user=user,
                    db=session,
                )

        self.assertEqual(result.failed_count, 1)
        self.assertEqual(result.error_count, 1)
        self.assertEqual(result.executions[0].status, "network_error")
        self.assertEqual(result.executions[0].message, "兑换请求失败，请稍后重试")

    async def test_execute_redeem_batch_maps_invalid_json_response_to_network_error(self):
        from app.api.redeem import execute_redeem_batch

        async with await self._new_session() as session:
            user = await self._create_user(session, "redeem-json-user")
            account = await self._create_account(
                session,
                user_id=user.id,
                nickname="JSON账号",
                mihoyo_uid="50004",
                game_roles=[("hk4e_cn", "83004")],
            )
            await session.commit()
            await session.refresh(user)

            client = FakeRedeemAsyncClient(FakeRedeemResponse(json_error=ValueError("not json")))
            with patch("app.services.redeem.httpx.AsyncClient", return_value=client):
                result = await execute_redeem_batch(
                    RedeemExecuteRequest(
                        game="genshin",
                        code="JSON2026",
                        account_ids=[account.id],
                    ),
                    current_user=user,
                    db=session,
                )

        self.assertEqual(result.failed_count, 1)
        self.assertEqual(result.error_count, 1)
        self.assertEqual(result.executions[0].status, "network_error")
        self.assertEqual(result.executions[0].message, "兑换请求失败，请稍后重试")

    async def test_execute_redeem_batch_rejects_foreign_account(self):
        from app.api.redeem import execute_redeem_batch
        from app.models.redeem import RedeemBatch

        async with await self._new_session() as session:
            user = await self._create_user(session, "redeem-owner-user")
            another_user = await self._create_user(session, "redeem-stranger-user")
            own_account = await self._create_account(
                session,
                user_id=user.id,
                nickname="自己的账号",
                mihoyo_uid="40001",
                game_roles=[("hk4e_cn", "82001")],
            )
            foreign_account = await self._create_account(
                session,
                user_id=another_user.id,
                nickname="别人的账号",
                mihoyo_uid="40002",
                game_roles=[("hk4e_cn", "82002")],
            )
            await session.commit()
            await session.refresh(user)

            with self.assertRaises(HTTPException) as context:
                await execute_redeem_batch(
                    RedeemExecuteRequest(
                        game="genshin",
                        code="OWNERONLY",
                        account_ids=[own_account.id, foreign_account.id],
                    ),
                    current_user=user,
                    db=session,
                )

            batch_total = (await session.execute(select(func.count(RedeemBatch.id)))).scalar_one()

        self.assertEqual(context.exception.status_code, 404)
        self.assertIn("账号不存在", context.exception.detail)
        self.assertEqual(batch_total, 0)

if __name__ == "__main__":
    unittest.main()
