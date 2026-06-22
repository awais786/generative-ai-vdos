import logging

from celery import shared_task

from apps.projects.constants import ImageStatus, Level, Stage, Status
from apps.projects.models import Project, Scene
from apps.projects.services import publish_event
from apps.projects.utils import (
    fail_project,
    fetch_project_for_plan,
    generate_scene,
    get_work_dir,
    handle_transient_error,
    polish_plan,
    resolve_plan_model,
    resolve_secure_key,
    save_plan,
)

from pipeline.schema import ShotPlan
from pipeline.script_agent import generate_shot_plan, revise_shot_plan
from pipeline.styles import PRESETS

logger = logging.getLogger(__name__)

_PLAN_TASK_OPTS = dict(
    bind=True,
    max_retries=2,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    soft_time_limit=5 * 60,
    time_limit=6 * 60,
)

_IMAGE_TASK_OPTS = dict(
    bind=True,
    max_retries=3,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    soft_time_limit=10 * 60,
    time_limit=12 * 60,
)


@shared_task(**_PLAN_TASK_OPTS)
def run_plan_stage(self, project_id):
    project = fetch_project_for_plan(project_id)
    if project is None:
        return {"project_id": str(project_id)}

    try:
        llm = resolve_plan_model(project)
        model_id = llm.model_id
        provider_code = llm.provider.code
        secure_key = resolve_secure_key(project.owner, llm.provider)
        style = PRESETS.get(project.style) if project.style else None

        logger.info(
            "Plan stage — model=%s, provider=%s, key_source=%s, style=%s",
            model_id, provider_code,
            "db" if secure_key else "env-fallback",
            project.style or "none",
        )

        project.transition_status(Status.PLANNING)

        publish_event(project_id, Stage.PLAN, Level.INFO, f"Generating shot plan with {model_id}")
        plan = generate_shot_plan(project.prompt, model=model_id, style=style,
                                  animate=project.animate,
                                  provider=provider_code, api_key=secure_key)

        publish_event(project_id, Stage.PLAN, Level.INFO, "Polishing image prompts")
        plan = polish_plan(plan, model_id, provider_code, secure_key, animate=project.animate)
        save_plan(project, plan)

        publish_event(project_id, Stage.PLAN, Level.INFO, f"Shot plan ready — {len(plan.scenes)} scenes")
        project.transition_status(Status.REVIEW)

    except (ConnectionError, TimeoutError) as exc:
        handle_transient_error(self, project, project_id, Stage.PLAN, exc)
    except Exception as exc:
        fail_project(project, project_id, Stage.PLAN, exc)

    return {"project_id": str(project_id)}


@shared_task(**_PLAN_TASK_OPTS)
def run_refine_stage(self, project_id, instruction):
    project = fetch_project_for_plan(project_id)
    if project is None:
        return {"project_id": str(project_id)}

    if project.status != Status.REVIEW:
        publish_event(project_id, Stage.PLAN, Level.WARN,
                      f"Refine skipped — project is {project.status}, expected REVIEW")
        return {"project_id": str(project_id)}

    try:
        llm = resolve_plan_model(project)
        model_id = llm.model_id
        provider_code = llm.provider.code
        secure_key = resolve_secure_key(project.owner, llm.provider)
        plan_data = {**(project.shot_plan or {})}
        plan_data["scenes"] = [
            {
                "media_prompt": s.media_prompt,
                "narration": s.narration,
                "negative_prompt": s.negative_prompt or None,
                "animate": s.animate,
                "on_screen_text": s.on_screen_text or None,
            }
            for s in project.scenes.order_by("index")
        ]
        current_plan = ShotPlan.model_validate(plan_data)

        project.transition_status(Status.PLANNING)

        publish_event(project_id, Stage.PLAN, Level.INFO, f"Revising shot plan with {model_id}")
        plan = revise_shot_plan(current_plan, instruction, model=model_id,
                                provider=provider_code, api_key=secure_key)

        publish_event(project_id, Stage.PLAN, Level.INFO, "Polishing image prompts")
        plan = polish_plan(plan, model_id, provider_code, secure_key, animate=project.animate)
        save_plan(project, plan)

        publish_event(project_id, Stage.PLAN, Level.INFO, f"Revised plan ready — {len(plan.scenes)} scenes")
        project.transition_status(Status.REVIEW)

    except (ConnectionError, TimeoutError) as exc:
        handle_transient_error(self, project, project_id, Stage.PLAN, exc)
    except Exception as exc:
        fail_project(project, project_id, Stage.PLAN, exc)

    return {"project_id": str(project_id)}


@shared_task(**_IMAGE_TASK_OPTS)
def run_image_stage(self, project_id, scene_index):
    project = Project.objects.select_related(
        "image_model", "image_model__provider", "owner",
    ).get(id=project_id)
    scene = Scene.objects.get(project_id=project_id, index=scene_index)

    try:
        generate_scene(project, scene, scene_index)
    except Exception as exc:
        scene.image_status = ImageStatus.FAILED
        scene.save(update_fields=["image_status", "updated_at"])
        is_transient = isinstance(exc, (ConnectionError, TimeoutError))
        msg = (f"Scene {scene_index} failed (will retry)" if is_transient
               else f"Scene {scene_index} failed: {exc}")
        publish_event(project_id, Stage.IMAGES, Level.ERROR, msg,
                      scene_index=scene_index)
        raise

    return {"project_id": str(project_id), "scene_index": scene_index}


@shared_task(
    bind=True,
    max_retries=3,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    soft_time_limit=15 * 60,
    time_limit=18 * 60,
)
def run_voice_stage(self, project_id, scene_index=None):
    project = Project.objects.get(id=project_id)
    if scene_index is None:
        publish_event(project_id, Stage.VOICE, Level.INFO, "Generating voiceover")
    else:
        publish_event(project_id, Stage.VOICE, Level.INFO, f"Generating voiceover for scene {scene_index}")

    try:
        work_dir = get_work_dir(project)
        work_dir.mkdir(parents=True, exist_ok=True)
        # TODO: call actual TTS backend (edge-tts is free, no key needed)
        if scene_index is None:
            publish_event(project_id, Stage.VOICE, Level.INFO, "Voiceover done")
        else:
            publish_event(project_id, Stage.VOICE, Level.INFO, f"Voiceover done for scene {scene_index}")
    except Exception as exc:
        is_transient = isinstance(exc, (ConnectionError, TimeoutError))
        message = "Voiceover failed (will retry)" if is_transient else f"Voiceover failed: {exc}"
        publish_event(project_id, Stage.VOICE, Level.ERROR, message)
        raise

    return {"project_id": project_id, "scene_index": scene_index}


@shared_task(
    bind=True,
    max_retries=2,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    soft_time_limit=20 * 60,
    time_limit=25 * 60,
)
def run_assemble_stage(self, project_id):
    project = Project.objects.get(id=project_id)
    publish_event(project_id, Stage.ASSEMBLE, Level.INFO, "Assembling final video")

    try:
        work_dir = get_work_dir(project)
        work_dir.mkdir(parents=True, exist_ok=True)
        # TODO: call actual FFmpeg assembly (no external API, no key needed)
        project.stale = False
        project.save(update_fields=["stale", "updated_at"])
        project.transition_status(Status.DONE)
        publish_event(project_id, Stage.ASSEMBLE, Level.INFO, "Assembly complete")
    except Exception as exc:
        is_transient = isinstance(exc, (ConnectionError, TimeoutError))
        message = "Assembly failed (will retry)" if is_transient else f"Assembly failed: {exc}"
        publish_event(project_id, Stage.ASSEMBLE, Level.ERROR, message)
        raise

    return {"project_id": project_id}


@shared_task
def mark_pipeline_failed(task_id, project_id):
    """Error callback for chord/chain — marks the project as FAILED."""
    logger.error("Pipeline task %s failed for project %s", task_id, project_id)
    try:
        project = Project.objects.get(id=project_id)
        project.error = f"Pipeline task {task_id} failed"
        project.save(update_fields=["error", "updated_at"])
        project.transition_status(Status.FAILED)
        publish_event(project_id, Stage.IMAGES, Level.ERROR, f"Pipeline failed (task {task_id})")
    except Project.DoesNotExist:
        logger.warning("Project %s not found when marking failed", project_id)
