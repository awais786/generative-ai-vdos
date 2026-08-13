"""The style guide and its sidecar file.

A video's look is decided in four places (image prompts, compose cards,
captions, overlays). Before this, each read a different source and they drifted:
a plan with style_prefix "warm desert tones" rendered a purple quote card,
because the card's palette was looked up by music_mood. These tests pin the
single source and, just as importantly, the fallbacks — every existing
output/*/ folder has no style.json and must keep rendering.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.styles import PRESETS, load_style, resolve_style, save_style

PALETTE_KEYS = {"bg1", "bg2", "fg", "accent", "glow"}
TEXT_KEYS = {"caption_size", "caption_outline", "overlay_size", "overlay_border"}


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_every_preset_is_complete(name):
    # A preset missing a key would silently fall back for that one value,
    # producing a video that is styled *almost* consistently — the hardest
    # kind of drift to notice.
    preset = PRESETS[name]
    assert PALETTE_KEYS == set(preset["palette"]), name
    assert TEXT_KEYS == set(preset["text"]), name
    assert preset["consistency_anchors"], name


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_palette_values_are_hex(name):
    # Remotion, libass and drawtext all need parseable colours; a stray
    # "warm gold" here surfaces as a broken render, not a config error.
    for key, value in PRESETS[name]["palette"].items():
        if key == "glow":
            continue  # rgba(...) by design — used for CSS shadows only
        assert value.startswith("#") and len(value) == 7, f"{name}.{key}={value}"
        int(value[1:], 16)


def test_save_then_load_round_trips(tmp_path):
    written = save_style(tmp_path, PRESETS["cinematic"])
    assert written == tmp_path / "style.json"
    loaded = load_style(tmp_path)
    assert loaded["palette"] == PRESETS["cinematic"]["palette"]
    assert loaded["consistency_anchors"] == PRESETS["cinematic"]["consistency_anchors"]
    assert loaded["name"] == "cinematic"


def test_save_style_with_no_preset_writes_nothing(tmp_path):
    # A run with no --style must leave the work dir exactly as it was.
    assert save_style(tmp_path, None) is None
    assert not (tmp_path / "style.json").exists()


def test_load_style_missing_file_returns_empty(tmp_path):
    # Every existing output/*/ folder is in this state.
    assert load_style(tmp_path) == {}


def test_load_style_corrupt_file_returns_empty(tmp_path):
    # Falling back beats crashing stage 4 on a hand-edited file.
    (tmp_path / "style.json").write_text("{not json")
    assert load_style(tmp_path) == {}


def test_custom_style_saves_without_palette(tmp_path):
    # resolve_style("custom:...") returns a partial dict with no palette;
    # saving it must not invent one.
    preset = resolve_style("custom: oil painting, thick impasto")
    save_style(tmp_path, preset)
    assert load_style(tmp_path).get("palette") in (None, {})


# --- entry points ---

def test_refine_writes_style_after_refinement(tmp_path, monkeypatch):
    # Ordering matters: refine_plan() returns a fresh ShotPlan parsed from the
    # LLM. Anything written before it runs describes a plan that no longer
    # exists. This asserts save_style is called after, by recording the order.
    import pipeline.refine as refine_mod

    calls: list[str] = []

    def fake_refine_plan(plan, **kwargs):
        calls.append("refine_plan")
        return plan

    def fake_save_style(work_dir, preset):
        calls.append("save_style")
        return None

    monkeypatch.setattr(refine_mod, "refine_plan", fake_refine_plan, raising=False)
    monkeypatch.setattr(refine_mod, "save_style", fake_save_style, raising=False)

    # The helper under test is the small function extracted in Step 3.
    refine_mod._finalize_plan_artifacts(
        plan=object(), work_dir=tmp_path, preset=PRESETS["noir"],
        persist_style=True,
        model="m", animate=False, do_polish=True, do_review=True,
        on_write=lambda p: None,
    )
    assert calls == ["refine_plan", "save_style"]


def test_finalize_writes_a_real_style_file(tmp_path, monkeypatch):
    import pipeline.refine as refine_mod
    monkeypatch.setattr(refine_mod, "refine_plan",
                        lambda plan, **kw: plan, raising=False)
    refine_mod._finalize_plan_artifacts(
        plan=object(), work_dir=tmp_path, preset=PRESETS["noir"],
        persist_style=True,
        model="m", animate=False, do_polish=False, do_review=False,
        on_write=lambda p: None,
    )
    assert json.loads((tmp_path / "style.json").read_text())["name"] == "noir"


def test_style_uses_the_palette_that_survived_refinement(tmp_path, monkeypatch):
    # refine_plan() returns a fresh plan parsed from the LLM — a full round trip
    # over the whole plan, constrained only by prose ("return the COMPLETE
    # plan"), not by anything structural. If a pass rewrites `palette`,
    # style.json must carry the colours of the plan that was actually written to
    # disk; otherwise the sidecar disagrees with the shot_plan.json beside it.
    # This is the same reason save_style runs last, and it is why the palette
    # cannot be read in the call-site argument expression: Python evaluates that
    # before the helper is entered.
    import pipeline.refine as refine_mod

    before = {"bg1": "#111111", "bg2": "#222222", "fg": "#333333", "accent": "#444444"}
    after = {"bg1": "#aa1111", "bg2": "#aa2222", "fg": "#aa3333", "accent": "#aa4444"}
    monkeypatch.setattr(refine_mod, "refine_plan",
                        lambda plan, **kw: SimpleNamespace(palette=after),
                        raising=False)

    refine_mod._finalize_plan_artifacts(
        plan=SimpleNamespace(palette=before), work_dir=tmp_path, preset=None,
        persist_style=True,
        model="m", animate=False, do_polish=True, do_review=True,
        on_write=lambda p: None,
    )
    assert json.loads((tmp_path / "style.json").read_text())["palette"]["bg1"] == "#aa1111"


def test_persist_style_false_writes_nothing_even_with_a_palette(tmp_path, monkeypatch):
    # The guard the call site threads in: viewing an existing plan must not
    # write a style file just because that plan happens to carry a palette.
    import pipeline.refine as refine_mod
    monkeypatch.setattr(refine_mod, "refine_plan",
                        lambda plan, **kw: plan, raising=False)
    refine_mod._finalize_plan_artifacts(
        plan=SimpleNamespace(palette={"bg1": "#111111", "bg2": "#222222",
                                      "fg": "#333333", "accent": "#444444"}),
        work_dir=tmp_path, preset=None, persist_style=False,
        model="m", animate=False, do_polish=False, do_review=False,
        on_write=lambda p: None,
    )
    assert not (tmp_path / "style.json").exists()


# --- the call-site guard (only main() can get this wrong) ---

def _existing_project(work_dir: Path) -> Path:
    """A minimal but valid existing video folder, already styled 'noir'."""
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "shot_plan.json").write_text(json.dumps({
        "title": "T", "description": "D", "tags": ["t"],
        "music_mood": "calm", "style_prefix": "sp",
        "scenes": [{"narration": "n", "media_prompt": "m"}],
    }))
    style_file = work_dir / "style.json"
    save_style(work_dir, PRESETS["noir"])
    return style_file


def _run_refine(monkeypatch, argv: list[str]):
    import pipeline.refine as refine_mod
    # --model short-circuits default_model(); do_polish/do_review are both False
    # for a plain existing-plan view, so no LLM is reachable either way.
    monkeypatch.setattr(refine_mod, "refine_plan", lambda plan, **kw: plan, raising=False)
    monkeypatch.setattr(sys, "argv", ["pipeline.refine", *argv, "--model", "m"])
    refine_mod.main()


def test_env_style_never_repaints_an_existing_plan(tmp_path, monkeypatch, capsys):
    # The guard lives at main()'s call site, so only a test that drives main()
    # can catch this. VIDEO_STYLE is a *default* for new plans; it must never
    # make `python -m pipeline.refine <dir>` — the plain "view this plan"
    # command — repaint a video whose look was already decided.
    style_file = _existing_project(tmp_path / "vid")
    before = style_file.read_bytes()
    monkeypatch.setenv("VIDEO_STYLE", "cinematic")

    _run_refine(monkeypatch, [str(tmp_path / "vid")])

    assert style_file.read_bytes() == before


def test_typed_style_flag_does_rewrite_an_existing_plan(tmp_path, monkeypatch, capsys):
    # The other half of the contract: asking for a restyle explicitly still works.
    style_file = _existing_project(tmp_path / "vid")
    monkeypatch.setenv("VIDEO_STYLE", "noir")

    _run_refine(monkeypatch, [str(tmp_path / "vid"), "--style", "cinematic"])

    assert json.loads(style_file.read_text())["name"] == "cinematic"


# --- LLM-proposed palettes for the no-preset path ---

from pipeline.styles import validate_palette  # noqa: E402


def test_validate_palette_accepts_four_hex_keys_and_derives_glow():
    # The model supplies four colours; glow is derived so it cannot be malformed
    # and the model has one less thing to get wrong.
    out = validate_palette({"bg1": "#0b0b12", "bg2": "#3a1f22",
                            "fg": "#f4ead6", "accent": "#e0714a"})
    assert set(out) == {"bg1", "bg2", "fg", "accent", "glow"}
    assert out["accent"] == "#e0714a"
    assert out["glow"].startswith("rgba(224,113,74,")


def test_validate_palette_normalises_case():
    out = validate_palette({"bg1": "#0B0B12", "bg2": "#3A1F22",
                            "fg": "#F4EAD6", "accent": "#E0714A"})
    assert out["bg1"] == "#0b0b12"


@pytest.mark.parametrize("bad", [
    None,
    "purple",
    {},
    {"bg1": "#0b0b12"},                                   # incomplete
    {"bg1": "warm", "bg2": "#3a1f22", "fg": "#f4ead6", "accent": "#e0714a"},
    {"bg1": "#0b0b1", "bg2": "#3a1f22", "fg": "#f4ead6", "accent": "#e0714a"},
    {"bg1": "#zzzzzz", "bg2": "#3a1f22", "fg": "#f4ead6", "accent": "#e0714a"},
])
def test_validate_palette_rejects_bad_input(bad):
    # Anything the model gets wrong must fall back to today's behaviour rather
    # than reaching Remotion or libass, where a bad value is a silent wrong
    # colour rather than an error.
    assert validate_palette(bad) is None


def test_preset_beats_the_models_proposal(tmp_path):
    # A named style is a promise that two videos in that style match. The
    # model's per-video suggestion must never override it.
    from pipeline.styles import PRESETS, resolve_style, style_for_plan
    proposed = {"bg1": "#111111", "bg2": "#222222",
                "fg": "#333333", "accent": "#444444"}
    chosen = style_for_plan(resolve_style("noir"), proposed)
    assert chosen["palette"] == PRESETS["noir"]["palette"]


def test_model_palette_used_when_no_preset():
    from pipeline.styles import style_for_plan
    proposed = {"bg1": "#111111", "bg2": "#222222",
                "fg": "#333333", "accent": "#444444"}
    chosen = style_for_plan(None, proposed)
    assert chosen["palette"]["bg1"] == "#111111"
    assert chosen["consistency_anchors"] == []


def test_no_preset_and_no_proposal_yields_nothing():
    from pipeline.styles import style_for_plan
    assert style_for_plan(None, None) is None
