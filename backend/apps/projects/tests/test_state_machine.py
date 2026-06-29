import uuid as _uuid
from django.test import TestCase
from apps.accounts.models import UserProfile
from apps.projects.models import Project
from apps.projects.choices import Status


def make_project_in(status):
    uid = _uuid.uuid4().hex[:8]
    user = UserProfile.objects.create(
        cognito_sub=f"sub-{status}-{uid}", email=f"{status}-{uid}@example.com"
    )
    p = Project.objects.create(owner=user, prompt="test")
    Project.objects.filter(pk=p.pk).update(status=status)
    p.refresh_from_db()
    return p


class ValidTransitionsTest(TestCase):
    def test_draft_to_planning(self):
        p = make_project_in(Status.DRAFT)
        p.transition_status(Status.PLANNING)
        self.assertEqual(p.status, Status.PLANNING)

    def test_planning_to_review(self):
        p = make_project_in(Status.PLANNING)
        p.transition_status(Status.REVIEW)
        self.assertEqual(p.status, Status.REVIEW)

    def test_planning_to_failed(self):
        p = make_project_in(Status.PLANNING)
        p.transition_status(Status.FAILED)
        self.assertEqual(p.status, Status.FAILED)

    def test_review_to_generating(self):
        p = make_project_in(Status.REVIEW)
        p.transition_status(Status.GENERATING)
        self.assertEqual(p.status, Status.GENERATING)

    def test_review_to_planning(self):
        p = make_project_in(Status.REVIEW)
        p.transition_status(Status.PLANNING)
        self.assertEqual(p.status, Status.PLANNING)

    def test_generating_to_done(self):
        p = make_project_in(Status.GENERATING)
        p.transition_status(Status.DONE)
        self.assertEqual(p.status, Status.DONE)

    def test_generating_to_failed(self):
        p = make_project_in(Status.GENERATING)
        p.transition_status(Status.FAILED)
        self.assertEqual(p.status, Status.FAILED)

    def test_failed_to_generating(self):
        p = make_project_in(Status.FAILED)
        p.transition_status(Status.GENERATING)
        self.assertEqual(p.status, Status.GENERATING)


class InvalidTransitionsTest(TestCase):
    def _assert_raises(self, from_status, to_status):
        p = make_project_in(from_status)
        with self.assertRaises(ValueError):
            p.transition_status(to_status)

    def test_done_to_anything(self):
        for s in [Status.DRAFT, Status.PLANNING,
                  Status.REVIEW, Status.GENERATING,
                  Status.FAILED]:
            with self.subTest(to=s):
                self._assert_raises(Status.DONE, s)

    def test_review_to_failed(self):
        self._assert_raises(Status.REVIEW, Status.FAILED)

    def test_review_to_done(self):
        self._assert_raises(Status.REVIEW, Status.DONE)

    def test_draft_to_done(self):
        self._assert_raises(Status.DRAFT, Status.DONE)

    def test_failed_to_review(self):
        self._assert_raises(Status.FAILED, Status.REVIEW)
