from django.test import TestCase
from django.db import IntegrityError
from apps.accounts.models import UserProfile
from apps.projects.models import Project, Scene
from apps.projects.choices import MediaStatus


def make_project():
    user = UserProfile.objects.create(cognito_sub="sub-scene", email="s@example.com")
    return Project.objects.create(owner=user, prompt="test")


class SceneTest(TestCase):
    def setUp(self):
        self.project = make_project()

    def test_create_scene(self):
        s = Scene.objects.create(project=self.project, index=0)
        self.assertEqual(s.project, self.project)
        self.assertEqual(s.index, 0)
        self.assertEqual(s.media_status, MediaStatus.PENDING)
        self.assertFalse(s.media_path)   # empty FileField is falsy
        self.assertEqual(s.media_provider, "")

    def test_unique_together_project_index(self):
        Scene.objects.create(project=self.project, index=0)
        with self.assertRaises(IntegrityError):
            Scene.objects.create(project=self.project, index=0)

    def test_cascade_delete_with_project(self):
        Scene.objects.create(project=self.project, index=0)
        pid = self.project.id
        self.project.delete()
        self.assertFalse(Scene.objects.filter(project_id=pid).exists())

    def test_ordering_by_index(self):
        Scene.objects.create(project=self.project, index=2)
        Scene.objects.create(project=self.project, index=0)
        Scene.objects.create(project=self.project, index=1)
        indices = list(
            Scene.objects.filter(project=self.project).values_list("index", flat=True)
        )
        self.assertEqual(indices, [0, 1, 2])
