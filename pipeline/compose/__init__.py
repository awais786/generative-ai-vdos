"""Stage 2.75: composition scenes via Remotion.

A scene with a `compose` spec is a text/motion card (title, quote) rather than a
generated image. It renders straight into video/scene_NN.mp4 — the same slot the
FFmpeg assembler already prefers over a Ken Burns still — so the rest of the
pipeline (concat, captions, music) is unchanged.

Runs AFTER the voice stage so each card can be sized to its narration length.
Cost: $0 (local headless render), like the animate stage's Ken Burns fallback.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .. import report
from ..schema import ShotPlan
from ..styles import load_style

FPS = 30
BREATH = 0.3  # match assemble.py: a small breath added to each scene's duration

# Remotion composition id per template name (see remotion/src/Root.tsx).
_COMPOSITION_ID = {
    "title_card": "TitleCard",
    "quote": "Quote",
    "lower_third": "LowerThird",
    "outro": "Outro",
}

# Fallback durations (seconds) when a scene has no narration audio yet.
_DEFAULT_SECONDS = {"title_card": 4.0, "quote": 6.0, "lower_third": 4.0, "outro": 4.0}

# Keep in sync with remotion/src/theme.ts MOOD_PALETTES.
MOOD_PALETTES: dict[str, dict[str, str]] = {
    "calm": {"bg1": "#0d1b2a", "bg2": "#2a4a5c", "fg": "#eaf4f4", "accent": "#8fd0c8", "glow": "rgba(143,208,200,0.22)"},
    "upbeat": {"bg1": "#231533", "bg2": "#7a2f6a", "fg": "#fdeff6", "accent": "#ffb84d", "glow": "rgba(255,184,77,0.26)"},
    "dramatic": {"bg1": "#0b0b12", "bg2": "#3a1f22", "fg": "#f4ead6", "accent": "#e0714a", "glow": "rgba(224,113,74,0.24)"},
    "mysterious": {"bg1": "#0a0f1e", "bg2": "#241a3a", "fg": "#e8e6f4", "accent": "#a88fe0", "glow": "rgba(168,143,224,0.22)"},
    "inspiring": {"bg1": "#0f0b1e", "bg2": "#4a2f52", "fg": "#f6ecd6", "accent": "#f0b563", "glow": "rgba(255,214,140,0.28)"},
}
_DEFAULT_PALETTE = MOOD_PALETTES["inspiring"]


def _remotion_dir() -> Path:
    # pipeline/compose/__init__.py -> parents[2] == repo root
    return Path(__file__).resolve().parents[2] / "remotion"


def _audio_duration(mp3: Path) -> Optional[float]:
    if not mp3.is_file():
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(mp3)],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return None
    try:
        return float(out.stdout.strip())
    except (ValueError, AttributeError):
        return None


def _palette_for(plan: ShotPlan, work_dir: Path | None = None) -> dict[str, str]:
    """The card palette, preferring the video's own style.

    Falls back to the music-mood table per key, so a work dir with no style.json
    behaves exactly as before and a partially hand-edited palette cannot produce
    an unreadable card.
    """
    base = MOOD_PALETTES.get((plan.music_mood or "").strip().lower(), _DEFAULT_PALETTE)
    if work_dir is None:
        return base
    override = load_style(work_dir).get("palette")
    if not isinstance(override, dict):
        return base
    return {**base, **{k: v for k, v in override.items() if v}}


def _props_for(scene_compose, palette: dict[str, str], frames: int) -> dict:
    template = scene_compose.template
    if template == "quote":
        attribution = scene_compose.attribution
        if attribution and not attribution.strip().startswith("—"):
            attribution = f"— {attribution.strip()}"
        return {
            "heading": scene_compose.heading,
            "attribution": attribution,
            "palette": palette,
            "durationInFrames": frames,
        }
    # title_card / lower_third / outro all take heading + optional subheading.
    return {
        "heading": scene_compose.heading,
        "subheading": scene_compose.subheading,
        "palette": palette,
        "durationInFrames": frames,
    }


def render_compositions(plan: ShotPlan, work_dir: Path) -> list[Path]:
    """Render every compose scene in `plan` to work_dir/video/scene_NN.mp4."""
    compose_scenes = [(i, s) for i, s in enumerate(plan.scenes) if s.compose]
    if not compose_scenes:
        return []

    if shutil.which("npx") is None:
        raise RuntimeError(
            "npx not found — the composition track needs Node.js >= 18. "
            "Install Node (https://nodejs.org), then: cd remotion && npm install")

    remotion_dir = _remotion_dir()
    if not (remotion_dir / "node_modules").is_dir():
        raise RuntimeError(
            f"Remotion deps not installed. Run:\n  cd {remotion_dir} && npm install")

    video_dir = work_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = work_dir / "audio"
    props_dir = work_dir / "compose"
    props_dir.mkdir(parents=True, exist_ok=True)

    print(report.row("compose", "remotion",
                     f"local render, free, {report.plural(len(compose_scenes), 'card scene')}"))
    # One read of the sidecar, shared by the palette and the line that reports
    # where it came from — this used to load style.json twice and re-import
    # load_style locally, shadowing the module-level import.
    styled_palette = bool(load_style(work_dir).get("palette")) if work_dir else False
    palette = _palette_for(plan, work_dir)
    # Report where the palette actually came from. The style sidecar wins, and
    # when it exists the music mood is irrelevant — so the pre-style message
    # ("no palette for mood X") would be actively misleading there. Only warn
    # about the mood when the mood is genuinely what got used.
    if styled_palette:
        print(report.note_line("palette: from the video's style"))
    elif (plan.music_mood or "").strip().lower() not in MOOD_PALETTES:
        print(report.note_line(
            f"palette: default (no style set, and no palette for mood "
            f"'{plan.music_mood}')"))
    entry = "src/index.ts"
    rendered: list[Path] = []

    for i, scene in compose_scenes:
        template = scene.compose.template
        comp_id = _COMPOSITION_ID[template]
        dur = _audio_duration(audio_dir / f"scene_{i:02d}.mp3")
        seconds = (dur + BREATH) if dur else _DEFAULT_SECONDS.get(template, 5.0)
        frames = max(30, round(seconds * FPS))

        props = _props_for(scene.compose, palette, frames)
        props_file = props_dir / f"scene_{i:02d}.props.json"
        props_file.write_text(json.dumps(props, indent=2))

        out_path = (video_dir / f"scene_{i:02d}.mp4").resolve()
        cmd = [
            "npx", "--yes", "remotion", "render", entry, comp_id,
            str(out_path), f"--props={props_file.resolve()}",
        ]
        print(f"  compose: scene {i + 1}/{len(plan.scenes)} "
              f"({template}, {seconds:.1f}s) -> {out_path.name}")
        try:
            result = subprocess.run(cmd, cwd=str(remotion_dir),
                                    capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"remotion render timed out for scene {i} ({template}) after "
                f"{e.timeout:.0f}s") from e
        if result.returncode != 0:
            raise RuntimeError(
                f"remotion render failed for scene {i} ({template}):\n"
                f"{result.stderr[-2000:]}")
        if not out_path.is_file():
            raise RuntimeError(
                f"remotion render exited 0 but {out_path} is missing")
        rendered.append(out_path)

    return rendered
