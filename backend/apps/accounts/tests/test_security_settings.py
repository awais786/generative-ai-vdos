from django.conf import settings
from django.test import TestCase


class SessionCookieSecurityTest(TestCase):
    """Tripwire: CognitoSessionAuthentication skips CSRF tokens and relies
    solely on SESSION_COOKIE_SAMESITE to block cross-site writes. These tests
    ensure that assumption is never silently dropped by a settings override."""

    def test_samesite_is_lax(self):
        value = settings.SESSION_COOKIE_SAMESITE
        self.assertEqual(
            value,
            "Lax",
            f"SESSION_COOKIE_SAMESITE={value!r} — only 'Lax' is safe here: "
            "'Strict' breaks the Cognito OAuth callback redirect, and 'None' "
            "allows cross-site cookie submission without CSRF token enforcement.",
        )

    def test_session_cookie_httponly(self):
        self.assertTrue(
            settings.SESSION_COOKIE_HTTPONLY,
            "SESSION_COOKIE_HTTPONLY must be True to prevent JS from reading the session cookie.",
        )
