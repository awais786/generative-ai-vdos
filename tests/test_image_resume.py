"""A re-run of the images stage costs only the scenes that are missing.

generate_images() wrote every scene unconditionally, and run.py records
completion per STAGE -- so a failure on scene 6 of 8 recorded nothing and the
re-run regenerated all eight, billing twice for the five that had worked.

character_refs() in the same module already cached by file existence. Scene
images never did.
"""
import json
from pathlib import Path

import pytest

import pipeline.images as images
from pipeline.schema import ShotPlan


def _plan(n=8):
    return ShotPlan.model_validate({
        "title": "T", "description": "d.", "tags": ["t"], "music_mood": "calm",
        "style_prefix": "photo",
        "scenes": [{"media_prompt": f"scene {i}", "narration": f"line {i}"}
                   for i in range(n)],
    })


def _present(out_dir: Path, *indexes, size=64):
    out_dir.mkdir(parents=True, exist_ok=True)
    for i in indexes:
        (out_dir / f"scene_{i:02d}.png").write_bytes(b"x" * size)


def test_only_missing_scenes_are_generated(tmp_path, capsys):
    out = tmp_path / "images"
    _present(out, 0, 1, 2)
    images.generate_images(_plan(8), out, backend="placeholder")
    generated = [ln for ln in capsys.readouterr().out.splitlines()
                 if ln.strip().startswith("images: scene")]
    assert len(generated) == 5, generated


def test_the_banner_counts_pending_not_total(tmp_path, capsys):
    """A resumed run announcing 8 images while generating 3 is the same
    wrong-cost defect shipped twice on 2026-08-13."""
    out = tmp_path / "images"
    _present(out, 0, 1, 2)
    images.generate_images(_plan(8), out, backend="placeholder")
    header = capsys.readouterr().out.splitlines()[0]
    assert "5 scenes" in header, header
    assert "8 scenes" not in header


def test_skipping_is_announced_with_the_escape_hatch(tmp_path, capsys):
    out = tmp_path / "images"
    _present(out, 0, 1, 2)
    images.generate_images(_plan(8), out, backend="placeholder")
    text = capsys.readouterr().out
    assert "3 scenes already generated" in text
    assert "--redo" in text, "the flag must be discoverable when it is wanted"


def test_redo_regenerates_everything(tmp_path, capsys):
    out = tmp_path / "images"
    _present(out, *range(8))
    images.generate_images(_plan(8), out, backend="placeholder", redo=True)
    generated = [ln for ln in capsys.readouterr().out.splitlines()
                 if ln.strip().startswith("images: scene")]
    assert len(generated) == 8, generated


def test_a_zero_byte_file_counts_as_missing(tmp_path, capsys):
    """is_file() is True for the empty file a crash mid-write_bytes leaves
    behind; a naive check would skip that scene forever."""
    out = tmp_path / "images"
    _present(out, 0, 1)
    (out / "scene_02.png").write_bytes(b"")
    images.generate_images(_plan(4), out, backend="placeholder")
    generated = [ln for ln in capsys.readouterr().out.splitlines()
                 if ln.strip().startswith("images: scene")]
    assert len(generated) == 2, generated


def test_nothing_to_do_is_not_an_error(tmp_path, capsys):
    out = tmp_path / "images"
    _present(out, *range(4))
    images.generate_images(_plan(4), out, backend="placeholder")
    text = capsys.readouterr().out
    assert "4 scenes already generated" in text


def test_a_fresh_run_still_generates_everything(tmp_path, capsys):
    """Positive control: the skip must not break the normal first run."""
    out = tmp_path / "images"
    images.generate_images(_plan(5), out, backend="placeholder")
    generated = [ln for ln in capsys.readouterr().out.splitlines()
                 if ln.strip().startswith("images: scene")]
    assert len(generated) == 5, generated
