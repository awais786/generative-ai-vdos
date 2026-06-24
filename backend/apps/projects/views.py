import json

from celery import chain, group
from django.db import transaction
from django.http import Http404
from django.http import StreamingHttpResponse
from django.shortcuts import redirect
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response

from apps.core.moderation.drf import blocked_response

from .models import Project, Scene, JobLog
from .serializers import (ProjectSerializer, ProjectCreateSerializer,
                          SceneSerializer, SceneUpdateSerializer, JobLogSerializer)
from .services import ProjectService, _get_redis, _eager_thread
from .tasks import run_assemble_stage, run_image_stage, run_refine_stage, run_voice_stage
from .constants import ImageStatus, Status
from apps.storage import storage_provider
from apps.projects.models import LLMModel
from apps.projects.serializers import LLMModelSerializer


class SSERenderer(BaseRenderer):
    media_type = 'text/event-stream'
    format = 'txt'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


class ProjectViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return (
            Project.objects.filter(owner=self.request.user)
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
        return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)

    def _get_locked_project(self):
        return self.get_queryset().select_for_update().get(pk=self.kwargs["pk"])

    def partial_update(self, request, *args, **kwargs):
        project = self.get_object()
        if project.status != Status.REVIEW:
            return Response(
                {"detail": "Can only edit plan in REVIEW state."},
                status=status.HTTP_409_CONFLICT,
            )
        return super().partial_update(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        with transaction.atomic():
            project = self._get_locked_project()
            if project.status != Status.REVIEW:
                return Response(
                    {"detail": f"Cannot approve from {project.status} state."},
                    status=status.HTTP_409_CONFLICT,
                )
            project.transition_status(Status.GENERATING)
        transaction.on_commit(lambda: _dispatch_generate_stage(str(project.id)))
        return Response(ProjectSerializer(project).data, status=status.HTTP_202_ACCEPTED)

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
            if project.status != Status.REVIEW:
                return Response(
                    {"detail": f"Cannot refine from {project.status} state."},
                    status=status.HTTP_409_CONFLICT,
                )
            project.transition_status(Status.PLANNING)
        project_id = str(project.id)
        transaction.on_commit(lambda: _dispatch_refine_stage(project_id, instruction))
        return Response(ProjectSerializer(project).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"], renderer_classes=[SSERenderer])
    def events(self, request, pk=None):
        project = self.get_object()

        def event_stream():
            # Replay all existing logs so late-joining clients catch up.
            for log in JobLog.objects.filter(project=project).order_by("created_at"):
                payload = json.dumps({
                    "type": "log",
                    "stage": log.stage,
                    "level": log.level,
                    "message": log.message,
                    "ts": log.created_at.isoformat(),
                    "project_status": project.status,
                    "scene_index": None,
                    "image_status": None,
                })
                yield f"data: {payload}\n\n"

            # Bail early if already terminal.
            project.refresh_from_db(fields=["status"])
            if project.status in (Status.DONE, Status.FAILED):
                return

            # Subscribe to Redis for live events.
            client = _get_redis()
            if client is None:
                # No Redis — client falls back to HTTP log polling (/logs/).
                yield ": heartbeat\n\n"
                return

            pubsub = client.pubsub()
            channel = f"project:{project.id}:events"
            pubsub.subscribe(channel)
            try:
                while True:
                    msg = pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=25
                    )
                    if msg:
                        raw = (
                            msg["data"].decode("utf-8")
                            if isinstance(msg["data"], bytes)
                            else msg["data"]
                        )
                        yield f"data: {raw}\n\n"
                        try:
                            if json.loads(raw).get("project_status") in (
                                "DONE", "FAILED"
                            ):
                                break
                        except (ValueError, AttributeError):
                            pass
                    else:
                        yield ": heartbeat\n\n"
            finally:
                try:
                    pubsub.unsubscribe(channel)
                    pubsub.close()
                except Exception:
                    pass

        response = StreamingHttpResponse(
            streaming_content=event_stream(),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    @action(detail=True, methods=["post"], url_path="regenerate-images")
    def regenerate_images(self, request, pk=None):
        project = self.get_object()
        scene_indices = list(
            Scene.objects.filter(project=project)
            .values_list("index", flat=True)
            .order_by("index")
        )
        Scene.objects.filter(project=project).update(
            image_status=ImageStatus.PENDING
        )
        _eager_thread(group(
            run_image_stage.si(str(project.id), idx) for idx in scene_indices
        ).delay())
        return Response({"queued": len(scene_indices)}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="regenerate-voiceovers")
    def regenerate_voiceovers(self, request, pk=None):
        project = self.get_object()

        project.stale = True
        project.save(update_fields=["stale", "updated_at"])
        _eager_thread(run_voice_stage.delay, str(project.id))
        return Response({"queued": 1}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"])
    def reassemble(self, request, pk=None):
        with transaction.atomic():
            project = self._get_locked_project()
            if project.status != Status.DONE:
                return Response(
                    {"detail": f"Cannot reassemble from {project.status} state."},
                    status=status.HTTP_409_CONFLICT,
                )
            project.status = Status.VIDEO_GENERATING
            project.save(update_fields=["status", "updated_at"])
        _eager_thread(run_assemble_stage.delay, str(project.id))
        return Response(ProjectSerializer(project).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        project = self.get_object()

        video_url = storage_provider.url(project.final_video_path)
        if not video_url:
            raise Http404("final.mp4 not found")
        return redirect(video_url)

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

    if scene_indices:
        tasks = [run_image_stage.s(project_id, scene_indices[0])]
        tasks += [run_image_stage.si(project_id, idx) for idx in scene_indices[1:]]
        tasks += [run_voice_stage.si(project_id), run_assemble_stage.si(project_id)]
    else:
        tasks = [run_voice_stage.s(project_id), run_assemble_stage.si(project_id)]

    _eager_thread(chain(*tasks).delay)


class LLMModelViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LLMModelSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = LLMModel.objects.filter(is_active=True).select_related("provider")
        capability = self.request.query_params.get("capability")
        if capability:
            qs = qs.filter(capability=capability)
        return qs


class SceneViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    lookup_field = "index"
    http_method_names = ["get", "patch", "post", "head", "options"]

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
        scene = self.get_object()
        serializer = SceneUpdateSerializer(scene, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(SceneSerializer(scene, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def regenerate(self, request, project_pk=None, index=None):
        with transaction.atomic():
            scene = self._get_locked_scene(index)
            prompt = request.data.get("prompt", "").strip()
            if prompt:
                if resp := blocked_response(prompt, context="regenerate-image"):
                    return resp
                scene.media_prompt = prompt
            scene.image_status = ImageStatus.PENDING
            update_fields = ["image_status", "updated_at"]
            if prompt:
                update_fields.append("media_prompt")
            scene.save(update_fields=update_fields)

        _eager_thread(run_image_stage.delay, str(scene.project_id), scene.index)
        return Response(
            SceneSerializer(scene, context=self.get_serializer_context()).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["post"])
    def revoice(self, request, project_pk=None, index=None):
        scene = self.get_object()
        narration = request.data.get("narration")
        if isinstance(narration, str):
            if resp := blocked_response(narration, context="revoice"):
                return resp
            scene.narration = narration
            scene.save(update_fields=["narration", "updated_at"])

        project = scene.project
        project.stale = True
        project.save(update_fields=["stale", "updated_at"])

        _eager_thread(run_voice_stage.delay, str(scene.project_id), scene.index)
        return Response(
            SceneSerializer(scene, context=self.get_serializer_context()).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["get"], url_path="media-urls")
    def media_urls(self, request, project_pk=None, index=None):
        scene = self.get_object()
        return Response({
            "media_url": storage_provider.url(scene.media_path),
        })
