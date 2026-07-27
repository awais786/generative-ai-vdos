import base64
import json
from unittest.mock import patch, MagicMock
from django.test import TestCase


FAKE_COGNITO = {
    "COGNITO_DOMAIN": "https://example.auth.us-east-1.amazoncognito.com",
    "COGNITO_APP_CLIENT_ID": "client-abc",
    "COGNITO_APP_CLIENT_SECRET": "secret-xyz",
    "COGNITO_REDIRECT_URI": "http://localhost:8000/api/auth/callback",
    "COGNITO_LOGOUT_REDIRECT_URI": "http://localhost:3000",
}

FAKE_ID_TOKEN_CLAIMS = {
    "sub": "test-sub-123",
    "email": "test@example.com",
    "name": "Test User",
}


def _make_fake_jwt(claims: dict) -> str:
    def b64url(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return f"{b64url({'alg': 'none'})}.{b64url(claims)}."


FAKE_TOKENS = {
    "id_token": _make_fake_jwt(FAKE_ID_TOKEN_CLAIMS),
    "access_token": "access.jwt.token",
    "refresh_token": "refresh.token",
}


class LoginViewTest(TestCase):
    def test_redirects_to_cognito(self):
        with self.settings(COGNITO=FAKE_COGNITO):
            resp = self.client.get("/api/auth/login")
        self.assertEqual(resp.status_code, 302)
        self.assertIn(FAKE_COGNITO["COGNITO_DOMAIN"], resp["Location"])
        self.assertIn("/oauth2/authorize", resp["Location"])

    def test_state_stored_in_session(self):
        with self.settings(COGNITO=FAKE_COGNITO):
            self.client.get("/api/auth/login")
        self.assertIn("cognito_state", self.client.session)
        self.assertTrue(len(self.client.session["cognito_state"]) > 10)

    def test_redirect_contains_client_id(self):
        with self.settings(COGNITO=FAKE_COGNITO):
            resp = self.client.get("/api/auth/login")
        self.assertIn("client_id=client-abc", resp["Location"])


class CallbackViewTest(TestCase):
    def _set_state(self, state="good-state"):
        session = self.client.session
        session["cognito_state"] = state
        session.save()

    def _mock_exchange(self, return_value=FAKE_TOKENS):
        mock_resp = MagicMock()
        mock_resp.ok = return_value is not None
        if return_value:
            mock_resp.json.return_value = return_value
        return patch("apps.accounts.cognito.requests.post", return_value=mock_resp)

    def test_valid_code_sets_session_and_redirects(self):
        self._set_state("my-state")
        with self.settings(COGNITO=FAKE_COGNITO), self._mock_exchange():
            resp = self.client.get(
                "/api/auth/callback", {"code": "auth-code", "state": "my-state"}
            )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.session.get("id_token"), FAKE_TOKENS["id_token"])
        self.assertEqual(self.client.session.get("access_token"), "access.jwt.token")
        self.assertEqual(self.client.session.get("cognito_sub"), FAKE_ID_TOKEN_CLAIMS["sub"])

    def test_callback_creates_user_profile(self):
        from apps.accounts.models import UserProfile
        self._set_state("my-state")
        with self.settings(COGNITO=FAKE_COGNITO), self._mock_exchange():
            self.client.get(
                "/api/auth/callback", {"code": "auth-code", "state": "my-state"}
            )
        self.assertTrue(
            UserProfile.objects.filter(cognito_sub=FAKE_ID_TOKEN_CLAIMS["sub"]).exists()
        )

    def test_state_mismatch_returns_400(self):
        self._set_state("expected-state")
        resp = self.client.get(
            "/api/auth/callback", {"code": "code", "state": "wrong-state"}
        )
        self.assertEqual(resp.status_code, 400)

    def test_missing_code_returns_400(self):
        self._set_state("my-state")
        resp = self.client.get("/api/auth/callback", {"state": "my-state"})
        self.assertEqual(resp.status_code, 400)

    def test_failed_exchange_returns_401(self):
        self._set_state("my-state")
        with self.settings(COGNITO=FAKE_COGNITO), self._mock_exchange(return_value=None):
            resp = self.client.get(
                "/api/auth/callback", {"code": "bad-code", "state": "my-state"}
            )
        self.assertEqual(resp.status_code, 401)

    def test_state_consumed_after_callback(self):
        self._set_state("my-state")
        with self.settings(COGNITO=FAKE_COGNITO), self._mock_exchange():
            self.client.get(
                "/api/auth/callback", {"code": "code", "state": "my-state"}
            )
        self.assertNotIn("cognito_state", self.client.session)


class DevLoginViewTest(TestCase):
    def test_returns_403_when_debug_false(self):
        with self.settings(DEBUG=False):
            resp = self.client.post("/api/auth/dev-login")
        self.assertEqual(resp.status_code, 403)

    def test_redirects_to_home_when_debug_true(self):
        with self.settings(DEBUG=True):
            resp = self.client.post("/api/auth/dev-login")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/home", resp["Location"])

    def test_sets_cognito_sub_in_session(self):
        with self.settings(DEBUG=True):
            self.client.post("/api/auth/dev-login")
        self.assertEqual(self.client.session.get("cognito_sub"), "dev-local-user")

    def test_creates_user_profile_if_missing(self):
        from apps.accounts.models import UserProfile
        UserProfile.objects.filter(cognito_sub="dev-local-user").delete()
        with self.settings(DEBUG=True):
            self.client.post("/api/auth/dev-login")
        self.assertTrue(UserProfile.objects.filter(cognito_sub="dev-local-user").exists())

    def test_flushes_stale_session_data(self):
        session = self.client.session
        session["cognito_sub"] = "old-user-sub"
        session["id_token"] = "stale.token"
        session.save()
        with self.settings(DEBUG=True):
            self.client.post("/api/auth/dev-login")
        self.assertNotIn("id_token", self.client.session)
        self.assertEqual(self.client.session.get("cognito_sub"), "dev-local-user")


class LogoutViewTest(TestCase):
    def setUp(self):
        session = self.client.session
        session["id_token"] = "some.token"
        session["access_token"] = "some.access"
        session.save()

    def test_logout_clears_session(self):
        with self.settings(COGNITO=FAKE_COGNITO):
            self.client.get("/api/auth/logout")
        self.assertNotIn("id_token", self.client.session)
        self.assertNotIn("access_token", self.client.session)

    def test_logout_redirects_to_cognito(self):
        with self.settings(COGNITO=FAKE_COGNITO):
            resp = self.client.get("/api/auth/logout")
        self.assertEqual(resp.status_code, 302)
        self.assertIn(FAKE_COGNITO["COGNITO_DOMAIN"], resp["Location"])
        self.assertIn("/logout", resp["Location"])

    def test_logout_contains_client_id(self):
        with self.settings(COGNITO=FAKE_COGNITO):
            resp = self.client.get("/api/auth/logout")
        self.assertIn("client_id=client-abc", resp["Location"])

    def test_logout_accepts_post(self):
        with self.settings(COGNITO=FAKE_COGNITO):
            resp = self.client.post("/api/auth/logout")
        self.assertEqual(resp.status_code, 302)
