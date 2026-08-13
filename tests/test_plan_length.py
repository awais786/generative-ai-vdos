"""The scriptwriting prompt has to ask for a length it can actually hit.

SYSTEM opened with "produce a complete shot plan for a 60-90 second video" and
separately said each scene's narration runs "roughly 4-8 seconds" — but never
stated a scene count, so the two rules were never connected. The model picked
its own count and the median finished video came out at 28s. None of the 16
rendered videos landed in the stated range.

These pin the arithmetic, the clamp, and — most importantly — that a caller
passing no target gets byte-identical text, since the web app's Celery path
calls generate_shot_plan with no target and must not shift.
"""
import pytest

from pipeline.script_agent import SYSTEM, scene_count_for, system_for


@pytest.mark.parametrize("seconds,expected", [
    (30, 5),    # round(30/6)
    (60, 10),
    (12, 2),
    (66, 11),
])
def test_scene_count_follows_the_six_second_midpoint(seconds, expected):
    # Six is the midpoint of SYSTEM's own "roughly 4-8 seconds" rule, so the
    # count and the rule agree by construction rather than by coincidence.
    assert scene_count_for(seconds) == expected


@pytest.mark.parametrize("seconds", [1, 5, 11])
def test_scene_count_clamps_at_the_bottom(seconds):
    # A careless --seconds 5 must not ask for a one-scene video.
    assert scene_count_for(seconds) == 2


@pytest.mark.parametrize("seconds", [90, 600, 100000])
def test_scene_count_clamps_at_the_top(seconds):
    # Nor a forty-scene one: every scene is a paid image.
    assert scene_count_for(seconds) == 12


def test_no_target_renders_todays_prompt_byte_for_byte():
    # The web app's Celery path (backend/apps/projects/tasks.py) passes no
    # target. Any drift here changes every web-app video's script.
    assert system_for(None) == SYSTEM


def test_a_target_states_the_scene_count_and_the_seconds():
    rendered = system_for(30)
    assert "about 30 seconds" in rendered
    assert "5 scenes" in rendered
    assert "no more than 5" in rendered


def test_the_stated_seconds_match_the_scene_count_that_was_clamped_to():
    """--seconds 300 clamps to 12 scenes, but the seconds figure used to be
    interpolated unclamped: 'about 300 seconds — that is 12 scenes' told the
    model two incompatible things at once, against the prompt's own 4-8s rule."""
    rendered = system_for(300)
    assert "300 seconds" not in rendered
    assert "about 72 seconds" in rendered, "12 scenes at the prompt's 6s midpoint"
    assert "12 scenes" in rendered


def test_the_length_clause_leaves_the_sentence_intact():
    """The slot sits mid-sentence, so an imperative there swallowed the rest:
    '...no more than 12 scenes built from still images, voiceover, and captions'."""
    rendered = system_for(60)
    assert "built from still images," in rendered
    assert rendered.index("built from still images,") > rendered.index("scenes")


def test_a_target_removes_the_hardcoded_range():
    # The 60-90s claim is the thing being fixed; it must not survive alongside
    # the new clause, or the prompt contradicts itself exactly as before.
    assert "60-90 second" not in system_for(30)


def test_the_length_clause_does_not_restate_a_per_scene_duration():
    # SYSTEM already says "roughly 4-8 seconds to speak aloud". A second,
    # narrower range in the new clause would recreate the contradiction.
    rendered = system_for(30)
    head = rendered.split("Rules:")[0]
    assert "5-6 second" not in head
    assert "seconds of narration each" not in head


def test_the_character_consistency_section_survives():
    # The strongest part of the prompt; templating must not clip it.
    for rendered in (system_for(None), system_for(30)):
        assert "CHARACTER AND VISUAL CONSISTENCY" in rendered
        assert "Argentina flag" in rendered


# --- CLI threading ---

import sys


def test_refine_passes_seconds_through(tmp_path, monkeypatch):
    # The flag is worthless unless it reaches the prompt. This drives main()
    # rather than the helper, because the wiring is where it would be dropped.
    import pipeline.refine as refine_mod

    seen = {}

    def fake_generate(topic, **kw):
        seen.update(kw)
        raise SystemExit(0)  # stop before any file is written

    monkeypatch.setattr("pipeline.script_agent.generate_shot_plan", fake_generate)
    # --model keeps this hermetic: without it main() calls default_model(),
    # which needs LLM_PROVIDER in the environment and fails in a clean
    # checkout or CI.
    monkeypatch.setattr(sys, "argv",
                        ["refine", "a topic", "--seconds", "30",
                         "--model", "gpt-4o-mini"])
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        refine_mod.main()
    assert seen.get("target_seconds") == 30


def test_refine_without_seconds_passes_none(tmp_path, monkeypatch):
    import pipeline.refine as refine_mod

    seen = {}

    def fake_generate(topic, **kw):
        seen.update(kw)
        raise SystemExit(0)

    monkeypatch.setattr("pipeline.script_agent.generate_shot_plan", fake_generate)
    monkeypatch.setattr(sys, "argv",
                        ["refine", "a topic", "--model", "gpt-4o-mini"])
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        refine_mod.main()
    # Assert the key is PRESENT and None, not merely absent — `.get()` returning
    # None would pass identically against a build that never threads the flag,
    # which is exactly the regression this is meant to catch.
    assert "target_seconds" in seen
    assert seen["target_seconds"] is None
