import uuid

from django.db import models, transaction

from apps.accounts.models import UserProfile
from apps.core.models import TimestampMixin
from apps.projects.constants import (
    TRANSITIONS,
    Capability,
    ImageStatus,
    Level,
    MusicMood,
    NarratorVoice,
    Stage,
    Status,
    StylePreset,
)


class LLMModel(TimestampMixin):
    provider     = models.ForeignKey(
        "core.Provider", on_delete=models.PROTECT, related_name="llm_models",
    )
    capability   = models.CharField(max_length=10, choices=Capability.choices, db_index=True)
    model_id     = models.CharField(max_length=100)
    display_name = models.CharField(max_length=150)
    is_free      = models.BooleanField(default=False)
    is_default   = models.BooleanField(default=False)
    is_active    = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = "LLM Model"
        verbose_name_plural = "LLM Models"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "capability", "model_id"],
                name="unique_provider_capability_model",
            ),
        ]
        ordering = ["-is_default", "-is_free", "display_name"]

    def save(self, **kwargs):
        with transaction.atomic():
            if self.is_default:
                LLMModel.objects.select_for_update().filter(
                    capability=self.capability, is_default=True,
                ).exclude(pk=self.pk).update(is_default=False)
            super().save(**kwargs)

    def __str__(self):
        return f"{self.display_name} ({self.provider.code})"


def scene_media_upload_path(instance: "Scene", filename) -> str:
    # Use owner_id (FK column on project) rather than owner.id so the key can be
    # built from the select_related("project") row without loading UserProfile.
    if instance.animate:
        return f"{instance.project.owner_id}/{instance.project.id}/clip/{filename}"
    else:
        return f"{instance.project.owner_id}/{instance.project.id}/images/{filename}"

def video_upload_path(instance: "Project", filename) -> str:
    return f"{instance.owner_id}/{instance.id}/videos/{filename}"


class Project(TimestampMixin):
    Status = Status
    ImageStatus = ImageStatus

    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner          = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, related_name="projects", db_index=True
    )
    prompt         = models.TextField()
    title          = models.CharField(max_length=200, blank=True, default="")
    status         = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    shot_plan      = models.JSONField(null=True, blank=True)
    style          = models.CharField(
        max_length=20, choices=StylePreset.choices, blank=True, default="",
    )
    animate        = models.BooleanField(default=False)
    narrator_voice = models.CharField(
        max_length=100, choices=NarratorVoice.choices, blank=True, default=NarratorVoice.ANDREW
    )
    music          = models.CharField(
        max_length=200, choices=MusicMood.choices, blank=True, default=MusicMood.CALM
    )
    plan_model  = models.ForeignKey(
        "projects.LLMModel", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="plan_projects",
        limit_choices_to={"capability": "plan", "is_active": True},
    )
    image_model = models.ForeignKey(
        "projects.LLMModel", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="image_projects",
        limit_choices_to={"capability": "image", "is_active": True},
    )
    video_model = models.ForeignKey(
        "projects.LLMModel", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="video_projects",
        limit_choices_to={"capability": "video", "is_active": True},
    )
    final_video_path = models.FileField(upload_to=video_upload_path, blank=True, default="")
    error          = models.TextField(blank=True, default="")
    stale          = models.BooleanField(default=False)

    def transition_status(self, new_status):
        allowed = TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition Project from {self.status!r} to {new_status!r}."
            )
        self.status = new_status
        self.save(update_fields=["status", "updated_at"])

    def __str__(self):
        return f"Project({self.id}, {self.status})"


class Scene(TimestampMixin):
    ImageStatus = ImageStatus

    project        = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="scenes"
    )
    index          = models.IntegerField()
    narration      = models.TextField()
    media_prompt   = models.TextField()
    on_screen_text = models.CharField(max_length=256, blank=True, default="")
    negative_prompt = models.TextField(max_length=256, blank=True, default="")
    animate        = models.BooleanField(default=False)
    media_path     = models.FileField(upload_to=scene_media_upload_path, blank=True, default="")
    image_status   = models.CharField(
        max_length=20, choices=ImageStatus.choices, default=ImageStatus.PENDING
    )
    image_provider = models.CharField(max_length=50, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "index"],
                name="unique_scene_project_index",
            ),
        ]
        ordering = ["index"]

    def __str__(self):
        return f"Scene {self.index} of {self.project_id}"


class JobLog(TimestampMixin):
    project    = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="logs")
    stage      = models.CharField(max_length=10, choices=Stage.choices)
    level      = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)
    message    = models.TextField()

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"[{self.stage}/{self.level}] {self.message[:80]}"
