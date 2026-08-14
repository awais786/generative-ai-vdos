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

from . import report
from .env import load_env
from .plan_check import check_plan
from .schema import ShotPlan
# Imported at module level (both are cheap, stdlib/pydantic only) so
# _finalize_plan_artifacts resolves them as module attributes — that is what
# makes the "refine first, then persist" ordering testable.
from .script_agent import refine_plan
from .styles import save_style, style_for_plan


def _finalize_plan_artifacts(*, plan, work_dir, preset, persist_style,
                             model, animate, do_polish, do_review, on_write):
    """Run the refinement passes, then persist the resolved style.

    save_style runs last on purpose: refine_plan() returns a fresh ShotPlan
    parsed from the LLM, so a style file written before it would be describing a
    superseded plan. For the same reason the model-proposed palette is read
    *here*, from the plan that survived refinement — not in the caller's
    argument expression, which Python evaluates before this function is even
    entered and which would therefore persist the pre-refinement colours.

    persist_style is the caller's guard, threaded in rather than folded into
    `preset`, so that the palette read stays on this side of the refinement.
    """
    if do_polish or do_review:
        plan = refine_plan(
            plan, model=model, animate=animate,
            polish=do_polish, review=do_review, on_write=on_write,
        )
    if persist_style:
        save_style(work_dir, style_for_plan(preset, getattr(plan, "palette", None)))
    return plan


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
        if s.compose:
            print(f"  compose   : {s.compose.template} — {s.compose.heading!r}")
            continue
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
    # Only list stages that actually run. pipeline.video is disabled by policy
    # (it spends DashScope credit), and compose must appear whenever the plan
    # has a card scene — pipeline.images skips those, so assemble would fail
    # with "no image or clip for scene(s) N" and point at the one stage that
    # can never fix it.
    has_compose = any(s.compose for s in plan.scenes)
    print("next steps:")
    print(f"  revise : python -m pipeline.refine {work_dir} --change \"<your feedback>\"")
    print(f"  images : python -m pipeline.images {work_dir}")
    print(f"  voice  : python -m pipeline.voiceover {work_dir}")
    if has_compose:
        n = sum(1 for s in plan.scenes if s.compose)
        print(f"  compose: python -m pipeline.compose {work_dir}"
              f"   # required — {n} card scene(s) in this plan")
    print(f"  final  : python -m pipeline.assemble {work_dir}")


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
    parser.add_argument("--style", default=None,
                        help="Style preset name, 'list' to show all, or "
                             "'custom:your description' (.env: VIDEO_STYLE)")
    parser.add_argument("--seconds", type=int, default=None,
                        help="Target video length; sets the scene count "
                             "(default: the prompt's own 60-90s guidance)")
    args = parser.parse_args()
    forced_model = args.model is not None
    if not args.model:
        from .script_agent import default_model
        args.model = default_model()  # errors if LLM_PROVIDER not set

    from .styles import resolve_style
    # VIDEO_STYLE still supplies a default, but only an explicitly typed --style
    # may (re)write an existing video's style.json. Otherwise setting VIDEO_STYLE
    # in .env would silently repaint every older project you merely looked at.
    style_explicit = args.style is not None
    style = resolve_style(args.style if style_explicit else os.environ.get("VIDEO_STYLE"))

    if args.input is None:
        from .run import latest_work_dir
        in_path = latest_work_dir()
    else:
        in_path = Path(args.input)
    try:
        is_existing_plan = (in_path / "shot_plan.json").is_file()
    except OSError:  # long rough-text input exceeds filesystem name limits
        is_existing_plan = False

    # Header only when an LLM call is actually coming — viewing a plan is free.
    if not is_existing_plan or args.change or args.polish:
        from .script_agent import plan_report
        for line in plan_report(args.model, forced=forced_model):
            print(line)
        if args.style:
            print(report.note_line(f"style preset: {args.style} (--style / VIDEO_STYLE)"))

    if is_existing_plan:
        # Existing plan: view, or revise with --change.
        work_dir = in_path
        plan = ShotPlan.model_validate_json((work_dir / "shot_plan.json").read_text())
        if args.change:
            from .script_agent import revise_shot_plan
            print("revising plan...")
            plan = revise_shot_plan(plan, args.change, model=args.model)
            (work_dir / "shot_plan.json").write_text(plan.model_dump_json(indent=2))
    else:
        # New plan from rough text.
        if args.change:
            sys.exit("--change needs an existing output dir, e.g. "
                     "python -m pipeline.refine output/my-video --change \"...\"")
        import time

        from .run import slugify
        from .script_agent import generate_shot_plan, scene_count_for
        if args.seconds:
            # Print the resolved count so the 2-12 clamp is visible rather than
            # silently applied — --seconds 600 gives 12 scenes, not 100.
            print(f"target: ~{args.seconds}s -> {scene_count_for(args.seconds)} scenes")
        # The model is already named in the plan header printed above, so this
        # line no longer repeats it.
        print("generating plan...")
        plan = generate_shot_plan(args.input, model=args.model, style=style,
                                  target_seconds=args.seconds)
        # Folder named after the generated title, e.g. output/the-thief-act/
        name = args.name or slugify(plan.title)[:40].strip("-") or time.strftime("%Y%m%d-%H%M%S")
        work_dir = Path("output") / name
        if work_dir.exists():  # same title generated before — keep both
            work_dir = Path("output") / f"{name}-{time.strftime('%H%M%S')}"
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "shot_plan.json").write_text(plan.model_dump_json(indent=2))

    # New plans get a polish pass automatically; existing plans only with --polish.
    # Consistency review always runs on new plans (catches structural bugs like
    # recurring objects missing from the characters list). animate=False here —
    # pipeline.refine has no --animate flag, so plans start animation-free.
    do_polish = args.polish or (not is_existing_plan and not args.no_polish)
    do_review = args.polish or not is_existing_plan
    if is_existing_plan and style_explicit and not args.change:
        # Repainting the sidecar without regenerating the plan leaves the new
        # style's consistency_anchors appended to image prompts written for the
        # OLD style_prefix — noir's "high-contrast black and white grade" on a
        # watercolor plan, fighting each other in every prompt. The repaint is
        # still allowed (it is what --style on an existing plan means), but it
        # must not be silent.
        print(report.warning(
            f"--style {args.style} repaints style.json only — the plan's "
            f"style_prefix is unchanged, so image prompts may fight the new "
            f"anchors. Add --change \"restyle as {args.style}\" to rewrite the plan."))
    plan = _finalize_plan_artifacts(
        plan=plan, work_dir=work_dir,
        # With no preset, the helper falls back to the palette the model
        # proposed for this plan — otherwise the compose card picks its colours
        # from music_mood and disagrees with style_prefix. A preset always wins
        # (style_for_plan), and the palette is read inside the helper so it
        # comes from the plan that survived refinement.
        preset=style,
        # Only persist a style when this invocation is actually establishing one:
        # a brand-new plan, or a typed --style on an existing one. Persisting
        # unconditionally would let `python -m pipeline.refine <dir>` — the plain
        # "view this plan" command — silently rewrite an older video's style.json
        # from the VIDEO_STYLE env default, which is the same class of bug
        # (something unrelated picks the colours) this whole design removes.
        persist_style=(not is_existing_plan or style_explicit),
        model=args.model, animate=False,
        do_polish=do_polish, do_review=do_review,
        on_write=lambda p: (work_dir / "shot_plan.json").write_text(p.model_dump_json(indent=2)),
    )

    if not is_existing_plan:
        # Mark the plan stage done only after polish + consistency review have
        # rewritten shot_plan.json — otherwise a crash mid-refinement would leave
        # the dir flagged plan-complete with an unpolished plan and pipeline.run
        # would skip the plan stage.
        (work_dir / "state.json").write_text(json.dumps({"done": ["plan"]}, indent=2))

    for issue in check_plan(plan):
        print(report.warning(issue))
    print_plan(plan, work_dir)


if __name__ == "__main__":
    main()
