"""Mechanical checks on a generated plan, run before anything is spent.

The LLM reliably produces plans that validate against the schema and are still
wrong — wrong in ways a reader spots in seconds and no type catches. Every check
here corresponds to a defect observed in a real generated plan:

- a book-summary brief produced six `lower_third` cards and no images at all
- four single-scene props (`house`, `calculator`, …) were cast as characters,
  each costing a billed reference portrait
- two of five overlays were verbatim lifts of their own narration, despite the
  `on_screen_text` field description telling the model not to do that

A plan costs ~$0.001 and images cost 10-20x that per scene, so this is the cheap
place to catch them. These are **warnings, not errors**: the model is sometimes
right and the user always decides. `consistency_review` in `script_agent` is the
LLM-based counterpart; this one is deterministic and free.
"""
from . import report
from .assemble import _restates
from .schema import ShotPlan

#: Below this, a scene is a caption rather than a beat. The corpus median is 10
#: words (~4.0s spoken) — the exact floor of the prompt's own 4-8s rule, which
#: is why finished videos run far shorter than intended. See `scene-script`.
_THIN_WORDS = 8


def check_plan(plan: ShotPlan) -> list[str]:
    """Problems worth seeing before the review gate. Empty list = nothing found."""
    issues: list[str] = []
    scenes = plan.scenes
    if not scenes:
        return ["plan has no scenes"]

    # 1. A plan of nothing but cards is a slideshow, not a video.
    if all(s.compose for s in scenes):
        issues.append(
            f"every one of the {len(scenes)} scenes is a text card — this plan has "
            f"no images at all. Give the story scenes a media_prompt and keep "
            f"cards for the title or closing beat.")

    # 2. A character used in one scene is a prop, and costs a reference portrait.
    #    Skipped entirely when no scene has a media_prompt: some older plans in
    #    output/ use the legacy `image_prompt` field, so every character would
    #    read as unused and the check would emit nothing but noise.
    if any(s.media_prompt for s in scenes):
        for c in plan.characters:
            used = sum(1 for s in scenes
                       if c.name in plan.characters_in(s.media_prompt))
            if used <= 1:
                issues.append(
                    f"character {{{c.name}}} appears in "
                    f"{report.plural(used, 'scene')} — props do not need a "
                    f"character entry, and each one costs a billed reference "
                    f"portrait. Describe it inline in that scene's media_prompt.")

    # 3. An overlay that lifts a phrase from its narration is dropped at
    #    assembly, so the label the user asked for never reaches the screen.
    for i, s in enumerate(scenes):
        if s.on_screen_text and _restates(s.on_screen_text, s.narration):
            issues.append(
                f"scene {i + 1}: overlay {s.on_screen_text!r} repeats its own "
                f"narration and will be suppressed at assembly. A label should "
                f"compress the idea, not echo the sentence.")

    # 4. Narration length is what actually sets the video's duration.
    thin = [i + 1 for i, s in enumerate(scenes)
            if not s.compose and len(s.narration.split()) < _THIN_WORDS]
    if thin and len(thin) > len([s for s in scenes if not s.compose]) // 2:
        issues.append(
            f"narration is short on scene(s) {', '.join(map(str, thin))} — under "
            f"{_THIN_WORDS} words is roughly 3 seconds, and scene durations come "
            f"from the voiceover. Aim for 12-20 words per scene.")

    return issues
