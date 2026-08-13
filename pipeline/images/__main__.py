"""(Re)generate images for an existing work dir — all scenes or a single one.

Usage:
    python -m pipeline.images output/<slug>                 # all scenes
    python -m pipeline.images output/<slug> --scene 7       # one scene, e.g. after editing its image_prompt
    python -m pipeline.images output/<slug> --backend pexels
"""
import argparse
import os
from pathlib import Path

from ..env import load_env
from ..schema import ShotPlan
from . import (character_refs, generate_images, generate_scene_image,
               get_provider, selection_report)


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_dir", nargs="?", default=None,
                        help="output/<name> dir (default: the most recent one)")
    parser.add_argument("--scene", type=int, default=None, help="Regenerate only this scene index (0-based)")
    parser.add_argument("--backend", default=os.environ.get("IMAGE_BACKEND"),
                        help="Image backend (.env: IMAGE_BACKEND; qwen | openai | "
                             "flux | stock | placeholder)")
    args = parser.parse_args()

    from ..run import latest_work_dir
    work_dir = Path(args.work_dir) if args.work_dir else latest_work_dir()
    print(f"video folder: {work_dir}")
    plan = ShotPlan.model_validate_json((work_dir / "shot_plan.json").read_text())
    out_dir = work_dir / "images"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.scene is not None:
        if plan.scenes[args.scene].compose:
            print(f"scene {args.scene} is a compose card "
                  f"({plan.scenes[args.scene].compose.template}) — no image to regenerate")
            return
        primary = get_provider(args.backend)
        for line in selection_report(primary, forced=args.backend is not None, scenes=1):
            print(line)
        # Reuse (or rebuild only the missing) character reference portraits so a
        # single-scene regen keeps the same faces/outfits as the rest of the video,
        # matching the full-run path in generate_images().
        refs = character_refs(plan, primary, out_dir, work_dir=work_dir)
        data, used = generate_scene_image(plan, args.scene, primary,
                                          fallback=args.backend is None, char_refs=refs,
                                          work_dir=work_dir)
        path = out_dir / f"scene_{args.scene:02d}.png"
        path.write_bytes(data)
        print(f"regenerated {path} via {used.name}")
    else:
        generate_images(plan, out_dir, backend=args.backend, work_dir=work_dir)


if __name__ == "__main__":
    main()
