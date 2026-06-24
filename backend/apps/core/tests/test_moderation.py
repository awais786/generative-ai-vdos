from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

from apps.core.moderation import check_text, content_moderation_enabled
from apps.core.moderation.blocklist import contains_blocked_term
from apps.core.moderation.exceptions import ContentPolicyViolation
from apps.core.moderation.drf import (
    ContentPolicyAPIException,
    blocked_response,
    validate_user_text,
)


class BlocklistTest(SimpleTestCase):
    def test_detects_obvious_term(self):
        self.assertTrue(contains_blocked_term("what the fuck"))

    def test_ignores_clean_text(self):
        self.assertFalse(contains_blocked_term("a friendly video about berries"))


@override_settings(CONTENT_MODERATION_ENABLED=False)
class ModerationDisabledTest(SimpleTestCase):
    def test_allows_flagged_text_when_disabled(self):
        check_text("what the fuck")

    def test_flag_is_off(self):
        self.assertFalse(content_moderation_enabled())


@override_settings(CONTENT_MODERATION_ENABLED=True)
class ModerationEnabledTest(SimpleTestCase):
    def test_blocks_blocklisted_text(self):
        with self.assertRaises(ContentPolicyViolation):
            check_text("what the fuck")

    def test_allows_clean_text_without_api_key(self):
        check_text("a wholesome story about teamwork")

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False)
    @patch("openai.OpenAI")
    def test_openai_moderation_blocks_flagged_content(self, mock_openai_cls):
        result = MagicMock()
        result.flagged = True
        mock_openai_cls.return_value.moderations.create.return_value.results = [result]

        with self.assertRaises(ContentPolicyViolation):
            check_text("some subtle harassment")

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False)
    @patch("openai.OpenAI")
    def test_openai_moderation_allows_clean_content(self, mock_openai_cls):
        result = MagicMock()
        result.flagged = False
        mock_openai_cls.return_value.moderations.create.return_value.results = [result]

        check_text("some subtle harassment")


class DRFHelpersTest(SimpleTestCase):
    @override_settings(CONTENT_MODERATION_ENABLED=True)
    def test_validate_user_text_raises(self):
        with self.assertRaises(ContentPolicyAPIException):
            validate_user_text("what the fuck")

    @override_settings(CONTENT_MODERATION_ENABLED=True)
    def test_blocked_response_returns_detail(self):
        resp = blocked_response("what the fuck")
        self.assertIsNotNone(resp)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["detail"], POLICY_MESSAGE)

    @override_settings(CONTENT_MODERATION_ENABLED=False)
    def test_blocked_response_is_none_when_disabled(self):
        self.assertIsNone(blocked_response("what the fuck"))


@override_settings(CONTENT_MODERATION_ENABLED=True)
class ProjectCreateModerationTest(TestCase):
    def setUp(self):
        from apps.accounts.models import UserProfile
        self.user = UserProfile.objects.create(
            cognito_sub="mod-user", email="mod@example.com",
        )
        session = self.client.session
        session["cognito_sub"] = "mod-user"
        session.save()

    def test_rejects_vulgar_prompt(self):
        resp = self.client.post(
            "/api/projects/",
            {"prompt": "make a fucking violent video"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("isn't allowed", resp.json()["detail"])

    def test_allows_clean_prompt(self):
        with patch("apps.projects.services._dispatch_plan_stage"):
            resp = self.client.post(
                "/api/projects/",
                {"prompt": "a video about sharing berries"},
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 201)
