"""Cross-platform behaviour that cannot be exercised on the dev machine.

Everything here is about Windows and Linux running correctly from a macOS
checkout. The paths are asserted as data rather than probed on disk, because
the machine running these tests has none of the other platforms' fonts.
"""
import sys

import pytest

import pipeline.assemble as assemble_mod
import pipeline.registry as registry_mod


# --- fonts -----------------------------------------------------------------

def test_font_candidates_cover_all_three_platforms():
    """_FONT resolving to None makes _overlay_filter return '' -- so on a
    platform with no candidate, every on_screen_text overlay silently vanishes
    from the finished video. Windows had no entry at all."""
    joined = " ".join(assemble_mod._FONT_CANDIDATES).lower()
    assert "/system/library/fonts" in joined, "macOS"
    assert "/usr/share/fonts" in joined, "Linux"
    assert "windows\\fonts" in joined or "windows/fonts" in joined, "Windows"


def test_font_arg_escapes_a_windows_path():
    r"""ffmpeg parses the filtergraph string itself, so a raw
    C:\Windows\Fonts\arialbd.ttf breaks it twice: ':' separates filter options
    and '\' escapes. Forward slashes plus an escaped drive colon is the form
    ffmpeg accepts."""
    got = assemble_mod._font_arg(r"C:\Windows\Fonts\arialbd.ttf")
    assert got == r"C\:/Windows/Fonts/arialbd.ttf"
    assert "\\W" not in got, "backslash before W would be read as an escape"


def test_font_arg_leaves_posix_paths_alone():
    path = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
    assert assemble_mod._font_arg(path) == path


def test_overlay_filter_uses_the_escaped_font_path(monkeypatch):
    monkeypatch.setattr(assemble_mod, "_FONT", r"C:\Windows\Fonts\arialbd.ttf")
    filt = assemble_mod._overlay_filter("Hello")
    assert r"C\:/Windows/Fonts/arialbd.ttf" in filt
    assert r"C:\Windows" not in filt


# --- install hints ---------------------------------------------------------

@pytest.mark.parametrize("platform, expected", [
    ("darwin", "brew"),
    ("win32", "winget"),
    ("linux", "apt-get"),
])
def test_ffmpeg_hint_is_platform_correct(monkeypatch, platform, expected):
    """Windows fell through to the Linux branch and was told to run apt-get."""
    monkeypatch.setattr(sys, "platform", platform)
    assert expected in registry_mod._ffmpeg_hint()


def test_assemble_ffmpeg_missing_hint_is_not_hardcoded_to_brew(monkeypatch):
    """The raise in assemble() said 'brew install ffmpeg' on every platform,
    while registry.py already branched correctly."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(assemble_mod.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError) as e:
        assemble_mod.assemble(None, "unused")
    assert "brew" not in str(e.value)
    assert "winget" in str(e.value)


# --- the silent overlay loss ----------------------------------------------

def _plan_with_overlay():
    from pipeline.schema import ShotPlan
    return ShotPlan.model_validate({
        "title": "T", "description": "d.", "tags": ["t"], "music_mood": "calm",
        "style_prefix": "photo",
        "scenes": [{"media_prompt": "a", "narration": "hello there",
                    "on_screen_text": "A Label"}],
    })


def _run_assemble(plan, tmp_path, monkeypatch):
    import json
    from pathlib import Path
    for sub in ("images", "audio", "video"):
        (tmp_path / sub).mkdir()
    (tmp_path / "images" / "scene_00.png").write_bytes(b"png")
    (tmp_path / "audio" / "scene_00.mp3").write_bytes(b"mp3")
    (tmp_path / "audio" / "scene_00.words.json").write_text(json.dumps(
        [{"text": "hello", "start": 0.0, "duration": 0.4}]))

    def fake_run(cmd, cwd=None, timeout=None, tag=None):
        out = Path(cmd[-1])
        if not out.is_absolute():
            out = Path(cwd or ".") / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"mp4")
        return 0.0

    monkeypatch.setattr(assemble_mod, "_run", fake_run)
    monkeypatch.setattr(assemble_mod, "_duration", lambda p: 2.0)
    monkeypatch.setattr(assemble_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    assemble_mod.assemble(plan, tmp_path)


def test_assemble_warns_when_no_font_and_overlays_exist(tmp_path, monkeypatch, capsys):
    """_FONT None makes _overlay_filter return '' for every scene, so the
    overlays vanish from the finished video with no error anywhere. That is
    exactly what a Windows box did before the font list covered it."""
    monkeypatch.setattr(assemble_mod, "_FONT", None)
    _run_assemble(_plan_with_overlay(), tmp_path, monkeypatch)
    out = capsys.readouterr().out.lower()
    assert "font" in out and "overlay" in out


def test_assemble_is_quiet_when_a_font_exists(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(assemble_mod, "_FONT", "/System/Library/Fonts/Helvetica.ttc")
    _run_assemble(_plan_with_overlay(), tmp_path, monkeypatch)
    assert "no font" not in capsys.readouterr().out.lower()
