import itertools
import uuid as _uuid

from apps.accounts.models import UserProfile
from apps.projects.choices import Status
from apps.projects.models import Project, Scene


def make_user(**kwargs):
    uid = _uuid.uuid4().hex[:8]
    defaults = {"cognito_sub": f"sub-{uid}", "email": f"{uid}@example.com"}
    defaults.update(kwargs)
    return UserProfile.objects.create(**defaults)


def make_project(owner=None, **kwargs):
    owner = owner or make_user()
    return Project.objects.create(owner=owner, prompt="test", **kwargs)


def make_project_in(status, **kwargs):
    p = make_project(**kwargs)
    Project.objects.filter(pk=p.pk).update(status=status)
    p.refresh_from_db()
    return p


def make_shot_plan(scene_count=2):
    return {
        "title": "Test",
        "description": "Test video.",
        "tags": ["test"],
        "music_mood": "calm",
        "style_prefix": "photo",
        "characters": [],
        "global_negative": "",
        "scenes": [
            {"narration": "test", "image_prompt": "a test image"}
            for _ in range(scene_count)
        ],
    }


def make_generating_project(scene_count=2):
    project = make_project(shot_plan=make_shot_plan(scene_count))
    project.transition_status(Status.PLANNING)
    project.transition_status(Status.REVIEW)
    project.transition_status(Status.GENERATING)
    for i in range(scene_count):
        Scene.objects.create(
            project=project, index=i,
            narration="test narration", media_prompt="a test image",
        )
    return project


_fake_counter = itertools.count()


def make_fake_image(tmp_dir):
    idx = next(_fake_counter)
    img = tmp_dir / "images" / f"scene_{idx:02d}.png"
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    return img
