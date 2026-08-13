"""Regressions found by code review of the pipeline branch, 2026-08-13.

Each test here corresponds to a defect that shipped once. The money-rule one
matters most: the guard existed, but only on the path fewer people run.
"""
import os
import sys

import pytest

import pipeline.run as run_mod


def _argv(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["pipeline.run", *args])


def test_env_image_backend_cannot_make_the_one_shot_path_spend(monkeypatch, capsys):
    """resolve_backend_arg was wired into pipeline.images only. run.py — which
    pipeline.auto routes through, and which is the command the docs recommend
    for a one-shot video — still defaulted --image-backend to IMAGE_BACKEND and
    passed it straight to generate_images. So `IMAGE_BACKEND=openai` in .env
    billed gpt-image-1 for every scene with nothing typed on the command line.
    """
    monkeypatch.setenv("IMAGE_BACKEND", "openai")
    monkeypatch.setattr(run_mod, "load_env", lambda: None)
    _argv(monkeypatch, "a topic")

    with pytest.raises(SystemExit) as exc:
        run_mod.main()

    message = str(exc.value)
    assert "IMAGE_BACKEND" in message
    assert "gpt-image-1" in message
    assert "--backend" in message, "the message must name the way to opt in"


def test_env_image_backend_still_allows_a_free_backend(monkeypatch):
    """The guard must refuse only paid backends, not every env default."""
    from pipeline.images import resolve_backend_arg

    monkeypatch.setenv("IMAGE_BACKEND", "placeholder")
    assert resolve_backend_arg(None, os.environ["IMAGE_BACKEND"]) == "placeholder"


def test_narrator_voice_env_is_not_reported_as_forced(monkeypatch):
    """--voice defaulted to NARRATOR_VOICE, so the header claimed 'forced via
    --voice' for a voice the user never typed — the same env-vs-explicit
    conflation already fixed for --style and --image-backend."""
    from pipeline.voiceover import voice_report

    import re
    source = open(run_mod.__file__, encoding="utf-8").read()
    # Match the default= only: the help text legitimately names the env var.
    default = re.search(r'add_argument\("--voice",\s*default=([^,\n]+)', source).group(1)
    assert default.strip() == "None", (
        "--voice must default to None; NARRATOR_VOICE is applied after parsing, "
        f"so it does not count as an explicit choice. Got default={default}")

    # And the report itself distinguishes the two.
    plan = _plan()
    explicit = "\n".join(voice_report(plan, "en-US-AriaNeural", forced=True))
    implicit = "\n".join(voice_report(plan, "en-US-AriaNeural", forced=False))
    assert "forced" in explicit
    assert "forced" not in implicit


def _plan():
    from pipeline.schema import ShotPlan
    return ShotPlan.model_validate({
        "title": "T", "description": "d.", "tags": ["t"], "music_mood": "calm",
        "style_prefix": "photo",
        "scenes": [{"media_prompt": "a", "narration": "hello there"}],
    })


def test_scene_count_bounds_agree_with_the_schema_description():
    """system_for() said 'do not exceed N scenes' while the response schema the
    model receives simultaneously said '8-15 scenes'. Two contradictory
    instructions in one request made --seconds unreliable."""
    from pipeline.schema import ShotPlan
    from pipeline.script_agent import MAX_SCENES, MIN_SCENES

    described = ShotPlan.model_fields["scenes"].description
    assert f"{MIN_SCENES}-{MAX_SCENES}" in described, (
        f"schema says {described!r} but the clamp is {MIN_SCENES}-{MAX_SCENES}")
