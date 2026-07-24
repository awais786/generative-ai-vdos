from django.test import TestCase

from apps.projects.choices import Level, Stage, Status
from apps.projects.models import JobLog
from apps.projects.tests.helpers import make_project, make_user


class LogsCursorTest(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.project = make_project(owner=self.owner, status=Status.GENERATING)
        self.other_project = make_project(owner=self.owner, status=Status.GENERATING)

        self.log1 = JobLog.objects.create(
            project=self.project, stage=Stage.PLAN, level=Level.INFO, message="first"
        )
        self.log2 = JobLog.objects.create(
            project=self.project, stage=Stage.IMAGES, level=Level.INFO, message="second"
        )
        self.log3 = JobLog.objects.create(
            project=self.project, stage=Stage.VOICE, level=Level.INFO, message="third"
        )
        # Row for a different project — must never appear in results.
        JobLog.objects.create(
            project=self.other_project, stage=Stage.PLAN, level=Level.INFO, message="other"
        )

        session = self.client.session
        session["cognito_sub"] = self.owner.cognito_sub
        session.save()

    def _get_logs(self, after=0):
        return self.client.get(
            f"/api/projects/{self.project.id}/logs/",
            {"after": after},
        )

    def test_no_cursor_returns_all_logs_for_project(self):
        resp = self._get_logs()
        self.assertEqual(resp.status_code, 200)
        ids = [r["id"] for r in resp.json()]
        self.assertIn(self.log1.id, ids)
        self.assertIn(self.log2.id, ids)
        self.assertIn(self.log3.id, ids)

    def test_after_cursor_excludes_seen_rows(self):
        resp = self._get_logs(after=self.log1.id)
        self.assertEqual(resp.status_code, 200)
        ids = [r["id"] for r in resp.json()]
        self.assertNotIn(self.log1.id, ids)
        self.assertIn(self.log2.id, ids)
        self.assertIn(self.log3.id, ids)

    def test_after_last_log_returns_empty(self):
        resp = self._get_logs(after=self.log3.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_other_project_logs_never_appear(self):
        resp = self._get_logs()
        messages = [r["message"] for r in resp.json()]
        self.assertNotIn("other", messages)

    def test_invalid_after_falls_back_to_zero(self):
        resp = self.client.get(
            f"/api/projects/{self.project.id}/logs/",
            {"after": "not-a-number"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 3)
