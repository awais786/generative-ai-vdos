import uuid
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.core.models import Provider
from apps.projects.choices import Capability, Status
from apps.projects.models import LLMModel, Scene
from apps.projects.tasks import run_plan_stage, run_refine_stage
from apps.projects.tests.helpers import make_project, make_project_in, make_shot_plan


def _make_plan_model():
    provider = Provider.objects.create(code="google", name="Google")
    return LLMModel.objects.create(
        provider=provider, capability=Capability.PLAN,
        model_id="gemini-3.1-flash-lite", display_name="Gemini Flash Lite",
        is_free=True, is_default=True,
    )


def _fake_shot_plan(scene_count=2):
    plan = MagicMock()
    plan.title = "Test Video"
    plan.model_dump.return_value = make_shot_plan(scene_count)

    scenes = []
    for _ in range(scene_count):
        s = MagicMock()
        s.narration = "test narration"
        s.media_prompt = "a test image"
        s.on_screen_text = ""
        s.negative_prompt = ""
        s.animate = False
        s.voice = None
        scenes.append(s)
    plan.scenes = scenes
    return plan


@patch("apps.projects.utils.consistency_review")
@patch("apps.projects.utils.polish_image_prompts")
@patch("apps.projects.tasks.generate_shot_plan")
class RunPlanStageTest(TestCase):

    def test_happy_path(self, mock_gen, mock_polish, mock_review):
        plan = _fake_shot_plan(3)
        mock_gen.return_value = plan
        mock_polish.return_value = plan
        mock_review.return_value = plan

        llm = _make_plan_model()
        project = make_project(plan_model=llm)
        run_plan_stage(project.id)

        mock_gen.assert_called_once_with(
            project.prompt, model=llm.model_id, style=None,
            animate=False, provider=llm.provider.code, api_key=None,
        )
        project.refresh_from_db()
        self.assertEqual(project.status, Status.REVIEW)
        self.assertEqual(project.title, "Test Video")
        self.assertEqual(Scene.objects.filter(project=project).count(), 3)

    def test_missing_project_returns_early(self, mock_gen, mock_polish, mock_review):
        run_plan_stage(uuid.uuid4())
        mock_gen.assert_not_called()

    def test_pipeline_error_marks_failed(self, mock_gen, mock_polish, mock_review):
        mock_gen.side_effect = RuntimeError("LLM unavailable")

        llm = _make_plan_model()
        project = make_project(plan_model=llm)
        run_plan_stage(project.id)

        project.refresh_from_db()
        self.assertEqual(project.status, Status.FAILED)
        self.assertIn("LLM unavailable", project.error)


@patch("apps.projects.utils.consistency_review")
@patch("apps.projects.utils.polish_image_prompts")
@patch("apps.projects.tasks.revise_shot_plan")
class RunRefineStageTest(TestCase):

    def test_happy_path(self, mock_revise, mock_polish, mock_review):
        plan = _fake_shot_plan(2)
        mock_revise.return_value = plan
        mock_polish.return_value = plan
        mock_review.return_value = plan

        llm = _make_plan_model()
        project = make_project_in(
            Status.REVIEW, plan_model=llm, shot_plan=make_shot_plan(3),
        )
        run_refine_stage(project.id, "add more humor")

        mock_revise.assert_called_once()
        args, kwargs = mock_revise.call_args
        self.assertEqual(kwargs["model"], llm.model_id)
        self.assertEqual(args[1], "add more humor")

        project.refresh_from_db()
        self.assertEqual(project.status, Status.REVIEW)
        self.assertEqual(Scene.objects.filter(project=project).count(), 2)

    def test_missing_project_returns_early(self, mock_revise, mock_polish, mock_review):
        run_refine_stage(uuid.uuid4(), "change something")
        mock_revise.assert_not_called()

    def test_error_marks_failed(self, mock_revise, mock_polish, mock_review):
        mock_revise.side_effect = RuntimeError("LLM unavailable")

        llm = _make_plan_model()
        project = make_project_in(
            Status.REVIEW, plan_model=llm, shot_plan=make_shot_plan(2),
        )
        run_refine_stage(project.id, "make it darker")

        project.refresh_from_db()
        self.assertEqual(project.status, Status.FAILED)
        self.assertIn("LLM unavailable", project.error)
