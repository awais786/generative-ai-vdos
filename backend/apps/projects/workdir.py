"""Materialize a CLI-style work dir from DB + storage for FFmpeg assembly."""

from pathlib import Path

from django.conf import settings

from apps.projects.models import Project, Scene
from apps.projects.utils import build_shot_plan, get_work_dir
from pipeline.schema import ShotPlan


def _download_field(field_file, dest: Path) -> None:
    if not field_file:
        raise FileNotFoundError("missing storage file")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with field_file.open("rb") as src:
        dest.write_bytes(src.read())


def materialize_work_dir(project: Project) -> tuple[Path, ShotPlan]:
    """Download scene assets into MEDIA_ROOT layout expected by pipeline.assemble."""
    work_dir = get_work_dir(project)
    images_dir = work_dir / "images"
    audio_dir = work_dir / "audio"
    video_dir = work_dir / "video"
    for d in (images_dir, audio_dir, video_dir):
        d.mkdir(parents=True, exist_ok=True)

    plan = build_shot_plan(project)
    (work_dir / "shot_plan.json").write_text(plan.model_dump_json(indent=2))

    for scene in Scene.objects.filter(project=project).order_by("index"):
        idx = scene.index
        if scene.media_path:
            _download_field(scene.media_path, images_dir / f"scene_{idx:02d}.png")
        if scene.audio_path:
            _download_field(scene.audio_path, audio_dir / f"scene_{idx:02d}.mp3")
        if scene.words_path:
            _download_field(scene.words_path, audio_dir / f"scene_{idx:02d}.words.json")

    return work_dir, plan


def music_root() -> Path:
    return Path(settings.BASE_DIR).parent / "music"
