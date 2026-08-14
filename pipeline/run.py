"""Pipeline runner. Resumable: each stage records completion in state.json,
so a re-run skips finished stages instead of re-burning credits.

Usage:
    python -m pipeline.run "Why octopuses have three hearts"
    # review/edit output/<slug>/shot_plan.json, then re-run the same command
    python -m pipeline.run "Why octopuses have three hearts" --approve
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

from .env import load_env
from .schema import ShotPlan

load_env()

STAGES = ["plan", "images", "animate", "voice", "compose", "assemble"]


def _flag(name: str) -> bool:
    """A .env feature flag is on for 1/true/yes/on (case-insensitive)."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def latest_work_dir(out_root: Path = Path("output")) -> Path:
    """The most recently created/revised video folder — used when stage CLIs
    are run without a folder argument."""
    dirs = ([d for d in out_root.iterdir() if (d / "shot_plan.json").is_file()]
            if out_root.exists() else [])
    if not dirs:
        sys.exit('no video folders found — create one first:\n'
                 '  python -m pipeline.refine "your idea"')
    return max(dirs, key=lambda d: (d / "shot_plan.json").stat().st_mtime)


def load_state(work_dir: Path) -> dict:
    f = work_dir / "state.json"
    return json.loads(f.read_text()) if f.exists() else {"done": []}


def save_state(work_dir: Path, state: dict) -> None:
    (work_dir / "state.json").write_text(json.dumps(state, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Topic -> finished YouTube video")
    parser.add_argument("topic", help="Topic or rough script")
    # Defaults come from .env feature flags so a plain run needs no CLI params;
    # passing the flag on the command line still overrides the .env value.
    parser.add_argument("--approve", action="store_true", default=_flag("AUTO_APPROVE"),
                        help="Proceed past the shot-plan review gate (.env: AUTO_APPROVE)")
    parser.add_argument("--voice", default=None,
                        help="Narrator voice (.env: NARRATOR_VOICE; default: voiceover.DEFAULT_VOICE)")
    parser.add_argument("--model", default=None,
                        help="Override the model id (default: resolved from LLM_PROVIDER)")
    parser.add_argument("--out", default="output")
    parser.add_argument("--music-dir", default="music")
    parser.add_argument("--name", default=None,
                        help="Output folder name (default: slug of the topic text)")
    parser.add_argument("--redo", action="store_true",
                        help="Regenerate images that already exist "
                             "(default: skip them, so a re-run only fills gaps)")
    parser.add_argument("--image-backend", default=None,
                        help="Force an image provider (.env: IMAGE_BACKEND; see "
                             "pipeline/images: flux-schnell, gpt-image-1, pexels, placeholder)")
    parser.add_argument("--animate", action="store_true", default=_flag("ANIMATE"),
                        help="Animate scene stills into video clips (.env: ANIMATE; needs a "
                             "video backend, e.g. DASHSCOPE_API_KEY for Wan)")
    parser.add_argument("--video-backend", default=os.environ.get("VIDEO_BACKEND"),
                        help="Force a video provider (.env: VIDEO_BACKEND; see "
                             "pipeline/video: wan-i2v); implies --animate")
    parser.add_argument("--until", choices=STAGES, default=None,
                        help="Stop after this stage (step-by-step runs)")
    parser.add_argument("--style", default=os.environ.get("VIDEO_STYLE"),
                        help="Style preset name, 'list' to show all, or "
                             "'custom:your description' (.env: VIDEO_STYLE)")
    parser.add_argument("--seconds", type=int, default=None,
                        help="Target video length; sets the scene count "
                             "(default: the prompt's own 60-90s guidance)")
    args = parser.parse_args()
    # Deliberately not an argparse default: IMAGE_BACKEND must not be able to
    # select a paid backend on its own. pipeline.auto routes through here, so
    # leaving this out meant the one-shot path still billed gpt-image-1 from
    # .env alone — the very hole resolve_backend_arg exists to close.
    from .images import resolve_backend_arg
    try:
        args.image_backend = resolve_backend_arg(
            args.image_backend, os.environ.get("IMAGE_BACKEND"))
    except RuntimeError as e:
        sys.exit(str(e))
    forced_model = args.model is not None
    if not args.model:
        from .script_agent import default_model
        args.model = default_model()  # errors if LLM_PROVIDER not set

    from .styles import resolve_style
    style = resolve_style(args.style)

    from . import report

    work_dir = Path(args.out) / (args.name or slugify(args.topic))
    work_dir.mkdir(parents=True, exist_ok=True)
    state = load_state(work_dir)
    plan_file = work_dir / "shot_plan.json"

    # ---- Stage 1: shot plan ----
    if "plan" not in state["done"]:
        from .script_agent import (generate_shot_plan, plan_report, refine_plan,
                                   scene_count_for)
        print("stage: plan")
        for line in plan_report(args.model, forced=forced_model):
            print(line)
        if args.style:
            print(report.note_line(f"style preset: {args.style} (--style / VIDEO_STYLE)"))
        if args.seconds:
            # Show the resolved count so the 2-12 clamp is visible.
            print(report.note_line(
                f"target: ~{args.seconds}s -> {scene_count_for(args.seconds)} scenes"))
        plan = generate_shot_plan(args.topic, model=args.model, style=style,
                                  animate=args.animate,
                                  target_seconds=args.seconds)
        plan_file.write_text(plan.model_dump_json(indent=2))
        plan = refine_plan(
            plan, model=args.model, animate=args.animate,
            on_write=lambda p: plan_file.write_text(p.model_dump_json(indent=2)),
        )
        # After refine_plan, not before: it returns a fresh LLM-parsed plan, so a
        # style written earlier would describe a superseded one. Resuming a run
        # whose plan stage is already done skips this with the rest of the stage,
        # leaving an existing style.json alone.
        from .styles import save_style, style_for_plan
        # With no --style, persist the palette the model proposed for this plan
        # instead of writing nothing; a preset always wins over it.
        save_style(work_dir, style_for_plan(style, getattr(plan, "palette", None)))
        state["done"].append("plan")
        save_state(work_dir, state)
        print(f"  wrote {plan_file} ({len(plan.scenes)} scenes)")

    plan = ShotPlan.model_validate_json(plan_file.read_text())
    if args.until == "plan":
        print(f"stopped after plan (--until): review {plan_file}")
        return

    # ---- Review gate ----
    if not args.approve and "approved" not in state["done"]:
        print(f"\nReview gate: inspect/edit {plan_file}")
        print("Then re-run with --approve to generate assets.")
        sys.exit(0)
    if "approved" not in state["done"]:
        state["done"].append("approved")
        save_state(work_dir, state)

    # ---- Stage 2: images ----
    if "images" not in state["done"]:
        from .images import generate_images
        print("stage: images")
        generate_images(plan, work_dir / "images", backend=args.image_backend,
                        work_dir=work_dir, redo=args.redo)
        state["done"].append("images")
        save_state(work_dir, state)
    if args.until == "images":
        print("stopped after images (--until)")
        return

    # ---- Stage 2.5: animate (optional) ----
    if (args.animate or args.video_backend) and "animate" not in state["done"]:
        from .video import animate_scenes
        print("stage: animate")
        animate_scenes(plan, work_dir / "images", work_dir / "video",
                       backend=args.video_backend)
        state["done"].append("animate")
        save_state(work_dir, state)
    if args.until == "animate":
        print("stopped after animate (--until)")
        return

    # ---- Stage 3: voiceover ----
    if "voice" not in state["done"]:
        from .voiceover import DEFAULT_VOICE, generate_voiceover, voice_report
        print("stage: voiceover")
        # NARRATOR_VOICE still sets the voice, but only a typed --voice counts
        # as "forced" in the header. Defaulting the flag to the env var made the
        # report claim the user chose a voice they never mentioned — the same
        # env-vs-explicit conflation fixed for --style and --image-backend.
        voice = args.voice or os.environ.get("NARRATOR_VOICE") or None
        for line in voice_report(plan, voice or DEFAULT_VOICE,
                                 forced=args.voice is not None):
            print(line)
        generate_voiceover(plan, work_dir / "audio", voice=voice)
        state["done"].append("voice")
        save_state(work_dir, state)
    if args.until == "voice":
        print("stopped after voice (--until)")
        return

    # ---- Stage 3.5: compose (Remotion text/motion cards) ----
    # Runs after voice so each card sizes itself to its narration; renders straight
    # into video/scene_NN.mp4, which the assembler already prefers over Ken Burns.
    if "compose" not in state["done"]:
        compose_scenes = [i for i, s in enumerate(plan.scenes) if s.compose]
        if compose_scenes:
            from .compose import render_compositions
            print("stage: compose")
            render_compositions(plan, work_dir)
        state["done"].append("compose")
        save_state(work_dir, state)
    if args.until == "compose":
        print("stopped after compose (--until)")
        return

    # ---- Stage 4: assembly ----
    if "assemble" not in state["done"]:
        from .assemble import assemble, choose_music, music_report
        print("stage: assemble")
        print(report.row("assemble", "ffmpeg",
                         f"local render, free, {report.plural(len(plan.scenes), 'scene')}"))
        choice = choose_music(Path(args.music_dir), plan.music_mood)
        for line in music_report(choice):
            print(line)
        final = assemble(plan, work_dir, music_path=choice.path)
        state["done"].append("assemble")
        save_state(work_dir, state)
        print(f"\nDone: {final}")
        print(f"Title: {plan.title}")
    else:
        print(f"Already complete: {work_dir / 'final.mp4'}")


if __name__ == "__main__":
    main()
