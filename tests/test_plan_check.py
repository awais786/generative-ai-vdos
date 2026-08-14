"""Mechanical checks on a generated plan, before anything is spent.

Every check here corresponds to a defect observed in a real generated plan.
The LLM produces structurally-valid plans that are wrong in ways only a reader
notices, and plans cost $0.001 while images cost 10-20x that per scene — so the
cheap place to catch them is here.
"""
import pytest

from pipeline.plan_check import check_plan
from pipeline.schema import ShotPlan


def _plan(scenes, characters=None):
    return ShotPlan.model_validate({
        "title": "T", "description": "d.", "tags": ["t"],
        "music_mood": "calm", "style_prefix": "photo",
        "characters": characters or [],
        "scenes": scenes,
    })


def _card(heading="A Line", template="lower_third"):
    return {"template": template, "heading": heading}


def test_a_plan_of_only_cards_is_flagged():
    """Observed: a book-summary brief produced six lower_third cards and NO
    images at all — a slideshow, not a video."""
    plan = _plan([{"narration": f"line {i}", "media_prompt": "",
                   "compose": _card(f"Lesson {i}")} for i in range(4)])
    issues = "\n".join(check_plan(plan))
    assert "no images" in issues.lower()


def test_a_plan_with_one_card_is_fine():
    """A closing quote or outro card is normal and must not warn."""
    plan = _plan([
        {"narration": "one", "media_prompt": "a photo"},
        {"narration": "two", "media_prompt": "a photo"},
        {"narration": "three", "media_prompt": "", "compose": _card("The End", "outro")},
    ])
    assert not [i for i in check_plan(plan) if "no images" in i.lower()]


def test_a_character_used_in_one_scene_is_flagged_as_a_prop():
    """Observed: house, finance_books, calculator and investment_choice each
    appeared in one scene, and each cost a billed reference portrait."""
    plan = _plan(
        scenes=[{"narration": "one", "media_prompt": "{hero} beside {calculator}"},
                {"narration": "two", "media_prompt": "{hero} walking"}],
        characters=[{"name": "hero", "description": "a man in a grey coat"},
                    {"name": "calculator", "description": "a grey calculator",
                     "is_inanimate": True}],
    )
    issues = "\n".join(check_plan(plan))
    assert "calculator" in issues
    assert "hero" not in issues, "a character in two scenes is a real character"


def test_an_overlay_that_repeats_its_narration_is_flagged():
    """Observed: 2 of 5 overlays were verbatim lifts, despite the schema field
    telling the model never to repeat a phrase from the narration."""
    plan = _plan([{"narration": "Instead of working for money, make money work for you.",
                   "media_prompt": "a desk", "on_screen_text": "Make Money Work"}])
    issues = "\n".join(check_plan(plan))
    assert "Make Money Work" in issues
    assert "suppressed" in issues.lower()


def test_a_label_that_compresses_is_not_flagged():
    plan = _plan([{"narration": "Instead of working for money, make money work for you.",
                   "media_prompt": "a desk", "on_screen_text": "Assets Over Income"}])
    assert not [i for i in check_plan(plan) if "Assets Over Income" in i]


def test_thin_narration_is_flagged():
    """Measured across 30 videos: the median scene is 10 words (~4.0s), the
    exact floor of the prompt's own 4-8s target, which is why finished videos
    run far shorter than intended. See the scene-script skill."""
    plan = _plan([{"narration": "Money matters.", "media_prompt": "a desk"},
                  {"narration": "Save more.", "media_prompt": "a bank"}])
    issues = "\n".join(check_plan(plan))
    assert "short" in issues.lower()


def test_a_healthy_plan_reports_nothing():
    """The check must stay quiet on a good plan, or it becomes noise people
    learn to scroll past."""
    plan = _plan(
        scenes=[
            {"narration": "The rich buy assets while the poor buy liabilities they mistake for assets.",
             "media_prompt": "{hero} at a desk comparing a deed against a stack of bills",
             "on_screen_text": "Wealthy Buy Assets"},
            {"narration": "Financial literacy will take you further than any salary ever will.",
             "media_prompt": "{hero} reading a finance book by a window",
             "on_screen_text": "Knowledge Over Salary"},
            {"narration": "Start today, and let your money begin working for you.",
             "media_prompt": "", "compose": _card("Begin now", "outro")},
        ],
        characters=[{"name": "hero", "description": "a man in a grey coat"}],
    )
    assert check_plan(plan) == []
