from django.test import TestCase
from django.db import IntegrityError
from apps.accounts.models import UserProfile
from apps.projects.models import Project, Scene


def make_project():
    user = UserProfile.objects.create(cognito_sub="sub-scene", email="s@example.com")
    return Project.objects.create(owner=user, prompt="test")


class SceneTest(TestCase):
    def setUp(self):
        self.project = make_project()


    def test_unique_together_project_index(self):
        Scene.objects.create(project=self.project, index=0)
        with self.assertRaises(IntegrityError):
            Scene.objects.create(project=self.project, index=0)


    def test_ordering_by_index(self):
        Scene.objects.create(project=self.project, index=2)
        Scene.objects.create(project=self.project, index=0)
        Scene.objects.create(project=self.project, index=1)
        indices = list(
            Scene.objects.filter(project=self.project).values_list("index", flat=True)
        )
        self.assertEqual(indices, [0, 1, 2])
