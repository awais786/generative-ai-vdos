from rest_framework import serializers

from apps.core.moderation.drf import ModeratedFieldsMixin
from apps.projects.models import JobLog, LLMModel, Project, Scene


def _model_slug(capability):
    return serializers.SlugRelatedField(
        slug_field="model_id",
        queryset=LLMModel.objects.filter(capability=capability, is_active=True),
        required=False,
        allow_null=True,
    )


class SceneSerializer(serializers.ModelSerializer):
    class Meta:
        model = Scene
        fields = [
            "id", "index", "narration", "media_prompt", "animate",
            "on_screen_text", "negative_prompt",
            "media_path", "image_status", "image_provider",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "index", "media_path", "image_status",
            "image_provider", "created_at", "updated_at",
        ]


class SceneUpdateSerializer(ModeratedFieldsMixin, serializers.ModelSerializer):
    moderated_fields = ("narration", "media_prompt", "on_screen_text", "negative_prompt")

    class Meta:
        model = Scene
        fields = ["narration", "media_prompt", "animate", "on_screen_text", "negative_prompt"]


class JobLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobLog
        fields = ["id", "stage", "level", "message", "created_at"]
        read_only_fields = fields


class LLMModelSerializer(serializers.ModelSerializer):
    provider = serializers.CharField(source="provider.code", read_only=True)

    class Meta:
        model = LLMModel
        fields = [
            "id", "model_id", "display_name", "provider",
            "capability", "is_free", "is_default",
        ]
        read_only_fields = fields


class ProjectSerializer(ModeratedFieldsMixin, serializers.ModelSerializer):
    moderated_fields = ("prompt", "title")
    scenes = SceneSerializer(many=True, read_only=True)
    plan_model = _model_slug("plan")
    image_model = _model_slug("image")
    video_model = _model_slug("video")

    class Meta:
        model = Project
        fields = [
            "id", "title", "prompt", "status", "shot_plan",
            "plan_model", "image_model", "video_model",
            "style", "animate", "narrator_voice", "music",
            "error", "stale", "scenes", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "error", "stale",
            "created_at", "updated_at",
        ]


class ProjectCreateSerializer(ModeratedFieldsMixin, serializers.ModelSerializer):
    moderated_fields = ("prompt", "title")
    plan_model = _model_slug("plan")
    image_model = _model_slug("image")
    video_model = _model_slug("video")

    class Meta:
        model = Project
        fields = [
            "prompt", "title", "plan_model", "image_model", "video_model",
            "style", "animate", "narrator_voice", "music",
        ]
