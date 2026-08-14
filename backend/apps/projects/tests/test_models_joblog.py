from django.test import TestCase
from apps.accounts.models import UserProfile
from apps.projects.models import Project, JobLog


def make_project():
    user = UserProfile.objects.create(cognito_sub="sub-log", email="log@example.com")
    return Project.objects.create(owner=user, prompt="test")


class JobLogTest(TestCase):
    def setUp(self):
        self.project = make_project()




    def test_ordering_is_chronological(self):
        JobLog.objects.create(
            project=self.project, stage="plan", level="info", message="first"
        )
        JobLog.objects.create(
            project=self.project, stage="images", level="info", message="second"
        )
        stages = list(
            JobLog.objects.filter(project=self.project).values_list("stage", flat=True)
        )
        self.assertEqual(stages, ["plan", "images"])
