
from django.test import TestCase

from apps.accounts.models import UserProfile
from apps.projects.choices import MusicMood, NarratorVoice, Status
from apps.projects.models import Project


def make_user(sub="sub-1"):
    return UserProfile.objects.create(cognito_sub=sub, email=f"{sub}@example.com")


def make_project(owner=None, **kwargs):
    if owner is None:
        owner = make_user()
    return Project.objects.create(owner=owner, prompt="a test prompt", **kwargs)


class ProjectFieldsTest(TestCase):

    def test_defaults(self):
        p = make_project()
        self.assertEqual(p.status, Status.DRAFT)
        self.assertIsNone(p.shot_plan)
        self.assertIsNone(p.plan_model)
        self.assertIsNone(p.image_model)
        self.assertIsNone(p.video_model)
        self.assertFalse(p.animate)
        self.assertEqual(p.narrator_voice, NarratorVoice.ANDREW)
        self.assertEqual(p.music, MusicMood.CALM)
        self.assertEqual(p.error, "")
        self.assertFalse(p.stale)
        self.assertEqual(p.title, "")



