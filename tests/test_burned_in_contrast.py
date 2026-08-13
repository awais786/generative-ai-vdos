"""Burned-in text must stay legible whatever the style's card palette is.

`palette["fg"]` is defined in schema.py as "text, high contrast against bg1" —
a CARD colour, chosen against a known background. Captions and overlays are
burned over arbitrary photographs with a dark outline (`bordercolor=black@0.8`,
libass `Outline`), so a dark fg renders dark-on-dark and effectively vanishes.

Six of the seven presets are dark-card designs with a light fg, so this never
showed. Storybook was changed to a light parchment card on 2026-08-13, giving
it fg #3b2a1a — and its captions went dark brown over bright illustrations.
"""
import pytest

import pipeline.assemble as assemble_mod
from pipeline.styles import PRESETS


@pytest.mark.skipif(assemble_mod._FONT is None, reason="no system font here")
def test_dark_card_foreground_is_not_used_for_burned_in_text():
    storybook = PRESETS["storybook"]
    assert storybook["palette"]["fg"] == "#3b2a1a", "guard: the preset changed"

    overlay = assemble_mod._overlay_filter("Off to the forest!", style=storybook)
    subs = assemble_mod._subtitle_filter("audio/scene_00.srt", _SRT, style=storybook)

    assert "0x3b2a1a" not in overlay, "dark card colour must not fill burned-in overlay text"
    assert "fontcolor=white" in overlay
    # libass: a dark PrimaryColour would be the same defect one layer down.
    assert "PrimaryColour" not in subs or "&H00FFFFFF" in subs.upper()


@pytest.mark.skipif(assemble_mod._FONT is None, reason="no system font here")
def test_light_card_foreground_is_still_honoured():
    """Positive control: the fix must not flatten every style to white."""
    cinematic = PRESETS["cinematic"]
    assert cinematic["palette"]["fg"] == "#f4ead6", "guard: the preset changed"
    overlay = assemble_mod._overlay_filter("A Label", style=cinematic)
    assert "0xf4ead6" in overlay


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_every_preset_produces_legible_burned_in_text(name):
    """Whatever a preset's palette, the burned-in fill must be light enough to
    read against the dark outline the filters always apply."""
    overlay = assemble_mod._overlay_filter("Text", style=PRESETS[name])
    if not overlay:
        pytest.skip("no font on this machine")
    colour = overlay.split("fontcolor=")[1].split(":")[0]
    if colour == "white":
        return
    r, g, b = (int(colour[2:][i:i + 2], 16) for i in (0, 2, 4))
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    assert luma >= 140, f"{name}: fill {colour} (luma {luma:.0f}) is too dark to read"


class _SRTStub:
    """_subtitle_filter needs a non-empty SRT to emit anything."""

    def is_file(self):
        return True

    def stat(self):
        class _S:
            st_size = 42
        return _S()


_SRT = _SRTStub()
