"""Stage 4: FFmpeg assembly — Ken Burns over stills, burned captions, music bed."""
import json
import logging
import random
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import report
from .schema import ShotPlan
from .styles import load_style

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


def _hex_to_ass(hex_colour: str) -> str:
    """#rrggbb -> &HAABBGGRR for libass force_style.

    libass stores colours blue-first with alpha leading. Handing it an #rrggbb
    string produces a wrong-but-plausible colour and no error, so every colour
    reaching force_style must come through here.
    """
    h = hex_colour.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _hex_to_drawtext(hex_colour: str) -> str:
    """#rrggbb -> 0xrrggbb for ffmpeg drawtext fontcolor."""
    return "0x" + hex_colour.lstrip("#").lower()


def _flatten(text: Optional[str]) -> str:
    """Lowercase, punctuation to spaces, whitespace collapsed — so that
    'everyone HAS a WAVE coming...' and 'Everyone has a wave coming' compare equal."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def _restates(text: Optional[str], narration: Optional[str]) -> bool:
    """True when `text` is a verbatim phrase already spoken in `narration`.

    The subtitles are built from the narration, so anything this returns True
    for would render twice on the same frame. Deliberately conservative:

    - Contiguous phrase only. Paraphrase ('Meet the Professor' against "Meet
      our professor") never fires — catching it needs judgement we don't have.
    - Under 3 words never fires. This is what protects the short labels that
      repeat the narration on purpose: in a listicle, 'ARGENTINA' over
      "Argentina — champions by destiny" IS the visual design.
    - 'subscribe' never fires. CTA copy repeats the narration on purpose.
    """
    flat = _flatten(text)
    spoken = _flatten(narration)
    if not flat or not spoken:
        return False
    if len(flat.split()) < 3:
        return False
    if "subscribe" in flat:
        return False
    return f" {flat} " in f" {spoken} "


def _overlay_filter(text: Optional[str], style: dict | None = None) -> str:
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
    text_cfg = (style or {}).get("text") or {}
    palette = (style or {}).get("palette") or {}
    size = text_cfg.get("overlay_size", 58)
    border = text_cfg.get("overlay_border", 3)
    colour = _hex_to_drawtext(palette["fg"]) if palette.get("fg") else "white"
    return (f",drawtext=fontfile='{_FONT}':text='{esc}':fontsize={size}:"
            f"fontcolor={colour}:borderw={border}:bordercolor=black@0.8:"
            f"x=(w-text_w)/2:y=70")


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


def _build_scene_srt(words_json: Path, srt_path: Path) -> None:
    """Write per-scene SRT (local 0-based offsets) from edge-tts word timings.
    No-op if the words file is absent or empty."""
    if not words_json.is_file():
        return
    words = json.loads(words_json.read_text())
    if not words:
        return
    entries = []
    chunk: List[dict] = []
    for w in words:
        chunk.append(w)
        if len(chunk) >= 4:
            entries.append((chunk[0]["start"],
                            chunk[-1]["start"] + chunk[-1]["duration"],
                            " ".join(c["text"] for c in chunk)))
            chunk = []
    if chunk:
        entries.append((chunk[0]["start"],
                        chunk[-1]["start"] + chunk[-1]["duration"],
                        " ".join(c["text"] for c in chunk)))
    lines = []
    for n, (start, end, text) in enumerate(entries, 1):
        lines.append(f"{n}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n")
    srt_path.write_text("\n".join(lines))


def _subtitle_filter(rel_path: str, srt_path: Path, style: dict | None = None) -> str:
    """subtitles= chunk (path relative to ffmpeg cwd), or '' if no SRT."""
    if not srt_path.is_file() or srt_path.stat().st_size == 0:
        return ""
    text = (style or {}).get("text") or {}
    palette = (style or {}).get("palette") or {}
    size = text.get("caption_size", 18)
    outline = text.get("caption_outline", 2)
    colour = f",PrimaryColour={_hex_to_ass(palette['fg'])}" if palette.get("fg") else ""
    return (f",subtitles={rel_path}:force_style="
            f"'FontSize={size},Bold=1,Outline={outline},MarginV=40{colour}'")


def assemble(plan: ShotPlan, work_dir: Path, music_path: Optional[Path] = None) -> Path:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found — install it with: brew install ffmpeg")

    # The per-scene ffmpeg calls run with cwd=work_dir so libass resolves the
    # SRT from a clean relative path. That makes every OTHER path passed to
    # ffmpeg relative to work_dir too, so a relative work_dir sends ffmpeg
    # looking for work_dir/work_dir/images/... Resolve here, at the boundary,
    # rather than in main(): the celery path already passes an absolute path,
    # and resolving once protects every caller.
    work_dir = Path(work_dir).resolve()

    images_dir = work_dir / "images"
    video_dir = work_dir / "video"
    audio_dir = work_dir / "audio"
    clips_dir = work_dir / "clips"
    clips_dir.mkdir(exist_ok=True)
    # One read for the whole render: captions and overlays take their size and
    # colour from the same style the images and compose cards used.
    style = load_style(work_dir)

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

    # Per-scene clip + that scene's voiceover. Captions are burned in *here*
    # (per-scene SRT with local timings) so the final pass can stream-copy
    # instead of doing a full re-encode of the concatenated video.
    t_total = time.perf_counter()
    clip_paths = []
    scenes_wall = 0.0
    srt_wall = 0.0
    for i in range(len(plan.scenes)):
        img = images_dir / f"scene_{i:02d}.png"
        vid = video_dir / f"scene_{i:02d}.mp4"
        mp3 = audio_dir / f"scene_{i:02d}.mp3"
        clip = clips_dir / f"scene_{i:02d}.mp4"
        dur = _duration(mp3) + 0.3  # small breath between scenes
        scene = plan.scenes[i]
        # An overlay that only repeats the narration would print the same words
        # the subtitles are already showing. The subtitles win: they are
        # word-timed and carry accessibility.
        overlay_text = scene.on_screen_text
        if _restates(overlay_text, scene.narration):
            overlay_text = None
        overlay = _overlay_filter(overlay_text, style=style)

        t_srt = time.perf_counter()
        words_json = audio_dir / f"scene_{i:02d}.words.json"
        srt_path = audio_dir / f"scene_{i:02d}.srt"
        _build_scene_srt(words_json, srt_path)
        srt_wall += time.perf_counter() - t_srt
        # ffmpeg cwd=work_dir so libass sees a clean relative path
        subs = _subtitle_filter(f"audio/scene_{i:02d}.srt", srt_path, style=style)
        # A compose card IS the scene's whole visual. When it shows the line the
        # narration speaks, the card wins and the subtitles stand down.
        if scene.compose and _restates(scene.compose.heading, scene.narration):
            subs = ""

        if vid.exists():
            scenes_wall += _run([
                "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(vid), "-i", str(mp3),
                "-filter_complex",
                f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,"
                f"crop=1920:1080,fps={FPS}{overlay}{subs}[v];[1:a]apad[a]",
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "veryfast", "-threads", "2",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "44100",
                "-t", f"{dur:.3f}", str(clip),
            ], cwd=work_dir, tag=f"scene[{i:02d}]:animated")
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
                f"{overlay}{subs}{fade_in}{fade_out}[v];"
                f"[1:a]apad[a]",
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "veryfast", "-threads", "2",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "44100",
                "-t", f"{dur:.3f}", str(clip),
            ], cwd=work_dir, tag=f"scene[{i:02d}]:kb")
            source = f"ken burns #{i % len(_KB_MODES) + 1}"
        clip_paths.append(clip)
        print(f"  assemble: scene clip {i + 1}/{len(plan.scenes)} ({source})")

    # Concat all scene clips.
    concat_list = work_dir / "concat.txt"
    concat_list.write_text("\n".join(f"file '{p.resolve()}'" for p in clip_paths))
    raw = work_dir / "video_raw.mp4"
    concat_wall = _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                        "-c", "copy", str(raw)], tag="concat")

    # Final pass. Subs are already burned per-scene, so:
    #   * no music → stream-copy raw → final (essentially free)
    #   * music    → copy video, only re-encode audio to mix the bed
    final = work_dir / "final.mp4"
    if music_path is not None:
        final_wall = _run([
            "ffmpeg", "-y", "-i", str(raw.resolve()),
            "-stream_loop", "-1", "-i", str(music_path.resolve()),
            "-filter_complex",
            "[1:a]volume=0.12[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac",
            "-shortest", str(final.resolve()),
        ], tag="final:music")
    else:
        final_wall = _run(["ffmpeg", "-y", "-i", str(raw.resolve()),
                           "-c", "copy", str(final.resolve())], tag="final:nomusic")

    logger.info(
        "assemble.summary scenes=%d total=%.2fs scenes_sum=%.2fs "
        "concat=%.2fs srt=%.2fs final=%.2fs",
        len(plan.scenes), time.perf_counter() - t_total,
        scenes_wall, concat_wall, srt_wall, final_wall,
    )
    return final


@dataclass(frozen=True, slots=True)
class MusicChoice:
    """Which track was picked and — the part that used to be silent — why.

    `source` is "mood" for a real music/<mood>/ hit, "fallback" for a random
    track from an unrelated mood, "none" when there is no music at all.
    """

    path: Optional[Path]
    source: str
    mood: str
    root: Path
    moods_available: tuple[str, ...] = ()
    mood_dir_exists: bool = False

    @property
    def matched(self) -> bool:
        """True only when the track really came from the requested mood."""
        return self.source == "mood"


def choose_music(music_root: Path, mood: str) -> MusicChoice:
    """Pick a random track from music/<mood>/, falling back to any track.

    Same behaviour as before — some music beats no music — but the caller can
    now tell a real mood match apart from a random fallback (see music_report).
    """
    mood_dir = music_root / mood
    mood_dir_exists = mood_dir.is_dir()
    moods = tuple(sorted(
        d.name for d in music_root.iterdir()
        if d.is_dir() and any(d.glob("*.mp3"))
    )) if music_root.is_dir() else ()

    pool = list(mood_dir.glob("*.mp3")) if mood_dir_exists else []
    if pool:
        return MusicChoice(random.choice(pool), "mood", mood, music_root,
                           moods, mood_dir_exists)
    pool = list(music_root.rglob("*.mp3")) if music_root.exists() else []
    if pool:
        return MusicChoice(random.choice(pool), "fallback", mood, music_root,
                           moods, mood_dir_exists)
    return MusicChoice(None, "none", mood, music_root, moods, mood_dir_exists)


def music_report(choice: MusicChoice) -> list[str]:
    """Header lines for the music pick — with a warning when the mood was missed.

    A wrong-mood soundtrack used to print exactly like a correct one; the
    warning names the folder that was missing and the moods that do exist.
    """
    if choice.path is None:
        return [report.row("music", "none", f"no .mp3 files under {choice.root}/")]
    try:
        label = str(choice.path.relative_to(choice.root))
    except ValueError:
        label = choice.path.name
    if choice.matched:
        return [report.row("music", label, f"mood '{choice.mood}', free (local file)")]

    folder = report.short_path(choice.root / choice.mood)
    missing = (f"{folder}/ has no .mp3 files" if choice.mood_dir_exists
               else f"no {folder}/ folder")
    return [
        report.row("music", label, f"RANDOM FALLBACK — mood '{choice.mood}' not matched"),
        report.warning(f"{missing} — picked a random track from another mood"),
        report.warning("moods available: " + (", ".join(choice.moods_available) or "none")),
    ]


def pick_music(music_root: Path, mood: str) -> Optional[Path]:
    """Path-only wrapper kept for callers that don't report the choice."""
    return choose_music(music_root, mood).path


def main() -> None:
    """CLI: python -m pipeline.assemble output/<slug> [--music-dir music]"""
    import argparse

    # CLI-only: make assemble.timing/summary lines visible when run standalone.
    # In the celery worker path Django's LOGGING config already installed handlers,
    # so basicConfig here is a no-op.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

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
    print(report.row("assemble", "ffmpeg",
                     f"local render, free, {report.plural(len(plan.scenes), 'scene')}"))
    if args.music:
        music = Path(args.music)
        if not music.is_file():
            import sys
            sys.exit(f"music file not found: {music}")
        print(report.row("music", music.name, "forced via --music"))
    else:
        choice = choose_music(Path(args.music_dir), plan.music_mood)
        music = choice.path
        for line in music_report(choice):
            print(line)
    final = assemble(plan, work_dir, music_path=music)
    print(f"Done: {final}")


if __name__ == "__main__":
    main()
