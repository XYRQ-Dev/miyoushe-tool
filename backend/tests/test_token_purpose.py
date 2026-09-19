"""令牌用途隔离回归，使用模拟数据库，不启动应用生命周期"""

import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from app.api import auth
from app.config import settings
from app.database import get_db


class TokenPurposeTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(
            id=11, username="token-user", role="user", is_active=True,
            password_hash="unused",
        )
        self.result = MagicMock()
        self.result.scalar_one_or_none.return_value = self.user
        self.db = SimpleNamespace(execute=AsyncMock(return_value=self.result))
        app = FastAPI()
        app.include_router(auth.router)

        async def fake_db():
            yield self.db

        app.dependency_overrides[get_db] = fake_db

        @app.get("/protected")
        async def protected(user=Depends(auth.get_current_user)):
            return {"id": user.id}

        @app.get("/admin")
        async def admin(user=Depends(auth.require_admin)):
            return {"id": user.id}

        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def token(self, claims, *, expired=False):
        return auth.create_token(claims, timedelta(minutes=-1 if expired else 5))

    def request(self, path, token):
        method = "POST" if path == "/api/auth/refresh" else "GET"
        return self.client.request(method, path, headers={"Authorization": f"Bearer {token}"})

    def assert_pair(self, data):
        for field, kind in (("access_token", "access"), ("refresh_token", "refresh")):
            payload = jwt.decode(data[field], settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
            self.assertEqual(payload["type"], kind)
            self.assertEqual(payload["user_id"], self.user.id)
            self.assertIn("exp", payload)
        self.assertEqual(self.request("/protected", data["access_token"]).status_code, 200)

    def test_login_and_refresh_issue_typed_pairs(self):
        with patch.object(auth.pwd_context, "verify", return_value=True):
            response = self.client.post("/api/auth/login", json={"username": "token-user", "password": "test-password"})
        self.assertEqual(response.status_code, 200)
        self.assert_pair(response.json())
        refreshed = self.request("/api/auth/refresh", response.json()["refresh_token"])
        self.assertEqual(refreshed.status_code, 200)
        self.assert_pair(refreshed.json())

    def test_tokens_cannot_cross_purposes(self):
        for path, kind in (("/protected", "refresh"), ("/admin", "refresh"), ("/api/auth/refresh", "access")):
            with self.subTest(path=path):
                response = self.request(path, self.token({"user_id": 11, "type": kind}))
                self.assertEqual(response.status_code, 401)
        self.db.execute.assert_not_awaited()

    def test_missing_unknown_expired_and_malformed_claims_are_rejected(self):
        for path, kind in (("/protected", "access"), ("/api/auth/refresh", "refresh")):
            invalid = [
                self.token({"user_id": 11}),
                self.token({"user_id": 11, "type": "unknown"}),
                self.token({"user_id": 11, "type": kind}, expired=True),
                self.token({"type": kind}),
                jwt.encode({"user_id": 11, "type": kind}, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM),
                "invalid-token",
            ]
            invalid.extend(self.token({"user_id": value, "type": kind}) for value in (None, True, 0, -1, "11", 1.5, [], {}))
            for index, token in enumerate(invalid):
                with self.subTest(path=path, case=index):
                    self.assertEqual(self.request(path, token).status_code, 401)
        self.db.execute.assert_not_awaited()

    def test_missing_or_disabled_users_are_rejected(self):
        self.user.is_active = False
        for user in (self.user, None):
            self.result.scalar_one_or_none.return_value = user
            for path, kind in (("/protected", "access"), ("/api/auth/refresh", "refresh")):
                with self.subTest(path=path, missing=user is None):
                    self.assertEqual(self.request(path, self.token({"user_id": 11, "type": kind})).status_code, 401)

    def test_admin_permission_uses_current_database_role(self):
        token = self.token({"user_id": 11, "type": "access", "role": "admin"})
        self.assertEqual(self.request("/admin", token).status_code, 403)
        self.user.role = "admin"
        token = self.token({"user_id": 11, "type": "access", "role": "user"})
        self.assertEqual(self.request("/admin", token).status_code, 200)


if __name__ == "__main__":
    unittest.main()
