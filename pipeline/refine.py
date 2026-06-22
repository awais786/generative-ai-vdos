"""Refine a rough idea into a shot plan, review it in the terminal, iterate with feedback.

Usage:
    # 1. New plan from rough text -> output/<title-slug>/shot_plan.json + summary:
    python -m pipeline.refine "two friends talk about stars at night, urdu voices"
    #    (folder is named from the generated title, e.g. output/stars-at-night/)

    # 2. View the current plan again:
    python -m pipeline.refine output/stars-at-night

    # 3. Revise it with feedback (AI rewrites the plan, keeps the rest intact):
    python -m pipeline.refine output/stars-at-night --change "make the mom younger"

    # 4. When happy, generate:
    python -m pipeline.images output/stars-at-night
"""
import argparse
import json
import os
import sys
from pathlib import Path

from .env import load_env
from .schema import ShotPlan


def print_plan(plan: ShotPlan, work_dir: Path) -> None:
    line = "=" * 72
    print(line)
    print(f"TITLE : {plan.title}")
    print(f"STYLE : {plan.style_prefix}")
    print(f"MUSIC : {plan.music_mood}")
    print(f"LENGTH: ~{len(plan.scenes) * 5}s ({len(plan.scenes)} scenes)")
    for c in plan.characters:
        print(f"CHAR  : {{{c.name}}} = {c.description}")
    for i, s in enumerate(plan.scenes):
        print("-" * 72)
        print(f"scene {i}")
        print(f"  narration : {s.narration}")
        chars = plan.characters_in(s.media_prompt)
        if chars:
            print(f"  chars     : {', '.join(chars)} (full descriptions substituted automatically)")
        if s.outfit:
            print(f"  outfit    : {s.outfit}")
        print(f"  image     : {plan.expand(s.media_prompt, scene_outfit=s.outfit)}")
        if s.motion:
            print(f"  motion    : {plan.expand(s.motion, scene_outfit=s.outfit)}")
        if s.voice:
            print(f"  voice     : {s.voice}")
        if s.on_screen_text:
            print(f"  overlay   : {s.on_screen_text}")
    print(line)
    print(f"plan file : {work_dir / 'shot_plan.json'}")
    print()
    print("next steps:")
    print(f"  revise : python -m pipeline.refine {work_dir} --change \"<your feedback>\"")
    print(f"  images : python -m pipeline.images {work_dir}")
    print(f"  then   : python -m pipeline.video {work_dir} && "
          f"python -m pipeline.voiceover {work_dir} && python -m pipeline.assemble {work_dir}")


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(
        description="Rough idea -> reviewable shot plan; iterate with --change")
    parser.add_argument("input", nargs="?", default=None,
                        help="Rough idea text, or an existing output/<name> dir "
                             "(omit to view/revise the most recent one)")
    parser.add_argument("--change", default=None,
                        help="Feedback to revise an existing plan (use with an output dir)")
    parser.add_argument("--polish", action="store_true",
                        help="Rewrite an existing plan's image prompts with expert "
                             "composition/lighting detail (new plans are polished automatically)")
    parser.add_argument("--no-polish", action="store_true",
                        help="Skip the automatic polish pass when generating a new plan")
    parser.add_argument("--name", default=None,
                        help="Output folder name for a new plan (default: timestamp)")
    parser.add_argument("--model", default=None,
                        help="Override the model id (default: resolved from LLM_PROVIDER)")
    parser.add_argument("--style", default=os.environ.get("VIDEO_STYLE"),
                        help="Style preset name, 'list' to show all, or "
                             "'custom:your description' (.env: VIDEO_STYLE)")
    args = parser.parse_args()
    if not args.model:
        from .script_agent import default_model
        args.model = default_model()  # errors if LLM_PROVIDER not set

    from .styles import resolve_style
    style = resolve_style(args.style)

    if args.input is None:
        from .run import latest_work_dir
        in_path = latest_work_dir()
    else:
        in_path = Path(args.input)
    try:
        is_existing_plan = (in_path / "shot_plan.json").is_file()
    except OSError:  # long rough-text input exceeds filesystem name limits
        is_existing_plan = False
    if is_existing_plan:
        # Existing plan: view, or revise with --change.
        work_dir = in_path
        plan = ShotPlan.model_validate_json((work_dir / "shot_plan.json").read_text())
        if args.change:
            from .script_agent import revise_shot_plan
            print(f"revising plan ({args.model})...")
            plan = revise_shot_plan(plan, args.change, model=args.model)
            (work_dir / "shot_plan.json").write_text(plan.model_dump_json(indent=2))
    else:
        # New plan from rough text.
        if args.change:
            sys.exit("--change needs an existing output dir, e.g. "
                     "python -m pipeline.refine output/my-video --change \"...\"")
        import time

        from .run import slugify
        from .script_agent import generate_shot_plan
        print(f"generating plan ({args.model})...")
        plan = generate_shot_plan(args.input, model=args.model, style=style)
        # Folder named after the generated title, e.g. output/the-thief-act/
        name = args.name or slugify(plan.title)[:40].strip("-") or time.strftime("%Y%m%d-%H%M%S")
        work_dir = Path("output") / name
        if work_dir.exists():  # same title generated before — keep both
            work_dir = Path("output") / f"{name}-{time.strftime('%H%M%S')}"
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "shot_plan.json").write_text(plan.model_dump_json(indent=2))
        # mark the plan stage done so pipeline.run can also resume this dir
        (work_dir / "state.json").write_text(json.dumps({"done": ["plan"]}, indent=2))

    # New plans get a polish pass automatically; existing plans only with --polish.
    if args.polish or (not is_existing_plan and not args.no_polish):
        from .script_agent import polish_image_prompts
        print(f"polishing image prompts ({args.model})...")
        plan = polish_image_prompts(plan, model=args.model)
        (work_dir / "shot_plan.json").write_text(plan.model_dump_json(indent=2))

    # Consistency review always runs on new plans (catches structural bugs
    # like recurring objects missing from the characters list).
    if args.polish or not is_existing_plan:
        from .script_agent import consistency_review
        print(f"consistency review ({args.model})...")
        plan = consistency_review(plan, model=args.model)
        (work_dir / "shot_plan.json").write_text(plan.model_dump_json(indent=2))

    print_plan(plan, work_dir)


if __name__ == "__main__":
    main()
