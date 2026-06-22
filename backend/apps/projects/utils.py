import logging
import tempfile
from pathlib import Path

from django.conf import settings
from apps.storage import storage_provider
from django.db import transaction

from apps.accounts.models import UserAPIKey
from apps.projects.constants import Capability, ImageStatus, Level, Stage, Status
from apps.projects.models import LLMModel, Project, Scene
from apps.projects.services import publish_event

from pipeline.images import generate_scene_image, get_provider
from pipeline.schema import ShotPlan
from pipeline.script_agent import consistency_review, polish_image_prompts

logger = logging.getLogger(__name__)


def get_work_dir(project):
    return Path(settings.MEDIA_ROOT) / str(project.owner_id) / str(project.id)


def resolve_secure_key(owner, provider):
    try:
        return UserAPIKey.objects.get(
            owner=owner, provider=provider,
        ).get_secure_key()
    except UserAPIKey.DoesNotExist:
        return None


def resolve_plan_model(project):
    llm = project.plan_model or LLMModel.objects.filter(
        capability=Capability.PLAN, is_default=True, is_active=True,
    ).select_related("provider").first()

    if not llm:
        raise RuntimeError("No plan model assigned and no default plan model configured.")

    return llm


def polish_plan(plan, model_id, provider_code, secure_key, animate=True):
    plan = polish_image_prompts(plan, model=model_id,
                                provider=provider_code, api_key=secure_key)
    plan = consistency_review(plan, model=model_id, animate=animate,
                              provider=provider_code, api_key=secure_key)
    return plan


def save_plan(project, plan):
    with transaction.atomic():
        # Scenes are the DB source of truth; shot_plan stores only plan-level metadata.
        project.shot_plan = plan.model_dump(exclude={"scenes"})
        project.title = plan.title
        project.save(update_fields=["shot_plan", "title", "updated_at"])

        project.scenes.all().delete()
        Scene.objects.bulk_create([
            Scene(
                project=project,
                index=i,
                narration=scene.narration,
                media_prompt=scene.media_prompt,
                on_screen_text=scene.on_screen_text or "",
                negative_prompt=scene.negative_prompt or "",
                animate=scene.animate,
            )
            for i, scene in enumerate(plan.scenes)
        ])


def fetch_project_for_plan(project_id):
    try:
        return Project.objects.select_related(
            "plan_model", "plan_model__provider", "owner",
        ).get(id=project_id)
    except Project.DoesNotExist:
        logger.error("Project %s not found, aborting stage", project_id)
        return None


def handle_transient_error(task, project, project_id, stage, exc):
    retries_left = task.max_retries - task.request.retries
    if retries_left > 0:
        logger.warning("%s stage transient error, %d retries left: %s", stage, retries_left, exc)
        raise
    fail_project(project, project_id, stage, exc)


def fail_project(project, project_id, stage, exc):
    error_type = type(exc).__name__
    error_message = f"[{error_type}] {exc}"
    logger.error("%s stage failed: %s", stage, error_message)
    project.error = error_message[:2000]
    project.save(update_fields=["error", "updated_at"])
    project.transition_status(Status.FAILED)
    publish_event(project_id, stage, Level.ERROR, error_message[:500])


def generate_scene(project, scene, scene_index):
    project_id = project.id

    # Build ShotPlan from plan-level metadata + DB scenes (single source of truth).
    plan_data = {**(project.shot_plan or {})}
    plan_data["scenes"] = [
        {
            "media_prompt": scene.media_prompt,
            "narration": scene.narration,
            "negative_prompt": scene.negative_prompt or None,
            "animate": scene.animate,
            "on_screen_text": scene.on_screen_text or None,
        }
        for scene in Scene.objects.filter(project=project).order_by("index")
    ]
    plan = ShotPlan.model_validate(plan_data)

    llm = project.image_model
    if not llm:
        raise RuntimeError("No image model assigned to project.")

    secure_key = resolve_secure_key(project.owner, llm.provider)
    provider = get_provider(llm.provider.code, api_key=secure_key)

    scene.image_status = ImageStatus.RUNNING
    scene.save(update_fields=["image_status", "updated_at"])
    publish_event(
        project_id, Stage.IMAGES, Level.INFO,
        f"Generating image for scene {scene_index} via {provider.name} ({llm.model_id})",
        scene_index=scene_index,
        image_status=ImageStatus.RUNNING,
    )

    data, used = generate_scene_image(
        plan, scene_index, provider,
        fallback=False,
        api_key=secure_key,
        model=llm.model_id,
    )

    if scene.media_path:
        scene.media_path.delete(save=False)

    filename = f"scene_{scene_index:02d}.png"
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / filename
            tmp_path.write_bytes(data)
            storage_provider.upload(scene.media_path, tmp_path, save=False)
    except Exception as e:
        logger.error("Failed to upload image to storage: %s", e)
        scene.image_status = ImageStatus.FAILED
        scene.save(update_fields=["image_status", "updated_at"])
        publish_event(
            project_id, Stage.IMAGES, Level.ERROR,
            f"Failed to upload image for scene {scene_index}: {e}",
            scene_index=scene_index,
            image_status=ImageStatus.FAILED,
        )
        raise

    scene.image_status = ImageStatus.DONE
    scene.image_provider = used.name
    scene.save(update_fields=["media_path", "image_status", "image_provider", "updated_at"])
    publish_event(
        project_id, Stage.IMAGES, Level.INFO,
        f"Scene {scene_index} image done via {used.name}",
        scene_index=scene_index,
        image_status=ImageStatus.DONE,
    )
    return scene.media_path.name
