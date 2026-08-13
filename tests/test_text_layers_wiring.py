"""The redundancy predicate must actually reach the filtergraph.

Both assertions here can pass for the wrong reason, so both have a positive
control alongside them:

  - _overlay_filter returns '' when _FONT is None, so "no drawtext" is true on
    any machine without the font. _FONT is monkeypatched.
  - _subtitle_filter returns '' when the SRT is empty, and _build_scene_srt
    writes nothing for empty words.json. Real word timings are written.
"""
import json
from pathlib import Path

import pytest

import pipeline.assemble as assemble_mod
from pipeline.schema import ShotPlan

WAVE = "Everyone has a wave coming. Yours is out there too, past the horizon."
QUOTE = "The real treasure was the journey itself."


def _words(text: str) -> list[dict]:
    """edge-tts-shaped word timings, so _build_scene_srt writes a real SRT."""
    return [{"text": w, "start": i * 0.4, "duration": 0.4}
            for i, w in enumerate(text.split())]


def _work_dir(tmp_path: Path, narration: str) -> Path:
    for sub in ("images", "audio", "video"):
        (tmp_path / sub).mkdir()
    (tmp_path / "images" / "scene_00.png").write_bytes(b"png")
    (tmp_path / "audio" / "scene_00.mp3").write_bytes(b"mp3")
    (tmp_path / "audio" / "scene_00.words.json").write_text(json.dumps(_words(narration)))
    return tmp_path


def _filtergraph(plan: ShotPlan, work_dir: Path, monkeypatch) -> str:
    """Run assemble() with ffmpeg stubbed; return the per-scene filter_complex."""
    graphs: list[str] = []

    def fake_run(cmd, cwd=None, timeout=None, tag=None):
        if "-filter_complex" in cmd:
            graphs.append(cmd[cmd.index("-filter_complex") + 1])
        out = Path(cmd[-1])
        if not out.is_absolute():
            out = Path(cwd or ".") / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"mp4")
        return 0.0

    monkeypatch.setattr(assemble_mod, "_run", fake_run)
    monkeypatch.setattr(assemble_mod, "_duration", lambda p: 2.0)
    monkeypatch.setattr(assemble_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    # Trap 1: without a font, _overlay_filter returns '' regardless of suppression.
    monkeypatch.setattr(assemble_mod, "_FONT", "/fake/Font.ttf")

    assemble_mod.assemble(plan, work_dir)
    assert graphs, "assemble() built no filtergraph"
    return graphs[0]


def _plan(scene: dict) -> ShotPlan:
    return ShotPlan.model_validate({
        "title": "Test", "description": "Test video.", "tags": ["test"],
        "music_mood": "calm", "style_prefix": "photo", "scenes": [scene],
    })


def test_redundant_overlay_is_not_drawn(tmp_path, monkeypatch):
    plan = _plan({"media_prompt": "a", "narration": WAVE,
                  "on_screen_text": "Everyone has a wave coming"})
    graph = _filtergraph(plan, _work_dir(tmp_path, WAVE), monkeypatch)
    assert "drawtext" not in graph
    assert "subtitles" in graph, "the subtitles must survive — they win over the overlay"


def test_independent_overlay_is_drawn(tmp_path, monkeypatch):
    # Positive control for trap 1: proves the absence above is suppression,
    # not a missing font.
    plan = _plan({"media_prompt": "a", "narration": WAVE,
                  "on_screen_text": "Why is the Sky Blue?"})
    graph = _filtergraph(plan, _work_dir(tmp_path, WAVE), monkeypatch)
    assert "drawtext" in graph


def test_redundant_card_drops_the_subtitles(tmp_path, monkeypatch):
    plan = _plan({"media_prompt": "a", "narration": QUOTE,
                  "compose": {"template": "quote", "heading": QUOTE}})
    work_dir = _work_dir(tmp_path, QUOTE)
    (work_dir / "video" / "scene_00.mp4").write_bytes(b"mp4")  # the rendered card
    graph = _filtergraph(plan, work_dir, monkeypatch)
    assert "subtitles" not in graph


def test_independent_card_keeps_the_subtitles(tmp_path, monkeypatch):
    # Positive control for trap 2: proves the absence above is suppression,
    # not an empty SRT.
    plan = _plan({"media_prompt": "a", "narration": QUOTE,
                  "compose": {"template": "lower_third", "heading": "Dr. Sarah Chen"}})
    work_dir = _work_dir(tmp_path, QUOTE)
    (work_dir / "video" / "scene_00.mp4").write_bytes(b"mp4")
    graph = _filtergraph(plan, work_dir, monkeypatch)
    assert "subtitles" in graph
