"""The redundancy predicate that decides when a text layer stands down.

Because the subtitles ARE the narration, an overlay or card heading that lifts
a phrase from the narration prints the same words twice on one frame. This
predicate finds that case -- and, just as importantly, does NOT fire on the
short labels ('ARGENTINA', 'Subscribe!') where repeating the narration is the
deliberate visual design of a listicle.
"""
import json
import pathlib

import pytest

from pipeline.assemble import _flatten, _restates

WAVE = "Everyone has a wave coming. Yours is out there too, past the horizon."


@pytest.mark.parametrize("text, narration", [
    # Verbatim lifts -- the defect this exists to catch.
    ("Everyone has a wave coming", WAVE),
    ("Cosmic vacuum cleaners!", "And black holes? They’re like cosmic vacuum cleaners!"),
    ("Vision and Strength", "It perches proudly, embodying vision and strength."),
    # Punctuation and case must not save a lift from being caught.
    ("everyone HAS a WAVE coming...", WAVE),
])
def test_fires_on_verbatim_lift(text, narration):
    assert _restates(text, narration) is True


@pytest.mark.parametrize("text, narration, why", [
    ("ARGENTINA", "Argentina — champions by destiny.", "under the 3-word floor"),
    ("Body Heart", "The third heart pumps blood to the body.", "under the floor"),
    ("Subscribe for more!", "Comment below and subscribe for more facts!", "CTA exemption"),
    ("Meet the Professor", "Meet our professor, a fountain of knowledge.", "paraphrase, not a lift"),
    ("Why is the Sky Blue?", "Did you know the sky isn't always blue?", "adds 'why'"),
    ("wave coming Everyone has a", WAVE, "same words, not contiguous"),
    ("", WAVE, "empty text"),
    (None, WAVE, "no text"),
    ("Everyone has a wave coming", "", "empty narration"),
    ("Everyone has a wave coming", None, "no narration"),
])
def test_does_not_fire(text, narration, why):
    assert _restates(text, narration) is False, why


OUTPUT = pathlib.Path(__file__).resolve().parent.parent / "output"


def _overlay_scenes():
    for plan_file in sorted(OUTPUT.glob("*/shot_plan.json")):
        try:
            plan = json.loads(plan_file.read_text())
        except (ValueError, OSError):
            continue  # a half-written plan from an interrupted run
        for scene in plan.get("scenes", []):
            if scene.get("on_screen_text"):
                yield plan_file.parent.name, scene["on_screen_text"], scene.get("narration")


@pytest.mark.skipif(not OUTPUT.is_dir(), reason="no output/ corpus in this checkout")
def test_corpus_suppression_stays_narrow():
    scenes = list(_overlay_scenes())
    if not scenes:
        pytest.skip("output/ has no plans with overlays")

    fired = [(name, text) for name, text, narration in scenes
             if _restates(text, narration)]

    # Every hit must be a genuine lift: at or over the floor, and contiguous.
    for name, text in fired:
        assert len(_flatten(text).split()) >= 3, f"{name}: {text!r} is a short label"

    # A rule that fires on a large share of overlays is deleting deliberate
    # labels, not redundant ones. Measured rate when written: 5/139 = 3.6%.
    rate = len(fired) / len(scenes)
    assert rate < 0.15, (
        f"suppressing {rate:.0%} of overlays ({len(fired)}/{len(scenes)}) — the rule "
        f"has been loosened and is now deleting deliberate labels: {fired[:10]}"
    )
