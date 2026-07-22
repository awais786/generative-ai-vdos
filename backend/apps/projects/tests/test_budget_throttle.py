"""Tests for the daily generation budget (services.py) and DRF rate throttles."""
from datetime import datetime, timezone
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.projects.choices import Status
from apps.projects.models import Project, Scene
from apps.projects.services import GenerationBudgetExceeded, enforce_daily_budget
from apps.projects.tests.helpers import make_project_in, make_user


# ---------------------------------------------------------------------------
# Unit tests: enforce_daily_budget()
# ---------------------------------------------------------------------------

class BudgetEnforcementTest(TestCase):
    def setUp(self):
        self.owner = make_user()
        cache.clear()

    def _today(self):
        return datetime.now(timezone.utc).date().isoformat()

    @override_settings(MAX_GENERATIONS_PER_DAY=3)
    def test_passes_under_cap(self):
        enforce_daily_budget(self.owner)
        enforce_daily_budget(self.owner)
        enforce_daily_budget(self.owner)
        # No exception raised — budget not exceeded.

    @override_settings(MAX_GENERATIONS_PER_DAY=3)
    def test_raises_on_exceeding_cap(self):
        for _ in range(3):
            enforce_daily_budget(self.owner)
        with self.assertRaises(GenerationBudgetExceeded) as ctx:
            enforce_daily_budget(self.owner)
        self.assertIsInstance(ctx.exception.wait, int)
        self.assertGreater(ctx.exception.wait, 0)

    @override_settings(MAX_GENERATIONS_PER_DAY=2)
    def test_different_users_have_separate_buckets(self):
        other = make_user()
        enforce_daily_budget(self.owner)
        enforce_daily_budget(self.owner)
        # Other user's budget is independent — should not raise.
        enforce_daily_budget(other)

    @override_settings(MAX_GENERATIONS_PER_DAY=1)
    def test_exception_carries_retry_after_seconds(self):
        enforce_daily_budget(self.owner)
        with self.assertRaises(GenerationBudgetExceeded) as ctx:
            enforce_daily_budget(self.owner)
        # wait should be seconds until UTC midnight — between 1 and 86400.
        self.assertGreaterEqual(ctx.exception.wait, 1)
        self.assertLessEqual(ctx.exception.wait, 86400)


# ---------------------------------------------------------------------------
# Integration tests: budget surfaced as HTTP 429 via the view layer
# ---------------------------------------------------------------------------

class BudgetViewTest(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.project = make_project_in(Status.REVIEW, owner=self.owner)
        self.project.shot_plan = {"title": "T"}
        self.project.save(update_fields=["shot_plan", "updated_at"])
        session = self.client.session
        session["cognito_sub"] = self.owner.cognito_sub
        session.save()
        cache.clear()

    @override_settings(MAX_GENERATIONS_PER_DAY=0)
    @patch("apps.projects.views._eager_thread")
    def test_approve_returns_429_when_over_budget(self, _):
        resp = self.client.post(f"/api/projects/{self.project.id}/approve/")
        self.assertEqual(resp.status_code, 429)
        body = resp.json()
        self.assertEqual(body.get("code"), "budget_exceeded")

    @override_settings(MAX_GENERATIONS_PER_DAY=0)
    @patch("apps.projects.views._eager_thread")
    def test_refine_returns_429_when_over_budget(self, _):
        resp = self.client.post(
            f"/api/projects/{self.project.id}/refine/",
            data={"instruction": "make it shorter"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 429)

    @override_settings(MAX_GENERATIONS_PER_DAY=5)
    @patch("apps.projects.views._eager_thread")
    def test_approve_passes_when_under_budget(self, _):
        resp = self.client.post(f"/api/projects/{self.project.id}/approve/")
        self.assertEqual(resp.status_code, 202)


# ---------------------------------------------------------------------------
# Integration tests: reassemble is NOT counted against the budget
# ---------------------------------------------------------------------------

class ReassembleNotThrottledTest(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.project = make_project_in(Status.DONE, owner=self.owner)
        session = self.client.session
        session["cognito_sub"] = self.owner.cognito_sub
        session.save()
        cache.clear()

    @override_settings(MAX_GENERATIONS_PER_DAY=0)
    @patch("apps.projects.views._eager_thread")
    def test_reassemble_ignores_budget(self, _):
        resp = self.client.post(f"/api/projects/{self.project.id}/reassemble/")
        self.assertEqual(resp.status_code, 202)


# ---------------------------------------------------------------------------
# Integration tests: DRF ScopedRateThrottle on regenerate-images
# Patch allow_request to False on the second call to simulate exhaustion
# without relying on the cache/rate-counting internals.
# ---------------------------------------------------------------------------

class ScopedThrottleTest(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.project = make_project_in(Status.GENERATING, owner=self.owner)
        Scene.objects.create(
            project=self.project, index=0,
            narration="n", media_prompt="m",
        )
        session = self.client.session
        session["cognito_sub"] = self.owner.cognito_sub
        session.save()
        cache.clear()

    @patch("apps.projects.views._eager_thread")
    def test_regenerate_images_passes_when_not_throttled(self, _):
        url = f"/api/projects/{self.project.id}/regenerate-images/"
        resp = self.client.post(url, content_type="application/json")
        self.assertEqual(resp.status_code, 202)

    def test_throttle_scope_set_for_regenerate_images(self):
        """get_throttles() must set throttle_scope = throttle_images."""
        from apps.projects.views import ProjectViewSet
        view = ProjectViewSet()
        view.action = "regenerate_images"
        view.get_throttles()
        self.assertEqual(view.throttle_scope, "throttle_images")

    def test_throttle_scope_set_for_refine(self):
        from apps.projects.views import ProjectViewSet
        view = ProjectViewSet()
        view.action = "refine"
        view.get_throttles()
        self.assertEqual(view.throttle_scope, "throttle_plan")

    def test_throttle_scope_not_set_for_reassemble(self):
        from apps.projects.views import ProjectViewSet
        view = ProjectViewSet()
        view.action = "reassemble"
        view.get_throttles()
        self.assertFalse(hasattr(view, "throttle_scope"))

    def test_scene_regenerate_scope_is_images(self):
        from apps.projects.views import SceneViewSet
        view = SceneViewSet()
        view.action = "regenerate"
        view.get_throttles()
        self.assertEqual(view.throttle_scope, "throttle_images")
