from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import TestCase

from apps.accounts.models import UserProfile
from apps.projects.choices import Status
from apps.projects.models import Project, Scene


def make_user(sub):
    return UserProfile.objects.create(cognito_sub=sub, email=f"{sub}@example.com")


class ProjectActionsTest(TestCase):
    def setUp(self):
        self.owner = make_user("owner-actions")
        self.project = Project.objects.create(
            owner=self.owner,
            prompt="p",
            status=Status.REVIEW,
            shot_plan={"title": "Old"},
        )
        self.scene = Scene.objects.create(
            project=self.project,
            index=0,
            narration="n",
            media_prompt="m",
        )
        session = self.client.session
        session["cognito_sub"] = self.owner.cognito_sub
        session.save()

    def test_project_patch_allowed_in_review_and_saves_shot_plan(self):
        resp = self.client.patch(
            f"/api/projects/{self.project.id}/",
            data={"shot_plan": {"title": "New"}},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.shot_plan, {"title": "New"})

    def test_project_patch_blocked_outside_review(self):
        self.project.status = Status.DONE
        self.project.save(update_fields=["status", "updated_at"])
        resp = self.client.patch(
            f"/api/projects/{self.project.id}/",
            data={"shot_plan": {"title": "Ignored"}},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 409)

    @patch("apps.projects.views._eager_thread")
    def test_regenerate_voiceovers_sets_stale_and_dispatches(self, eager_thread):
        resp = self.client.post(
            f"/api/projects/{self.project.id}/regenerate-voiceovers/",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 202)
        self.project.refresh_from_db()
        self.assertTrue(self.project.stale)
        eager_thread.assert_called_once()

    @patch("apps.projects.views._eager_thread")
    def test_reassemble_transitions_to_generating_and_dispatches(self, eager_thread):
        self.project.status = Status.DONE
        self.project.save(update_fields=["status", "updated_at"])
        resp = self.client.post(f"/api/projects/{self.project.id}/reassemble/")
        self.assertEqual(resp.status_code, 202)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, Status.VIDEO_GENERATING)
        eager_thread.assert_called_once()

    def test_download_redirects_to_storage_url(self):
        self.project.status = Status.DONE
        self.project.save(update_fields=["status", "updated_at"])
        self.project.final_video_path.save("final.mp4", ContentFile(b"video"), save=True)

        resp = self.client.get(f"/api/projects/{self.project.id}/download/", follow=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("final.mp4", resp["Location"])


class SceneActionsTest(TestCase):
    def setUp(self):
        self.owner = make_user("owner-scene")
        self.project = Project.objects.create(owner=self.owner, prompt="p", status=Status.DONE)
        self.scene = Scene.objects.create(
            project=self.project,
            index=0,
            narration="before",
            media_prompt="m",
        )
        session = self.client.session
        session["cognito_sub"] = self.owner.cognito_sub
        session.save()

    @patch("apps.projects.views._eager_thread")
    def test_revoice_updates_scene_and_marks_project_stale(self, eager_thread):
        resp = self.client.post(
            f"/api/projects/{self.project.id}/scenes/{self.scene.index}/revoice/",
            data={"narration": "after", "narrator_voice": "en-US-AndrewNeural"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 202)
        self.scene.refresh_from_db()
        self.project.refresh_from_db()
        self.assertEqual(self.scene.narration, "after")
        self.assertTrue(self.project.stale)
        eager_thread.assert_called_once()

    @patch("apps.projects.views._eager_thread")
    def test_revoice_empty_body_does_not_dispatch(self, eager_thread):
        resp = self.client.post(
            f"/api/projects/{self.project.id}/scenes/{self.scene.index}/revoice/",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 202)
        self.project.refresh_from_db()
        self.assertFalse(self.project.stale)
        eager_thread.assert_not_called()
