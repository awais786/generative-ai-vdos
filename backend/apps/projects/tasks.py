import logging
import shutil

from celery import shared_task
from django.db import transaction

from apps.storage import storage_provider
from apps.projects.choices import MediaStatus, Level, Stage, Status, VoiceStatus
from apps.projects.models import Project, Scene
from apps.projects.services import publish_event
from apps.projects.utils import (
    animate_scene,
    fail_project,
    fetch_project_for_plan,
    generate_scene,
    generate_all_scene_voices,
    generate_scene_voice,
    handle_transient_error,
    polish_plan,
    resolve_plan_model,
    resolve_secure_key,
    save_plan,
    scene_payload,
)
from apps.projects.workdir import materialize_work_dir, music_root
from pipeline.assemble import assemble, pick_music

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

_VIDEO_TASK_OPTS = dict(
    bind=True,
    max_retries=0,
    soft_time_limit=30 * 60,
    time_limit=35 * 60,
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
        style = PRESETS.get(project.style) if project.style else None

        # Transition before resolving the key: a MissingAPIKeyError raised here
        # must still land on a status that's allowed to move to FAILED (DRAFT
        # can't go straight to FAILED — only PLANNING can).
        project.transition_status(Status.PLANNING)
        secure_key = resolve_secure_key(project.owner, llm.provider)

        logger.info(
            "Plan stage — model=%s, provider=%s, style=%s",
            model_id, provider_code, project.style or "none",
        )

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
        plan_data = {**(project.shot_plan or {})}
        plan_data["scenes"] = [
            scene_payload(s) for s in project.scenes.order_by("index")
        ]
        current_plan = ShotPlan.model_validate(plan_data)

        # Transition before resolving the key: a MissingAPIKeyError raised here
        # must still land on a status that's allowed to move to FAILED (REVIEW
        # can't go straight to FAILED — only PLANNING can).
        project.transition_status(Status.PLANNING)
        secure_key = resolve_secure_key(project.owner, llm.provider)

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
    try:
        project = Project.objects.select_related(
            "image_model", "image_model__provider", "owner",
        ).get(id=project_id)
        scene = Scene.objects.get(project_id=project_id, index=scene_index)
    except (Project.DoesNotExist, Scene.DoesNotExist):
        logger.warning("Project %s / scene %s not found, aborting image stage",
                       project_id, scene_index)
        return {"project_id": str(project_id), "scene_index": scene_index}

    # Composition scenes (title/quote/lower-third/outro cards) are rendered by
    # Remotion at assemble time — no image to generate. Mark DONE so the
    # image-review gate and approve-images can proceed.
    if scene.compose:
        template = (scene.compose or {}).get("template", "card")
        scene.media_status = MediaStatus.DONE
        scene.media_provider = "compose"
        scene.save(update_fields=["media_status", "media_provider", "updated_at"])
        publish_event(
            project_id, Stage.IMAGES, Level.INFO,
            f"Scene {scene_index} is a {template} card — no image needed",
            scene_index=scene_index, media_status=MediaStatus.DONE,
        )
        return {"project_id": str(project_id), "scene_index": scene_index}

    llm = project.image_model

    try:
        secure_key = resolve_secure_key(project.owner, llm.provider)
        generate_scene(project, scene, scene_index, secure_key, llm)
    except Exception as exc:
        scene.media_status = MediaStatus.FAILED
        scene.save(update_fields=["media_status", "updated_at"])
        is_transient = isinstance(exc, (ConnectionError, TimeoutError))
        if is_transient:
            publish_event(project_id, Stage.IMAGES, Level.ERROR,
                          f"Scene {scene_index} failed (will retry)",
                          scene_index=scene_index)
            raise  # let Celery autoretry
        # Non-transient: log and return so the Celery chain continues to
        # transition_to_image_review, letting the user regenerate this scene.
        publish_event(project_id, Stage.IMAGES, Level.ERROR,
                      f"Scene {scene_index} failed: {exc}",
                      scene_index=scene_index)
        return {"project_id": str(project_id), "scene_index": scene_index, "failed": True}

    return {"project_id": str(project_id), "scene_index": scene_index}


@shared_task(**_VIDEO_TASK_OPTS)
def run_video_stage(self, project_id, scene_index=None):
    try:
        project = Project.objects.select_related(
            "video_model", "video_model__provider", "owner",
        ).get(id=project_id)
    except Project.DoesNotExist:
        logger.warning("Project %s not found, aborting video stage", project_id)
        return {"project_id": str(project_id)}

    if not project.video_model:
        fail_project(project, project_id, Stage.VIDEO, RuntimeError("No video model configured"))
        return {"project_id": str(project_id)}

    if scene_index is not None:
        animated = list(Scene.objects.filter(
            project=project, index=scene_index, animate=True, compose__isnull=True))
    else:
        animated = list(Scene.objects.filter(
            project=project, animate=True, compose__isnull=True).order_by("index"))

    if not animated:
        publish_event(project_id, Stage.VIDEO, Level.INFO, "No animated scenes — skipping")
        return {"project_id": str(project_id)}

    llm = project.video_model
    try:
        secure_key = resolve_secure_key(project.owner, llm.provider)
    except Exception as exc:
        logger.error("Animating scenes failed. cause: %s", exc, exc_info=True)
        publish_event(project_id, Stage.VIDEO, Level.ERROR,
                      f"Animating scenes failed. cause: {exc}")
        fail_project(project, project_id, Stage.VIDEO,
                     RuntimeError(f"All animated scene submissions failed: {exc}"))
        return {"project_id": str(project_id)}

    for scene in animated:
        if (
            scene.media_status == MediaStatus.DONE
            and scene.media_path
            and scene.media_path.name.lower().endswith(".mp4")
        ):
            logger.debug("Skipping completed video for scene %s", scene.index)
            continue
        try:
            animate_scene(project, scene, scene.index, secure_key)
        except Exception as exc:
            logger.error("Video scene %s failed: %s", scene.index, exc, exc_info=True)
            scene.media_status = MediaStatus.FAILED
            scene.save(update_fields=["media_status", "updated_at"])
            publish_event(project_id, Stage.VIDEO, Level.ERROR,
                          f"Scene {scene.index} failed: {exc}")

    if scene_index is None:
        if not Scene.objects.filter(project=project, animate=True, media_status=MediaStatus.DONE).exists():
            fail_project(project, project_id, Stage.VIDEO,
                         RuntimeError("All animated scene submissions failed"))

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
    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        logger.warning("Project %s not found, aborting voice stage", project_id)
        return {"project_id": str(project_id), "scene_index": scene_index}
    if project.status == Status.FAILED:
        return {"project_id": str(project_id), "scene_index": scene_index}

    if scene_index is None:
        publish_event(project_id, Stage.VOICE, Level.INFO, "Generating voiceover")
    else:
        try:
            scene = Scene.objects.get(project_id=project_id, index=scene_index)
        except Scene.DoesNotExist:
            logger.warning("Scene %s/%s not found, aborting voice stage",
                           project_id, scene_index)
            return {"project_id": str(project_id), "scene_index": scene_index}

    try:
        if scene_index is None:
            generate_all_scene_voices(project)
            publish_event(project_id, Stage.VOICE, Level.INFO, "Voiceover done")
        else:
            generate_scene_voice(project, scene, scene.index)
    except (ConnectionError, TimeoutError) as exc:
        handle_transient_error(self, project, project_id, Stage.VOICE, exc)
    except Exception as exc:
        if scene_index is None:
            Scene.objects.filter(
                project_id=project_id,
                voice_status__in=[VoiceStatus.PENDING, VoiceStatus.RUNNING],
            ).update(voice_status=VoiceStatus.FAILED)
        if project.status in (Status.GENERATING, Status.VIDEO_GENERATING):
            fail_project(project, project_id, Stage.VOICE, exc)
        else:
            publish_event(project_id, Stage.VOICE, Level.ERROR, f"Voiceover failed: {exc}")
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
    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        logger.warning("Project %s not found, aborting assemble stage", project_id)
        return {"project_id": str(project_id)}
    if project.status == Status.FAILED:
        return {"project_id": str(project_id)}
    publish_event(project_id, Stage.ASSEMBLE, Level.INFO, "Assembling final video")

    work_dir = None
    try:
        work_dir, plan = materialize_work_dir(project)
        music = pick_music(music_root(), plan.music_mood)
        final = assemble(plan, work_dir, music_path=music)
        old_final_name = project.final_video_path.name if project.final_video_path else ""
        storage_provider.upload(project.final_video_path, final, save=False)
        project.stale = False
        project.save(update_fields=["stale", "final_video_path", "updated_at"])
        if old_final_name and old_final_name != project.final_video_path.name:
            storage_provider.storage.delete(old_final_name)
        project.transition_status(Status.DONE)
        publish_event(project_id, Stage.ASSEMBLE, Level.INFO, "Assembly complete")
    except (ConnectionError, TimeoutError) as exc:
        handle_transient_error(self, project, project_id, Stage.ASSEMBLE, exc)
    except Exception as exc:
        fail_project(project, project_id, Stage.ASSEMBLE, exc)
        raise
    finally:
        if work_dir is not None:
            shutil.rmtree(work_dir, ignore_errors=True)

    return {"project_id": project_id}


@shared_task
def transition_to_image_review(project_id):
    with transaction.atomic():
        project = Project.objects.select_for_update().get(id=project_id)
        if project.status != Status.GENERATING:
            publish_event(project_id, Stage.IMAGES, Level.WARN,
                          f"transition_to_image_review skipped: project is {project.status}")
            return {"project_id": project_id}
        # Lock scene rows so a concurrent regenerate cannot change media_status
        # between the terminal check and the status transition.
        non_terminal = project.scenes.select_for_update().exclude(
            media_status__in=[MediaStatus.DONE, MediaStatus.FAILED]
        )
        if non_terminal.exists():
            publish_event(project_id, Stage.IMAGES, Level.WARN,
                          "transition_to_image_review: some scenes still running — skipping")
            return {"project_id": project_id}
        project.transition_status(Status.IMAGE_REVIEW)
    publish_event(
        project_id, Stage.IMAGES, Level.INFO,
        "Images are ready for review. Approve them to continue generating the video.",
    )
    return {"project_id": project_id}


@shared_task
def mark_pipeline_failed(task_id, project_id):
    """Error callback for chord/chain — marks the project as FAILED."""
    logger.error("Pipeline task %s failed for project %s", task_id, project_id)
    try:
        project = Project.objects.get(id=project_id)
        if project.status != Status.FAILED:
            project.error = f"Pipeline task {task_id} failed"
            project.save(update_fields=["error", "updated_at"])
            project.transition_status(Status.FAILED)
            publish_event(project_id, Stage.IMAGES, Level.ERROR, f"Pipeline failed (task {task_id})")
    except Project.DoesNotExist:
        logger.warning("Project %s not found when marking failed", project_id)
