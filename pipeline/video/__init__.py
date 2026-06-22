"""Stage 2.5 (optional): animate scene stills into short video clips.

Fail-soft by design: a scene whose clip fails (or times out) just stays a
still — assembly falls back to Ken Burns for any scene without a
video/scene_NN.mp4. Already-existing clips are skipped, so re-running only
retries the missing ones.
"""
import time
from pathlib import Path
from typing import List, Optional

from ..schema import ShotPlan, Scene
from .base import VideoProvider
from .wan import WanProvider

PROVIDERS: List[VideoProvider] = [
    WanProvider(),
]

POLL_INTERVAL = 15
BATCH_TIMEOUT = 30 * 60


def get_provider(name: Optional[str] = None, quality: str = "flash") -> VideoProvider:
    """Pick a video provider.

    quality only affects Wan (flash/turbo/plus); Kling ignores it (always pro mode).
    """
    if name:
        for p in PROVIDERS:
            if p.name == name:
                if not p.available():
                    raise RuntimeError(
                        f"video backend '{name}' is not configured (missing API key?)")
                if isinstance(p, WanProvider):
                    return WanProvider(quality=quality)
                return p
        raise RuntimeError(
            f"unknown video backend '{name}' — choices: {', '.join(p.name for p in PROVIDERS)}")
    for p in PROVIDERS:
        if p.available():
            if isinstance(p, WanProvider):
                return WanProvider(quality=quality)
            return p
    raise RuntimeError(
        "no video backend configured — set DASHSCOPE_API_KEY for Wan or "
        "KLING_ACCESS_KEY + KLING_ACCESS_SECRET for Kling")


def _motion_prompt(plan: ShotPlan, scene: Scene) -> str:
    if scene.motion:
        return f"{plan.expand(scene.motion, scene_outfit=scene.outfit)} Stay on this single shot, no scene changes."
    return (f"{plan.expand(scene.media_prompt, scene_outfit=scene.outfit)} Gentle cinematic camera motion and subtle "
            f"natural movement. Stay on this single shot, no scene changes.")


def animate_scenes(plan: ShotPlan, images_dir: Path, out_dir: Path,
                   backend: Optional[str] = None,
                   quality: str = "flash") -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    provider = get_provider(backend, quality=quality)
    print(f"  animate: backend = {provider.name}"
          + (f" ({quality})" if isinstance(provider, WanProvider) else ""))

    todo = []
    for i, scene in enumerate(plan.scenes):
        if (out_dir / f"scene_{i:02d}.mp4").exists():
            print(f"  animate: scene {i + 1} clip exists, skipping")
        elif not scene.animate:
            print(f"  animate: scene {i + 1} skipped (animate=false — uses Ken Burns)")
        else:
            todo.append(i)
    if todo:
        if hasattr(provider, "submit"):
            _animate_batch(provider, plan, images_dir, out_dir, todo)
        else:
            _animate_sequential(provider, plan, images_dir, out_dir, todo)
    return sorted(out_dir.glob("scene_*.mp4"))


def _animate_batch(provider, plan: ShotPlan, images_dir: Path, out_dir: Path,
                   todo: List[int]) -> None:
    """Submit every scene as a server-side task, then poll them all concurrently."""
    pending = {}
    for i in todo:
        try:
            task_id = provider.submit(_motion_prompt(plan, plan.scenes[i]),
                                      images_dir / f"scene_{i:02d}.png")
            pending[i] = task_id
            print(f"  animate: scene {i + 1} submitted")
        except Exception as e:
            print(f"  animate: scene {i + 1} submit failed ({e}) — stays a still")

    deadline = time.time() + BATCH_TIMEOUT
    while pending and time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        for i, task_id in list(pending.items()):
            try:
                url = provider.poll(task_id)
            except Exception as e:
                print(f"  animate: scene {i + 1} failed ({e}) — stays a still")
                del pending[i]
                continue
            if url:
                provider.download(url, out_dir / f"scene_{i:02d}.mp4")
                print(f"  animate: scene {i + 1} done ({len(pending) - 1} still rendering)")
                del pending[i]
    for i in pending:
        print(f"  animate: scene {i + 1} timed out — stays a still")


# Currently unreachable (Wan implements submit/poll) — kept intentionally as the
# documented path for future providers without async task support (see base.py).
def _animate_sequential(provider, plan: ShotPlan, images_dir: Path, out_dir: Path,
                        todo: List[int]) -> None:
    for i in todo:
        try:
            provider.generate(_motion_prompt(plan, plan.scenes[i]),
                              images_dir / f"scene_{i:02d}.png",
                              out_dir / f"scene_{i:02d}.mp4")
            print(f"  animate: scene {i + 1}/{len(plan.scenes)}")
        except Exception as e:
            print(f"  animate: scene {i + 1} failed ({e}) — stays a still")
