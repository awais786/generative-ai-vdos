"""Materialize a CLI-style work dir from DB + storage for FFmpeg assembly."""

import logging
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.conf import settings

from apps.projects.models import Project
from apps.projects.utils import build_shot_plan, get_work_dir
from pipeline.schema import ShotPlan

logger = logging.getLogger(__name__)


def _local_source_path(field_file) -> Path | None:
    try:
        return Path(field_file.path).resolve()
    except (NotImplementedError, ValueError, AttributeError):
        return None


def _download_field(field_file, dest: Path) -> float:
    """Copy a storage file to `dest`. Returns bytes actually copied (0 for in-place)."""
    if not field_file:
        raise FileNotFoundError("missing storage file")
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_path = _local_source_path(field_file)
    dest = dest.resolve()
    if src_path is not None and src_path == dest:
        if not src_path.is_file() or src_path.stat().st_size == 0:
            raise FileNotFoundError(f"empty or missing file: {dest}")
        return 0
    with field_file.open("rb") as src, dest.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    size = dest.stat().st_size
    if size == 0:
        raise FileNotFoundError(f"empty file after download: {dest}")
    return size


def _timed_download(job: tuple) -> int:
    """Run one download and log its wall time — parallel-safe replacement for
    the old per-scene loop timing."""
    field_file, dest = job
    t0 = time.perf_counter()
    size = _download_field(field_file, dest)
    logger.info("materialize.download file=%s dt=%.2fs bytes=%d",
                dest.name, time.perf_counter() - t0, size)
    return size


def materialize_work_dir(project: Project) -> tuple[Path, ShotPlan]:
    """Download scene assets into a staging layout expected by pipeline.assemble.

    Uses a ``_assemble`` subdir so we never open storage paths for write in place
    (FileSystemStorage stores images at ``{work_dir}/images/…`` — copying a file
    onto itself truncates it to zero bytes).
    """
    t_total = time.perf_counter()
    work_dir = get_work_dir(project) / "_assemble"
    images_dir = work_dir / "images"
    audio_dir = work_dir / "audio"
    video_dir = work_dir / "video"
    for d in (images_dir, audio_dir, video_dir):
        d.mkdir(parents=True, exist_ok=True)
    (work_dir / ".active").write_text(str(time.time()))

    plan = build_shot_plan(project)
    (work_dir / "shot_plan.json").write_text(plan.model_dump_json(indent=2))

    # Validate + collect every download in one pass, then fan out across a
    # thread pool. S3 GETs are latency-bound (~30-50ms round trip each), so
    # sequential fetches for 25+ files add up fast — parallelising cuts the
    # download phase from ~40s to <10s in prod.
    scenes = list(project.scenes.order_by("index"))
    has_compose = any(s.compose for s in scenes)
    jobs: list[tuple[object, Path]] = []
    for scene in scenes:
        prefix = f"scene_{scene.index:02d}"
        if not scene.audio_path:
            raise FileNotFoundError(f"scene {scene.index} is missing audio_path")
        jobs.append((scene.audio_path, audio_dir / f"{prefix}.mp3"))
        if scene.words_path:
            jobs.append((scene.words_path, audio_dir / f"{prefix}.words.json"))
        # Composition scenes have no image/video asset — Remotion renders
        # video/scene_NN.mp4 from the staged audio below.
        if scene.compose:
            continue
        if not scene.media_path:
            raise FileNotFoundError(f"scene {scene.index} is missing media_path")
        ext = Path(scene.media_path.name).suffix.lower()
        if ext == ".mp4":
            jobs.append((scene.media_path, video_dir / f"{prefix}.mp4"))
        else:
            jobs.append((scene.media_path, images_dir / f"{prefix}.png"))

    bytes_dl = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for size in ex.map(_timed_download, jobs):
            bytes_dl += size

    logger.info(
        "materialize.summary scenes=%d files=%d bytes=%d dt=%.2fs",
        len(scenes), len(jobs), bytes_dl, time.perf_counter() - t_total,
    )

    # Render composition cards (Remotion) into video/scene_NN.mp4 from the staged
    # audio — assemble() then prefers these clips exactly like an animated scene.
    # Requires Node + the repo's remotion/ project on this worker host.
    if has_compose:
        t_compose = time.perf_counter()
        from pipeline.compose import render_compositions
        render_compositions(plan, work_dir)
        logger.info("materialize.compose dt=%.2fs", time.perf_counter() - t_compose)

    return work_dir, plan


def music_root() -> Path:
    return Path(settings.BASE_DIR).parent / "music"


# task time_limit is 25 min; 5 min grace covers slow teardown
_ASSEMBLE_STALE_AFTER = 30 * 60


def assemble_is_live(assemble_dir: Path) -> bool:
    """Return True if _assemble/ has a fresh .active sentinel (assembly in flight)."""
    sentinel = assemble_dir / ".active"
    if not sentinel.exists():
        return False
    try:
        return time.time() - float(sentinel.read_text()) < _ASSEMBLE_STALE_AFTER
    except (ValueError, OSError):
        return False
