from django.test import TestCase

from apps.accounts.models import UserProfile
from apps.projects.models import Project, Scene
from apps.projects.utils import build_shot_plan, save_plan
from pipeline.schema import Character, Scene as PlanScene, ShotPlan


def make_user(sub="plan-voice-user"):
    return UserProfile.objects.create(cognito_sub=sub, email=f"{sub}@example.com")


class SavePlanVoiceTest(TestCase):
    def test_persists_per_scene_voice(self):
        owner = make_user()
        project = Project.objects.create(owner=owner, prompt="dialogue")
        plan = ShotPlan(
            title="Dialogue",
            description="Two friends talk",
            tags=["talk"],
            music_mood="calm",
            style_prefix="cinematic",
            characters=[
                Character(name="alice", description="a woman in a red dress"),
            ],
            scenes=[
                PlanScene(
                    narration="Hello there.",
                    media_prompt="{alice} waves",
                    voice="en-US-AvaNeural",
                ),
                PlanScene(
                    narration="Hi back.",
                    media_prompt="{alice} smiles",
                    voice="en-US-AndrewNeural",
                ),
            ],
        )
        save_plan(project, plan)

        voices = list(
            Scene.objects.filter(project=project).order_by("index").values_list("voice", flat=True)
        )
        self.assertEqual(voices, ["en-US-AvaNeural", "en-US-AndrewNeural"])

        rebuilt = build_shot_plan(project)
        self.assertEqual(rebuilt.scenes[0].voice, "en-US-AvaNeural")
        self.assertEqual(rebuilt.scenes[1].voice, "en-US-AndrewNeural")
