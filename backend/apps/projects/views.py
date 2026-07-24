import shutil

from celery import chain, chord, group
from django.db import IntegrityError, models, transaction
from django.http import Http404
from django.shortcuts import redirect
from rest_framework import mixins, viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import UserAPIKey
from apps.core.moderation.drf import blocked_response

from .models import Project, Scene, JobLog
from .serializers import (ProjectSerializer, ProjectCreateSerializer,
                          SceneSerializer, SceneUpdateSerializer, JobLogSerializer,
                          _absolute_media_url)
from .services import ProjectService, _eager_thread, enforce_daily_budget
from .utils import get_work_dir
from .workdir import assemble_is_live
from .tasks import (
    mark_pipeline_failed,
    run_assemble_stage,
    run_image_stage,
    run_refine_stage,
    run_video_stage,
    run_voice_stage,
    transition_to_image_review,
)
from .choices import MediaStatus, Status, VoiceStatus
from .constants import PROJECT_THROTTLE_SCOPES, SCENE_THROTTLE_SCOPES
from apps.storage import storage_provider
from apps.projects.models import LLMModel
from apps.projects.serializers import LLMModelSerializer



def _reset_failed_animated_scenes_with_stills(project):
    """Video-stage failures still have the PNG in storage — mark DONE to retry animation."""
    Scene.objects.filter(
        project=project,
        animate=True,
        media_status=MediaStatus.FAILED,
    ).exclude(
        media_path="",
    ).exclude(
        media_path__iendswith=".mp4",
    ).update(media_status=MediaStatus.DONE)


def _resume_failed_project(project) -> str:
    project.error = ""
    project.transition_status(Status.GENERATING)
    project.save(update_fields=["error", "updated_at"])
    _reset_failed_animated_scenes_with_stills(project)
    return str(project.id)


def _require_status(project, expected, detail):
    """Return a 409 Response if the project isn't in the expected state, else None.
    Usage: ``if resp := _require_status(...): return resp``."""
    if project.status != expected:
        return Response({"detail": detail}, status=status.HTTP_409_CONFLICT)
    return None


class ProjectViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_throttles(self):
        scope = PROJECT_THROTTLE_SCOPES.get(self.action)
        if scope:
            self.throttle_scope = scope
        return super().get_throttles()

    def get_queryset(self):
        return (
            Project.objects.filter(owner=self.request.user)
            .select_related("plan_model", "image_model", "video_model")
            .prefetch_related("scenes")
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        if self.action == "create":
            return ProjectCreateSerializer
        return ProjectSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project = ProjectService.create(owner=request.user, **serializer.validated_data)
        return Response(
            ProjectSerializer(project, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    def _get_locked_project(self):
        try:
            return self.get_queryset().select_for_update().get(pk=self.kwargs["pk"])
        except Project.DoesNotExist:
            raise Http404 from None

    def partial_update(self, request, *args, **kwargs):
        with transaction.atomic():
            project = self._get_locked_project()
            if resp := _require_status(project, Status.REVIEW,
                                       "Can only edit plan in REVIEW state."):
                return resp
            serializer = self.get_serializer(project, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        with transaction.atomic():
            project = self._get_locked_project()
            if project.status == Status.FAILED:
                enforce_daily_budget(project.owner)
                project_id = _resume_failed_project(project)
                transaction.on_commit(lambda: _dispatch_retry_stage(project_id))
                return Response(
                    self.get_serializer(project).data,
                    status=status.HTTP_202_ACCEPTED,
                )
            if resp := _require_status(project, Status.REVIEW,
                                       f"Cannot approve from {project.status} state."):
                return resp
            enforce_daily_budget(project.owner)
            project.transition_status(Status.GENERATING)
        transaction.on_commit(lambda: _dispatch_generate_stage(str(project.id)))
        return Response(self.get_serializer(project).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        with transaction.atomic():
            project = self._get_locked_project()
            if resp := _require_status(project, Status.FAILED,
                                       f"Cannot retry from {project.status} state."):
                return resp
            enforce_daily_budget(project.owner)
            project_id = _resume_failed_project(project)
        transaction.on_commit(lambda: _dispatch_retry_stage(project_id))
        return Response(self.get_serializer(project).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"])
    def refine(self, request, pk=None):
        instruction = request.data.get("instruction", "").strip()
        if not instruction:
            return Response(
                {"detail": "instruction is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if resp := blocked_response(instruction, context="refine"):
            return resp
        with transaction.atomic():
            project = self._get_locked_project()
            if resp := _require_status(project, Status.REVIEW,
                                       f"Cannot refine from {project.status} state."):
                return resp
            enforce_daily_budget(project.owner)
            project.transition_status(Status.PLANNING)
        project_id = str(project.id)
        transaction.on_commit(lambda: _dispatch_refine_stage(project_id, instruction))
        return Response(self.get_serializer(project).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="regenerate-images")
    def regenerate_images(self, request, pk=None):
        with transaction.atomic():
            project = self._get_locked_project()
            if project.status == Status.IMAGE_REVIEW:
                return Response(
                    {"detail": "Cannot bulk-regenerate images during review; regenerate scenes individually."},
                    status=status.HTTP_409_CONFLICT,
                )
            enforce_daily_budget(project.owner)
            scene_indices = list(
                Scene.objects.filter(project=project)
                .values_list("index", flat=True)
                .order_by("index")
            )
            Scene.objects.filter(project=project).update(
                media_status=MediaStatus.PENDING
            )
        _eager_thread(group(
            run_image_stage.si(str(project.id), idx) for idx in scene_indices
        ).delay)
        return Response({"queued": len(scene_indices)}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="regenerate-voiceovers")
    def regenerate_voiceovers(self, request, pk=None):
        voice = request.data.get("narrator_voice") or request.data.get("voice")
        with transaction.atomic():
            project = self._get_locked_project()
            if project.status == Status.IMAGE_REVIEW:
                return Response(
                    {"detail": "Cannot regenerate voiceovers during image review."},
                    status=status.HTTP_409_CONFLICT,
                )
            if isinstance(voice, str) and voice.strip():
                project.narrator_voice = voice.strip()
            Scene.objects.filter(project=project).update(voice_status=VoiceStatus.PENDING)
            project.stale = True
            project.save(update_fields=["narrator_voice", "stale", "updated_at"])
        _eager_thread(run_voice_stage.delay, str(project.id))
        return Response({"queued": 1}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="approve-images")
    def approve_images(self, request, pk=None):
        with transaction.atomic():
            project = self._get_locked_project()
            if resp := _require_status(project, Status.IMAGE_REVIEW,
                                       f"Cannot approve images from {project.status} state."):
                return resp
            not_done = project.scenes.select_for_update().exclude(media_status=MediaStatus.DONE)
            if not_done.exists():
                return Response(
                    {"detail": "All scenes must be DONE before approving."},
                    status=status.HTTP_409_CONFLICT,
                )
            enforce_daily_budget(project.owner)
            project.transition_status(Status.VIDEO_GENERATING)
        project_id = str(project.id)
        transaction.on_commit(lambda: _dispatch_voice_assembly(project_id))
        return Response(self.get_serializer(project).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"])
    def reassemble(self, request, pk=None):
        with transaction.atomic():
            project = self._get_locked_project()
            if resp := _require_status(project, Status.DONE,
                                       f"Cannot reassemble from {project.status} state."):
                return resp
            project.transition_status(Status.VIDEO_GENERATING)
        _eager_thread(run_assemble_stage.delay, str(project.id))
        return Response(self.get_serializer(project).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        project = self.get_object()

        video_url = storage_provider.url(project.final_video_path)
        if not video_url:
            raise Http404("final.mp4 not found")
        return redirect(video_url)

    def perform_destroy(self, instance):
        work_dir = get_work_dir(instance)
        super().perform_destroy(instance)
        assemble_dir = work_dir / "_assemble"
        if assemble_dir.exists() and assemble_is_live(assemble_dir):
            # Assembly task is in flight; its finally block cleans _assemble/.
            # Clean siblings now so large files don't linger until cleanup_workdirs runs.
            for child in work_dir.iterdir():
                if child != assemble_dir:
                    shutil.rmtree(child, ignore_errors=True)
            return
        shutil.rmtree(work_dir, ignore_errors=True)

    @action(detail=True, methods=["get"])
    def logs(self, request, pk=None):
        project = self.get_object()
        try:
            after = int(request.query_params.get("after", 0))
        except (TypeError, ValueError):
            after = 0
        logs = JobLog.objects.filter(project=project, id__gt=after).order_by("id")
        return Response(JobLogSerializer(logs, many=True).data)


def _dispatch_refine_stage(project_id: str, instruction: str) -> None:
    _eager_thread(run_refine_stage.delay, project_id, instruction)


def _dispatch_generate_stage(project_id: str) -> None:
    from .models import Scene

    scene_indices = list(
        Scene.objects.filter(project_id=project_id)
        .order_by("index")
        .values_list("index", flat=True)
    )

    error_sig = mark_pipeline_failed.s(project_id=str(project_id))

    if scene_indices:
        # Stop at the image-review gate — video/voice/assemble only run after
        # the user calls approve-images (see _dispatch_voice_assembly). Auto-chaining
        # them here used to race animate_scene() against the IMAGE_REVIEW gate,
        # flipping Scene.media_status back to RUNNING and wedging approve-images
        # in a permanent 409.
        canvas = chord(
            group(run_image_stage.si(project_id, idx).on_error(error_sig) for idx in scene_indices),
            transition_to_image_review.si(project_id).on_error(error_sig),
        )
    else:
        canvas = chain(
            run_video_stage.si(project_id),
            run_voice_stage.si(project_id),
            run_assemble_stage.si(project_id),
        ).on_error(error_sig)

    _eager_thread(lambda: canvas.apply_async())


def _dispatch_voice_assembly(project_id: str) -> None:
    _eager_thread(chain(
        run_video_stage.s(project_id),
        run_voice_stage.si(project_id),
        run_assemble_stage.si(project_id),
    ).delay)


def _dispatch_retry_stage(project_id: str) -> None:
    """Resume a FAILED project from the first incomplete stage."""
    pending_images = list(
        Scene.objects.filter(
            project_id=project_id,
            media_status__in=[MediaStatus.PENDING, MediaStatus.FAILED],
        )
        .order_by("index")
        .values_list("index", flat=True)
    )

    needs_video = Scene.objects.filter(
        project_id=project_id,
        animate=True,
    ).exclude(media_path__iendswith=".mp4").exists()

    tasks = []
    if pending_images:
        tasks.append(run_image_stage.s(project_id, pending_images[0]))
        tasks += [run_image_stage.si(project_id, idx) for idx in pending_images[1:]]
    if needs_video:
        tasks.append(run_video_stage.si(project_id))
    tasks += [run_voice_stage.si(project_id), run_assemble_stage.si(project_id)]

    _eager_thread(chain(*tasks).delay)


class LLMModelViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = LLMModelSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = LLMModel.objects.filter(is_active=True).filter(
            models.Q(owner__isnull=True) | models.Q(owner=self.request.user)
        ).select_related("provider")
        capability = self.request.query_params.get("capability")
        if capability:
            qs = qs.filter(capability=capability)
        return qs

    def perform_create(self, serializer):
        provider = serializer.validated_data["provider"]
        if not UserAPIKey.objects.filter(owner=self.request.user, provider=provider).exists():
            raise ValidationError({"provider": "Add an API key for this provider first."})
        # `owner` isn't a serializer field, so DRF can't validate the DB's
        # unique_owned_provider_capability_model constraint up front — a
        # duplicate model_id for this user hits IntegrityError on save.
        # Nested atomic() gives it a savepoint, so the failed insert can't
        # poison an enclosing transaction.
        try:
            with transaction.atomic():
                serializer.save(owner=self.request.user, is_free=False, is_default=False, is_active=True)
        except IntegrityError:
            raise ValidationError({"model_id": "You already have a model with this ID for this provider."})

    def perform_destroy(self, instance):
        if instance.owner_id != self.request.user.id:
            raise PermissionDenied("Cannot delete a model you don't own.")
        instance.delete()


class SceneViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    lookup_field = "index"
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_throttles(self):
        scope = SCENE_THROTTLE_SCOPES.get(self.action)
        if scope:
            self.throttle_scope = scope
        return super().get_throttles()

    def get_queryset(self):
        return Scene.objects.filter(
            project_id=self.kwargs["project_pk"],
            project__owner=self.request.user,
        )

    def get_serializer_class(self):
        if self.action == "partial_update":
            return SceneUpdateSerializer
        return SceneSerializer

    def _get_locked_scene(self, index):
        return self.get_queryset().select_for_update().get(index=index)

    def list(self, request, project_pk=None):
        qs = self.get_queryset()
        return Response(self.get_serializer(qs, many=True).data)

    def retrieve(self, request, project_pk=None, index=None):
        scene = self.get_object()
        return Response(self.get_serializer(scene).data)

    def partial_update(self, request, project_pk=None, index=None):
        with transaction.atomic():
            scene = self._get_locked_scene(index)
            serializer = SceneUpdateSerializer(scene, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            changed = set(serializer.validated_data.keys())
            serializer.save()

            # An edit desyncs the scene from any already-generated asset. Reset the
            # affected asset's status so it regenerates, and flag the project stale
            # if a final video already exists — otherwise the prompt/narration would
            # silently diverge from the rendered image/voiceover/final.mp4.
            image_fields = {"media_prompt", "animate", "negative_prompt"}
            status_fields = []
            if changed & image_fields and scene.media_status != MediaStatus.PENDING:
                scene.media_status = MediaStatus.PENDING
                status_fields.append("media_status")
            if "narration" in changed and scene.voice_status != VoiceStatus.PENDING:
                scene.voice_status = VoiceStatus.PENDING
                status_fields.append("voice_status")
            if status_fields:
                scene.save(update_fields=[*status_fields, "updated_at"])

            project = scene.project
            if changed and project.status == Status.DONE and not project.stale:
                project.stale = True
                project.save(update_fields=["stale", "updated_at"])

        return Response(SceneSerializer(scene, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def regenerate(self, request, project_pk=None, index=None):
        with transaction.atomic():
            scene = self._get_locked_scene(index)
            if scene.compose:
                return Response(
                    {"detail": "this scene is a composition card, not an image — nothing to regenerate"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            enforce_daily_budget(scene.project.owner)
            prompt = request.data.get("prompt", "").strip()
            if prompt:
                if resp := blocked_response(prompt, context="regenerate-image"):
                    return resp
                scene.media_prompt = prompt
            scene.media_status = MediaStatus.PENDING
            update_fields = ["media_status", "updated_at"]
            if prompt:
                update_fields.append("media_prompt")
            scene.save(update_fields=update_fields)

        project_id = str(scene.project_id)
        idx = scene.index
        if scene.animate:
            _eager_thread(chain(
                run_image_stage.si(project_id, idx),
                run_video_stage.si(project_id, idx),
            ).delay)
        else:
            _eager_thread(run_image_stage.delay, project_id, idx)
        return Response(
            SceneSerializer(scene, context=self.get_serializer_context()).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["post"])
    def revoice(self, request, project_pk=None, index=None):
        scene = self.get_object()
        narration = request.data.get("narration")
        voice = request.data.get("voice") or request.data.get("narrator_voice")
        update_fields = ["updated_at"]

        if isinstance(narration, str):
            if resp := blocked_response(narration, context="revoice"):
                return resp
            scene.narration = narration
            update_fields.append("narration")
        if isinstance(voice, str) and voice.strip():
            scene.voice = voice.strip()
            update_fields.append("voice")

        if len(update_fields) > 1:
            scene.voice_status = VoiceStatus.PENDING
            update_fields.append("voice_status")
            scene.save(update_fields=update_fields)
            project = scene.project
            project.stale = True
            project.save(update_fields=["stale", "updated_at"])
            _eager_thread(run_voice_stage.delay, str(scene.project_id), scene.index)

        return Response(
            SceneSerializer(scene, context=self.get_serializer_context()).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["get"], url_path="audio-urls")
    def audio_urls(self, request, project_pk=None, index=None):
        scene = self.get_object()
        return Response({
            "audio_url": _absolute_media_url(
                storage_provider.url(scene.audio_path) or "",
                request,
            ),
        })

    @action(detail=True, methods=["get"], url_path="media-urls")
    def media_urls(self, request, project_pk=None, index=None):
        scene = self.get_object()
        return Response({
            "media_url": _absolute_media_url(
                storage_provider.url(scene.media_path) or "",
                request,
            ),
        })
