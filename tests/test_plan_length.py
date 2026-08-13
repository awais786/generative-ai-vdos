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
    assert "Do not exceed 5 scenes" in rendered


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
