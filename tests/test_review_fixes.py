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


def test_a_card_scene_is_not_sent_to_the_image_stage(tmp_path, monkeypatch):
    """generate_images() skips compose scenes by design, so telling the user to
    run pipeline.images for a missing card was a dead end: the command reports
    'skipped' and assembly fails again, identically, forever."""
    import pipeline.assemble as assemble_mod
    from pipeline.schema import ShotPlan

    plan = ShotPlan.model_validate({
        "title": "T", "description": "d.", "tags": ["t"], "music_mood": "calm",
        "style_prefix": "photo",
        "scenes": [
            {"media_prompt": "a", "narration": "one"},
            {"media_prompt": "b", "narration": "two",
             "compose": {"template": "quote", "heading": "A line."}},
        ],
    })
    for sub in ("images", "audio", "video"):
        (tmp_path / sub).mkdir()
    (tmp_path / "images" / "scene_00.png").write_bytes(b"png")
    for i in (0, 1):
        (tmp_path / "audio" / f"scene_{i:02d}.mp3").write_bytes(b"mp3")
    monkeypatch.setattr(assemble_mod.shutil, "which", lambda n: f"/usr/bin/{n}")

    with pytest.raises(SystemExit) as exc:
        assemble_mod.assemble(plan, tmp_path)

    message = str(exc.value)
    assert "pipeline.compose" in message, "the card scene must point at the compose stage"
    assert "card scenes [1]" in message


def test_preflight_names_every_missing_var_at_once(monkeypatch):
    """Reporting one gap per run costs a round trip each time — and the earlier
    wording asserted 'the API key is present' when it was not."""
    from pipeline.registry import probe_images

    for var in ("DASHSCOPE_API_KEY", "QWEN_IMAGE_MODEL"):
        monkeypatch.delenv(var, raising=False)
    qwen = next(c for c in probe_images() if c.name == "qwen-image")
    assert "DASHSCOPE_API_KEY" in qwen.detail
    assert "QWEN_IMAGE_MODEL" in qwen.detail
    assert "is present" not in qwen.detail


@pytest.mark.parametrize("seconds, expected", [(15, 3), (21, 4), (27, 5), (33, 6)])
def test_scene_count_is_monotone(seconds, expected):
    """round() is banker's rounding: round(15/6) == round(2.5) == 2 gave
    --seconds 15 a ~12s video, and 21s and 27s both landed on 4 scenes."""
    from pipeline.script_agent import scene_count_for
    assert scene_count_for(seconds) == expected


def test_plan_director_routes_to_creative_intake():
    """The creative-intake spec's Integration section asked for this hand-off.
    Without it the skill was unreachable from the contract an agent reads, and
    --seconds was undiscoverable."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    assert "creative-intake" in (root / ".claude/skills/plan-director/SKILL.md").read_text()
    assert "creative-intake" in (root / "AGENT_GUIDE.md").read_text()


# --- third review round ----------------------------------------------------

def test_preflight_blames_only_the_vars_that_are_unset(monkeypatch):
    """With DASHSCOPE_API_KEY set and only the model id missing, the Images row
    said the key was not set while the Video row three lines below said it was —
    a self-contradicting table, from inferring the var list out of available()."""
    from pipeline.registry import probe_images

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.delenv("QWEN_IMAGE_MODEL", raising=False)
    qwen = next(c for c in probe_images() if c.name == "qwen-image")
    assert "QWEN_IMAGE_MODEL" in qwen.detail
    assert "DASHSCOPE_API_KEY" not in qwen.detail, "the key IS set; do not blame it"


def test_flux_and_gpt_image_require_their_model_ids(monkeypatch):
    """Only qwen's available() was taught to check its extra var, so its two
    siblings kept the 'selected, then dies on scene 1' bug."""
    import pipeline.images as images

    flux = next(p for p in images.PROVIDERS if p.name == "flux-schnell")
    gpt = next(p for p in images.PROVIDERS if p.name == "gpt-image-1")
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_test")
    monkeypatch.delenv("REPLICATE_IMAGE_MODEL", raising=False)
    assert flux.available() is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_IMAGE_MODEL", raising=False)
    assert gpt.available() is False


@pytest.mark.parametrize("heading, narration, suppress", [
    # The card IS the narration: it replaces the captions.
    ("Bees pollinate a third of our food.", "Bees pollinate a third of our food.", True),
    ("Greed is a curse.", "Moral: Greed is a curse.", True),
    # A short title merely CONTAINED in a long narration must not silence it.
    ("The Sharing Berry",
     "In a forest far away, the sharing berry changed everything for the animals", False),
])
def test_a_card_only_silences_captions_it_actually_replaces(heading, narration, suppress):
    """_restates fires on any contiguous 3-word phrase, so a title_card reading
    'The Sharing Berry' dropped all thirteen narrated words of captions —
    including the ten the card never shows."""
    from pipeline.assemble import _covers
    assert _covers(heading, narration) is suppress


def test_sizes_from_the_style_sidecar_cannot_break_the_filtergraph():
    """Colours were regex-validated; sizes were interpolated raw into drawtext
    and libass force_style from the same user-editable file."""
    import pipeline.assemble as assemble_mod
    bad = {"text": {"overlay_size": "big", "caption_size": "12:30"}}
    overlay = assemble_mod._overlay_filter("Text", style=bad)
    if overlay:
        assert "fontsize=58" in overlay, "falls back to the default"
        assert "big" not in overlay
    subs = assemble_mod._subtitle_filter("audio/scene_00.srt", _SRTStub(), style=bad)
    assert "12:30" not in subs


class _SRTStub:
    def is_file(self):
        return True

    def stat(self):
        class _S:
            st_size = 42
        return _S()


def test_a_custom_style_still_gets_a_palette():
    """resolve_style('custom:…') carries no palette, so style_for_plan returned
    it unchanged, save_style found no sidecar keys and wrote nothing, and the
    cards fell back to music_mood — worse colours than passing no style at all,
    with a valid model proposal sitting unused."""
    from pipeline.styles import resolve_style, style_for_plan

    proposed = {"bg1": "#101010", "bg2": "#202020", "fg": "#e8e8f0", "accent": "#c04080"}
    style = style_for_plan(resolve_style("custom:neon cyberpunk"), proposed)
    assert style["palette"]["fg"] == "#e8e8f0"
    assert style["source"] == "model", "invented colours must not reach burned-in text"
