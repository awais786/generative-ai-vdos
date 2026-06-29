"""Stage 3: per-scene voiceover via edge-tts (free Microsoft neural voices).

edge-tts streams WordBoundary events with timestamps, so caption timing comes
for free — no whisper pass needed.
"""
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import List, Optional

import edge_tts
from edge_tts.exceptions import NoAudioReceived

from .schema import ShotPlan

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "en-US-AndrewNeural"
_VOICE_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}-.+Neural$")

# Unicode punctuation that occasionally causes edge-tts to return no audio.
_SMART_PUNCT = str.maketrans({
    "\u2019": "'", "\u2018": "'",
    "\u201c": '"', "\u201d": '"',
    "\u2014": "-", "\u2013": "-",
})


def normalize_tts_text(text: str) -> str:
    """Strip and normalize narration before sending to edge-tts."""
    normalized = (text or "").strip().translate(_SMART_PUNCT)
    if not normalized:
        raise ValueError("Narration is empty")
    return normalized


def resolve_voice(scene_voice: str | None, default_voice: str) -> str:
    """Pick a valid edge-tts voice id, falling back to the project narrator."""
    for candidate in (scene_voice, default_voice, DEFAULT_VOICE):
        if candidate and _VOICE_RE.match(candidate.strip()):
            return candidate.strip()
    return DEFAULT_VOICE


async def synth_scene(text: str, voice: str, mp3_path: Path, words_path: Path) -> None:
    narration = normalize_tts_text(text)
    voice_id = resolve_voice(voice, DEFAULT_VOICE)
    communicate = edge_tts.Communicate(narration, voice_id, boundary="WordBoundary")
    words = []
    with open(mp3_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({
                    "text": chunk["text"],
                    "start": chunk["offset"] / 1e7,      # 100ns ticks -> seconds
                    "duration": chunk["duration"] / 1e7,
                })
    words_path.write_text(json.dumps(words, indent=2))


async def synth_scene_with_retry(
    text: str,
    voice: str,
    mp3_path: Path,
    words_path: Path,
    *,
    max_attempts: int = 4,
    base_delay: float = 1.5,
) -> None:
    """Retry on transient edge-tts failures (rate limits, empty responses)."""
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            await synth_scene(text, voice, mp3_path, words_path)
            return
        except (NoAudioReceived, ConnectionError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 >= max_attempts:
                break
            delay = base_delay * (attempt + 1)
            logger.warning(
                "voice: retry %s/%s after %r (sleep %.1fs)",
                attempt + 2, max_attempts, exc, delay,
            )
            await asyncio.sleep(delay)
    if last_error is None:
        raise RuntimeError("max_attempts must be >= 1")
    raise last_error


def synth_scene_sync(text: str, voice: str, mp3_path: Path, words_path: Path) -> None:
    """Blocking wrapper for web workers and Celery tasks."""
    asyncio.run(synth_scene_with_retry(text, voice, mp3_path, words_path))


def generate_voiceover(
    plan: ShotPlan,
    out_dir: Path,
    voice: Optional[str] = None,
    scene_indices: Optional[List[int]] = None,
) -> List[Path]:
    """Writes scene_NN.mp3 + scene_NN.words.json per scene. Returns mp3 paths."""
    default_voice = resolve_voice(voice, DEFAULT_VOICE)
    out_dir.mkdir(parents=True, exist_ok=True)
    indices = (
        list(scene_indices)
        if scene_indices is not None
        else list(range(len(plan.scenes)))
    )
    invalid = [i for i in indices if i < 0 or i >= len(plan.scenes)]
    if invalid:
        raise ValueError(f"Invalid scene indices: {invalid}")

    mp3_paths: List[Path] = []

    async def run_all():
        for i in indices:
            scene = plan.scenes[i]
            prefix = out_dir / f"scene_{i:02d}"
            mp3 = prefix.with_suffix(".mp3")
            words = Path(f"{prefix}.words.json")
            scene_voice = resolve_voice(scene.voice, default_voice)
            await synth_scene_with_retry(scene.narration, scene_voice, mp3, words)
            mp3_paths.append(mp3)
            logger.info(
                "voice: scene %s/%s (%s)",
                i + 1, len(plan.scenes), scene_voice,
            )
            # Brief pause between scenes to avoid edge-tts rate limits.
            if i != indices[-1]:
                await asyncio.sleep(0.4)

    asyncio.run(run_all())
    return mp3_paths


def main() -> None:
    """CLI: python -m pipeline.voiceover output/<slug> [--voice NAME]"""
    import argparse

    from .env import load_env
    load_env()
    parser = argparse.ArgumentParser(description="Generate voiceover for an existing work dir")
    parser.add_argument("work_dir", nargs="?", default=None,
                        help="output/<name> dir (default: the most recent one)")
    parser.add_argument("--voice", default=DEFAULT_VOICE,
                        help="Narrator voice; per-scene 'voice' in shot_plan.json overrides")
    args = parser.parse_args()

    from .run import latest_work_dir
    work_dir = Path(args.work_dir) if args.work_dir else latest_work_dir()
    print(f"video folder: {work_dir}")
    plan = ShotPlan.model_validate_json((work_dir / "shot_plan.json").read_text())
    generate_voiceover(plan, work_dir / "audio", voice=args.voice)


if __name__ == "__main__":
    main()
