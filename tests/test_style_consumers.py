"""The four renderers reading one style source.

Each of these pins a drift that actually happened: image scenes re-interpreting
a style phrase per scene, and a quote card picking its colours from music_mood.
"""
import json
from pathlib import Path

import pytest

from pipeline.schema import ShotPlan
from pipeline.styles import PRESETS, save_style

NOIR_ANCHORS = PRESETS["noir"]["consistency_anchors"]


def _plan(**over):
    base = {
        "title": "T", "description": "d", "tags": ["t"],
        "music_mood": "calm", "style_prefix": "cinematic photo",
        "scenes": [{"media_prompt": "a lighthouse", "narration": "hello"}],
    }
    base.update(over)
    return ShotPlan.model_validate(base)


class FakeProvider:
    """Records every prompt it is asked to render."""

    name = "fake"
    can_edit = False   # subclasses that define edit() must flip this

    def __init__(self):
        self.seen: list[str] = []

    def available(self):
        return True

    def generate(self, prompt, query=None, negative=None, api_key=None,
                 model=None, on_preview_url=None):
        self.seen.append(prompt)
        return b"png"


def test_extra_overhead_changes_the_compaction_threshold():
    # expand() cannot see the anchors (they are not on ShotPlan), so callers
    # declare their length. The compaction branch is gated on
    # `len(refs) >= 3 and len(result) > budget`, so this only bites with three
    # or more characters actually referenced — a plan with none would exercise
    # nothing at all, and the test would pass against an implementation that
    # ignored extra_overhead entirely.
    chars = [{"name": n, "description": f"a person called {n}, " + "d" * 120}
             for n in ("ana", "ben", "cal")]
    plan = _plan(characters=chars,
                 scenes=[{"media_prompt": "{ana} and {ben} and {cal} talk",
                          "narration": "hi"}])
    text = "{ana} and {ben} and {cal} talk"

    roomy = plan.expand(text, include_style_overhead=True,
                        extra_overhead=0, max_chars=600)
    tight = plan.expand(text, include_style_overhead=True,
                        extra_overhead=400, max_chars=600)

    # Same budget, same text — only the declared overhead differs, and that must
    # be enough to push the tight case over the threshold into compaction.
    assert roomy != tight, "extra_overhead did not affect the compaction threshold"
    assert len(tight) < len(roomy)


def test_expand_extra_overhead_defaults_to_zero():
    # Every existing call site must behave exactly as before.
    plan = _plan()
    assert plan.expand("a lighthouse", include_style_overhead=True) == "a lighthouse"


def test_anchors_are_appended_to_scene_prompts(tmp_path):
    import pipeline.images as images

    save_style(tmp_path, PRESETS["noir"])
    provider = FakeProvider()

    plan = _plan()
    images.generate_scene_image(plan, 0, provider, fallback=False,
                                work_dir=tmp_path)
    assert provider.seen, "provider was never called"
    for anchor in NOIR_ANCHORS:
        assert anchor in provider.seen[0], f"missing anchor: {anchor}"


def test_no_style_file_leaves_prompts_unchanged(tmp_path):
    import pipeline.images as images

    provider = FakeProvider()

    plan = _plan()
    images.generate_scene_image(plan, 0, provider, fallback=False,
                                work_dir=tmp_path)
    assert "same high-contrast" not in provider.seen[0]
    assert provider.seen[0].startswith("cinematic photo")
    assert provider.seen[0] == "cinematic photo, a lighthouse"


def test_generate_images_threads_work_dir_to_the_prompt(tmp_path, monkeypatch):
    """The path a real run actually takes.

    run.py and `python -m pipeline.images` call generate_images(), never
    generate_scene_image() directly. If work_dir stops here the feature is
    inert on every real video while the unit tests above stay green.
    """
    import pipeline.images as images

    save_style(tmp_path, PRESETS["noir"])
    provider = FakeProvider()
    monkeypatch.setattr(images, "get_provider", lambda *a, **k: provider)

    plan = _plan()
    paths = images.generate_images(plan, tmp_path / "images", backend="fake",
                                   work_dir=tmp_path)

    assert paths == [tmp_path / "images" / "scene_00.png"]
    assert provider.seen, "provider was never called"
    for anchor in NOIR_ANCHORS:
        assert anchor in provider.seen[0], f"missing anchor: {anchor}"


def test_character_reference_portraits_carry_the_anchors(tmp_path, monkeypatch):
    """The reference portrait is what every character scene is edited from, so
    an un-anchored portrait re-introduces the drift one level down."""
    import pipeline.images as images

    save_style(tmp_path, PRESETS["noir"])

    class EditingProvider(FakeProvider):
        can_edit = True

        def edit(self, prompt, refs, negative=None, api_key=None, model=None,
                 on_preview_url=None):
            self.seen.append(prompt)
            return b"png"

    provider = EditingProvider()
    monkeypatch.setattr(images, "get_provider", lambda *a, **k: provider)

    plan = _plan(
        characters=[{"name": "ana", "description": "a woman with red hair"}],
        scenes=[{"media_prompt": "{ana} on a pier", "narration": "hi"}],
    )
    images.generate_images(plan, tmp_path / "images", backend="fake",
                           work_dir=tmp_path)

    ref_prompt = provider.seen[0]  # the portrait is rendered before any scene
    assert "character reference portrait" in ref_prompt
    for anchor in NOIR_ANCHORS:
        assert anchor in ref_prompt, f"missing anchor on reference portrait: {anchor}"


def test_inanimate_reference_portraits_carry_the_anchors(tmp_path, monkeypatch):
    import pipeline.images as images

    save_style(tmp_path, PRESETS["noir"])

    class EditingProvider(FakeProvider):
        can_edit = True

        def edit(self, prompt, refs, negative=None, api_key=None, model=None,
                 on_preview_url=None):
            self.seen.append(prompt)
            return b"png"

    provider = EditingProvider()
    monkeypatch.setattr(images, "get_provider", lambda *a, **k: provider)

    plan = _plan(
        characters=[{"name": "urn", "description": "a cracked clay urn",
                     "is_inanimate": True}],
        scenes=[{"media_prompt": "{urn} on a table", "narration": "hi"}],
    )
    images.generate_images(plan, tmp_path / "images", backend="fake",
                           work_dir=tmp_path)

    ref_prompt = provider.seen[0]
    assert "product-style shot" in ref_prompt
    for anchor in NOIR_ANCHORS:
        assert anchor in ref_prompt, f"missing anchor on object reference: {anchor}"


def test_generate_images_without_style_file_is_unchanged(tmp_path, monkeypatch):
    import pipeline.images as images

    provider = FakeProvider()
    monkeypatch.setattr(images, "get_provider", lambda *a, **k: provider)

    plan = _plan()
    images.generate_images(plan, tmp_path / "images", backend="fake",
                           work_dir=tmp_path)
    assert provider.seen == ["cinematic photo, a lighthouse"]


def test_generate_images_without_work_dir_is_unchanged(tmp_path, monkeypatch):
    """work_dir is optional — callers that never pass it (the Django worker)
    must keep today's prompts, not crash."""
    import pipeline.images as images

    save_style(tmp_path, PRESETS["noir"])
    provider = FakeProvider()
    monkeypatch.setattr(images, "get_provider", lambda *a, **k: provider)

    plan = _plan()
    images.generate_images(plan, tmp_path / "images", backend="fake")
    assert provider.seen == ["cinematic photo, a lighthouse"]


# --- compose ---

def test_palette_comes_from_style_not_music_mood(tmp_path):
    # The bug this fixes: a plan whose style_prefix said "warm desert tones" got
    # a purple quote card, because the palette was looked up by music_mood.
    import pipeline.compose as compose

    save_style(tmp_path, PRESETS["cinematic"])
    plan = _plan(music_mood="inspiring")  # would have selected the purple palette
    palette = compose._palette_for(plan, work_dir=tmp_path)
    assert palette == PRESETS["cinematic"]["palette"]
    assert palette["bg1"] != compose.MOOD_PALETTES["inspiring"]["bg1"]


def test_palette_falls_back_to_music_mood_without_style(tmp_path):
    # Every existing output/*/ folder is in this state.
    import pipeline.compose as compose

    plan = _plan(music_mood="inspiring")
    assert compose._palette_for(plan, work_dir=tmp_path) == compose.MOOD_PALETTES["inspiring"]


def test_partial_palette_falls_back_per_key(tmp_path):
    # A hand-edited style.json missing one key must not produce a card with an
    # empty background; only that key falls back.
    import pipeline.compose as compose

    (tmp_path / "style.json").write_text(json.dumps({"palette": {"accent": "#ff0000"}}))
    palette = compose._palette_for(_plan(music_mood="calm"), work_dir=tmp_path)
    assert palette["accent"] == "#ff0000"
    assert palette["bg1"] == compose.MOOD_PALETTES["calm"]["bg1"]


# --- captions and overlays ---

def test_hex_to_ass_reverses_byte_order():
    # libass takes &HAABBGGRR — blue first. Passing #rrggbb straight through
    # produces the wrong colour silently, with no error anywhere.
    import pipeline.assemble as assemble
    assert assemble._hex_to_ass("#f4ead6") == "&H00D6EAF4"
    assert assemble._hex_to_ass("#000000") == "&H00000000"


def test_hex_to_drawtext_keeps_byte_order():
    import pipeline.assemble as assemble
    assert assemble._hex_to_drawtext("#f4ead6") == "0xf4ead6"


def test_caption_filter_uses_style_values(tmp_path):
    import pipeline.assemble as assemble

    save_style(tmp_path, PRESETS["retro-pixel"])
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    filt = assemble._subtitle_filter("s.srt", srt, style=json.loads(
        (tmp_path / "style.json").read_text()))
    assert "FontSize=20" in filt          # retro-pixel caption_size
    assert "Outline=3" in filt            # retro-pixel caption_outline
    assert assemble._hex_to_ass(PRESETS["retro-pixel"]["palette"]["fg"]) in filt


def test_caption_filter_without_style_keeps_todays_values(tmp_path):
    import pipeline.assemble as assemble
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    filt = assemble._subtitle_filter("s.srt", srt, style={})
    assert "FontSize=18" in filt
    assert "Outline=2" in filt
    assert "MarginV=40" in filt


def test_overlay_filter_uses_style_values():
    import pipeline.assemble as assemble
    if assemble._FONT is None:
        pytest.skip("no drawtext font discovered on this machine")
    filt = assemble._overlay_filter("Hello", style=PRESETS["noir"])
    assert "fontsize=56" in filt          # noir overlay_size
    assert "borderw=4" in filt            # noir overlay_border
    assert assemble._hex_to_drawtext(PRESETS["noir"]["palette"]["fg"]) in filt


def test_overlay_filter_without_style_keeps_todays_values():
    import pipeline.assemble as assemble
    if assemble._FONT is None:
        pytest.skip("no drawtext font discovered on this machine")
    filt = assemble._overlay_filter("Hello", style={})
    assert "fontsize=58" in filt
    assert "fontcolor=white" in filt
    assert "borderw=3" in filt
