"""Every path handed to ffmpeg must be absolute.

The per-scene ffmpeg calls run with `cwd=work_dir` so libass can resolve the
SRT from a clean relative path. That makes every other path in those commands
relative to work_dir as well — so a relative work_dir sends ffmpeg looking for
`work_dir/work_dir/images/scene_00.png` and the render dies with
"Error opening input file", after every image and voiceover is already paid for.

This is the rule CLAUDE.md states as "ffmpeg path args must be absolute
(.resolve()) when cwd=work_dir". It regressed once when cwd=work_dir was added
to the scene loop without resolving the inputs, which broke every documented
CLI invocation (`make example`, the README, refine.py's own printed next steps)
while leaving the celery path working, because that one already passes an
absolute path.
"""
import json
import os
from pathlib import Path

import pytest

import pipeline.assemble as assemble_mod
from pipeline.schema import ShotPlan


def _plan() -> ShotPlan:
    return ShotPlan.model_validate({
        "title": "Test",
        "description": "Test video.",
        "tags": ["test"],
        "music_mood": "calm",
        "style_prefix": "photo",
        "scenes": [{"media_prompt": "a", "narration": "hello"}],
    })


def _work_dir(tmp_path: Path) -> Path:
    """A work dir with the files assemble() requires present."""
    for sub in ("images", "audio", "video"):
        (tmp_path / sub).mkdir()
    (tmp_path / "images" / "scene_00.png").write_bytes(b"png")
    (tmp_path / "audio" / "scene_00.mp3").write_bytes(b"mp3")
    (tmp_path / "audio" / "scene_00.words.json").write_text(json.dumps([]))
    return tmp_path


def test_ffmpeg_inputs_are_absolute_when_work_dir_is_relative(tmp_path, monkeypatch):
    # Invoke exactly the way the docs and Makefile do: a path relative to cwd.
    work_dir = _work_dir(tmp_path)
    monkeypatch.chdir(work_dir.parent)
    relative = Path(work_dir.name)

    calls: list[tuple[list[str], object]] = []

    def fake_run(cmd, cwd=None, timeout=None, tag=None):
        calls.append((cmd, cwd))
        # Materialise whatever output path this command claims to write, so the
        # next stage of assemble() finds it.
        out = Path(cmd[-1])
        if not out.is_absolute():
            out = Path(cwd or ".") / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"mp4")
        return 0.0

    monkeypatch.setattr(assemble_mod, "_run", fake_run)
    monkeypatch.setattr(assemble_mod, "_duration", lambda p: 2.0)
    monkeypatch.setattr(assemble_mod.shutil, "which", lambda name: f"/usr/bin/{name}")

    assemble_mod.assemble(_plan(), relative)

    assert calls, "assemble() ran no ffmpeg commands"

    offenders = []
    for cmd, cwd in calls:
        if cwd is None:
            continue  # no cwd set: relative paths resolve normally
        for flag, value in zip(cmd, cmd[1:]):
            if flag != "-i":
                continue
            # The subtitles filter deliberately uses a relative path; -i inputs
            # are the ones that must be absolute.
            if not os.path.isabs(value):
                offenders.append((value, cwd))

    assert not offenders, (
        "ffmpeg -i inputs must be absolute when cwd is set; got relative: "
        f"{offenders}"
    )


def test_subtitle_filter_stays_relative(tmp_path, monkeypatch):
    # The SRT path is intentionally relative — libass parses the filter string
    # itself and chokes on absolute paths containing ':' on some platforms.
    # Resolving it along with the inputs would trade one bug for another.
    work_dir = _work_dir(tmp_path)
    (work_dir / "audio" / "scene_00.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")

    filt = assemble_mod._subtitle_filter("audio/scene_00.srt",
                                         work_dir / "audio" / "scene_00.srt")
    if filt:
        assert "audio/scene_00.srt" in filt
        assert str(work_dir) not in filt
