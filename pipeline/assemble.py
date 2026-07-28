"""Stage 4: FFmpeg assembly — Ken Burns over stills, burned captions, music bed."""
import json
import logging
import random
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from .schema import ShotPlan

logger = logging.getLogger(__name__)

FPS = 30

# Ken Burns motion patterns — cycles through each scene in order.
# Each entry: (zoom_expr, x_expr, y_expr)
# `on` = current output frame number; `iw`/`ih`/`zoom` = ffmpeg zoompan variables.
_KB_MODES = [
    # zoom in from centre
    ("1+0.0008*on",    "iw/2-(iw/zoom/2)",       "ih/2-(ih/zoom/2)"),
    # zoom out from centre
    ("1.20-0.0008*on", "iw/2-(iw/zoom/2)",       "ih/2-(ih/zoom/2)"),
    # slow pan left → right
    ("1.08",           "on*0.8",                  "ih/2-(ih/zoom/2)"),
    # slow pan right → left
    ("1.08",           "(iw-iw/zoom)-on*0.8",    "ih/2-(ih/zoom/2)"),
    # zoom in anchored to top-left corner
    ("1+0.0008*on",    "0",                       "0"),
    # zoom in anchored to bottom-right corner
    ("1+0.0008*on",    "iw-iw/zoom",              "ih-ih/zoom"),
]

# First present font is used for on_screen_text overlays.
_FONT = next((f for f in [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
] if Path(f).exists()), None)


def _overlay_filter(text: Optional[str]) -> str:
    """drawtext filter chunk for the scene's on_screen_text (top center), or ''."""
    if not text or _FONT is None:
        return ""
    # drawtext's filtergraph parser also chokes on newlines, [], commas and
    # semicolons (filtergraph separators) — collapse newlines to spaces and
    # escape the rest (backslash first, so we don't double it).
    esc = (text.replace("\\", "\\\\")
               .replace("\n", " ").replace("\r", " ")
               .replace("'", "’")
               .replace(":", "\\:").replace("%", "\\%")
               .replace("[", "\\[").replace("]", "\\]")
               .replace(",", "\\,").replace(";", "\\;"))
    return (f",drawtext=fontfile='{_FONT}':text='{esc}':fontsize=58:fontcolor=white:"
            f"borderw=3:bordercolor=black@0.8:x=(w-text_w)/2:y=70")


def _run(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 15 * 60,
         tag: str = "ffmpeg") -> float:
    # timeout= so a deadlocked ffmpeg raises TimeoutExpired instead of blocking
    # in a C call — otherwise Celery's soft-time-limit signal can't be delivered
    # and the worker child eventually gets SIGKILL'd without cleanup.
    # -benchmark makes ffmpeg print a `bench: utime=… stime=… rtime=…` line to
    # stderr so we can tell CPU-bound from I/O-bound at a glance.
    if cmd and cmd[0] == "ffmpeg":
        cmd = [cmd[0], "-benchmark", *cmd[1:]]
    t0 = time.perf_counter()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        logger.error("assemble.timing tag=%s dt=%.2fs status=timeout",
                     tag, time.perf_counter() - t0)
        raise RuntimeError(f"ffmpeg timed out after {timeout}s:\n{' '.join(cmd)}") from exc
    dt = time.perf_counter() - t0
    bench = next((ln for ln in result.stderr.splitlines() if ln.startswith("bench:")), "")
    if result.returncode != 0:
        logger.error("assemble.timing tag=%s dt=%.2fs status=fail %s", tag, dt, bench)
        raise RuntimeError(f"ffmpeg failed:\n{' '.join(cmd)}\n{result.stderr[-2000:]}")
    logger.info("assemble.timing tag=%s dt=%.2fs %s", tag, dt, bench)
    return dt


def _duration(media: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(media)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_srt(audio_dir: Path, scene_durations: List[float], srt_path: Path) -> None:
    """Chunk edge-tts word timings into ~4-word captions with global offsets."""
    entries = []
    offset = 0.0
    for i, dur in enumerate(scene_durations):
        words = json.loads((audio_dir / f"scene_{i:02d}.words.json").read_text())
        chunk: List[dict] = []
        for w in words:
            chunk.append(w)
            if len(chunk) >= 4:
                entries.append((offset + chunk[0]["start"],
                                offset + chunk[-1]["start"] + chunk[-1]["duration"],
                                " ".join(c["text"] for c in chunk)))
                chunk = []
        if chunk:
            entries.append((offset + chunk[0]["start"],
                            offset + chunk[-1]["start"] + chunk[-1]["duration"],
                            " ".join(c["text"] for c in chunk)))
        offset += dur

    lines = []
    for n, (start, end, text) in enumerate(entries, 1):
        lines.append(f"{n}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n")
    srt_path.write_text("\n".join(lines))


def assemble(plan: ShotPlan, work_dir: Path, music_path: Optional[Path] = None) -> Path:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found — install it with: brew install ffmpeg")

    images_dir = work_dir / "images"
    video_dir = work_dir / "video"
    audio_dir = work_dir / "audio"
    clips_dir = work_dir / "clips"
    clips_dir.mkdir(exist_ok=True)

    missing_audio = [i for i in range(len(plan.scenes))
                     if not (audio_dir / f"scene_{i:02d}.mp3").is_file()]
    if missing_audio:
        raise SystemExit(
            f"no voiceover for scene(s) {missing_audio} in {audio_dir} — run:\n"
            f"  python -m pipeline.voiceover {work_dir}")
    missing_images = [i for i in range(len(plan.scenes))
                      if not (images_dir / f"scene_{i:02d}.png").is_file()
                      and not (video_dir / f"scene_{i:02d}.mp4").is_file()]
    if missing_images:
        raise SystemExit(
            f"no image or clip for scene(s) {missing_images} — run:\n"
            f"  python -m pipeline.images {work_dir}")

    # Per-scene clip + that scene's voiceover. An animated clip from the
    # optional animate stage (video/scene_NN.mp4) is preferred — looped and
    # trimmed to the narration; otherwise Ken Burns over the still image.
    t_total = time.perf_counter()
    scene_durations = []
    clip_paths = []
    scenes_wall = 0.0
    for i in range(len(plan.scenes)):
        img = images_dir / f"scene_{i:02d}.png"
        vid = video_dir / f"scene_{i:02d}.mp4"
        mp3 = audio_dir / f"scene_{i:02d}.mp3"
        clip = clips_dir / f"scene_{i:02d}.mp4"
        dur = _duration(mp3) + 0.3  # small breath between scenes
        overlay = _overlay_filter(plan.scenes[i].on_screen_text)
        if vid.exists():
            scenes_wall += _run([
                "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(vid), "-i", str(mp3),
                "-filter_complex",
                f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,"
                f"crop=1920:1080,fps={FPS}{overlay}[v];[1:a]apad[a]",
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "44100",
                "-t", f"{dur:.3f}", str(clip),
            ], tag=f"scene[{i:02d}]:animated")
            source = "animated"
        else:
            frames = int(dur * FPS)
            z_expr, x_expr, y_expr = _KB_MODES[i % len(_KB_MODES)]
            # 0.3 s fade-in/out; cap at 12% of clip so short scenes don't over-fade
            fade_d = min(0.30, dur * 0.12)
            fade_in  = f",fade=t=in:st=0:d={fade_d:.2f}"
            fade_out = f",fade=t=out:st={max(0.0, dur - fade_d):.3f}:d={fade_d:.2f}"
            scenes_wall += _run([
                "ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS), "-i", str(img),
                "-i", str(mp3),
                "-filter_complex",
                f"[0:v]scale=2304:1296,zoompan=z='{z_expr}':d={frames}:"
                f"x='{x_expr}':y='{y_expr}':s=1920x1080:fps={FPS}"
                f"{overlay}{fade_in}{fade_out}[v];"
                f"[1:a]apad[a]",
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "44100",
                "-t", f"{dur:.3f}", str(clip),
            ], tag=f"scene[{i:02d}]:kb")
            source = f"ken burns #{i % len(_KB_MODES) + 1}"
        scene_durations.append(dur)
        clip_paths.append(clip)
        print(f"  assemble: scene clip {i + 1}/{len(plan.scenes)} ({source})")

    # Concat all scene clips.
    concat_list = work_dir / "concat.txt"
    concat_list.write_text("\n".join(f"file '{p.resolve()}'" for p in clip_paths))
    raw = work_dir / "video_raw.mp4"
    concat_wall = _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                        "-c", "copy", str(raw)], tag="concat")

    # Captions from edge-tts word timings.
    srt = work_dir / "captions.srt"
    t_srt = time.perf_counter()
    _build_srt(audio_dir, scene_durations, srt)
    srt_wall = time.perf_counter() - t_srt

    # Final pass: burn captions, mix music under the voiceover.
    final = work_dir / "final.mp4"
    sub_filter = (f"subtitles={srt.name}:force_style="
                  f"'FontSize=18,Bold=1,Outline=2,MarginV=40'")
    if music_path is not None:
        final_wall = _run([
            "ffmpeg", "-y", "-i", str(raw.resolve()), "-stream_loop", "-1", "-i", str(music_path.resolve()),
            "-filter_complex",
            f"[0:v]{sub_filter}[v];[1:a]volume=0.12[m];"
            f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(final.resolve()),
        ], cwd=work_dir, tag="final:music")
    else:
        final_wall = _run(["ffmpeg", "-y", "-i", str(raw.resolve()), "-vf", sub_filter,
              "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
              "-c:a", "copy", str(final.resolve())], cwd=work_dir, tag="final:nomusic")

    logger.info(
        "assemble.summary scenes=%d total=%.2fs scenes_sum=%.2fs "
        "concat=%.2fs srt=%.2fs final=%.2fs",
        len(plan.scenes), time.perf_counter() - t_total,
        scenes_wall, concat_wall, srt_wall, final_wall,
    )
    return final


def pick_music(music_root: Path, mood: str) -> Optional[Path]:
    """Pick a random track from music/<mood>/ (fall back to any track)."""
    if not music_root.exists():
        return None
    mood_dir = music_root / mood
    pool = list(mood_dir.glob("*.mp3")) if mood_dir.exists() else []
    if not pool:
        pool = list(music_root.rglob("*.mp3"))
    return random.choice(pool) if pool else None


def main() -> None:
    """CLI: python -m pipeline.assemble output/<slug> [--music-dir music]"""
    import argparse

    parser = argparse.ArgumentParser(description="Assemble final.mp4 for an existing work dir")
    parser.add_argument("work_dir", nargs="?", default=None,
                        help="output/<name> dir (default: the most recent one)")
    parser.add_argument("--music-dir", default="music",
                        help="Folder to pick a mood-matching track from")
    parser.add_argument("--music", default=None,
                        help="Exact music file to use (overrides --music-dir and mood)")
    args = parser.parse_args()

    from .run import latest_work_dir
    work_dir = Path(args.work_dir) if args.work_dir else latest_work_dir()
    print(f"video folder: {work_dir}")
    plan = ShotPlan.model_validate_json((work_dir / "shot_plan.json").read_text())
    if args.music:
        music = Path(args.music)
        if not music.is_file():
            import sys
            sys.exit(f"music file not found: {music}")
    else:
        music = pick_music(Path(args.music_dir), plan.music_mood)
    print(f"  music: {music if music else 'none'}")
    final = assemble(plan, work_dir, music_path=music)
    print(f"Done: {final}")


if __name__ == "__main__":
    main()
