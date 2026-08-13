"""Mood aliases — the most-picked mood in the corpus had no folder.

Measured across 30 plans in output/: `inspiring` is the single most common
music_mood (9 videos) and `music/inspiring/` has never existed, so every one of
those got `random.choice()` from an unrelated folder. A bee documentary was
scored with a heist track. Add `melancholic` and `mysterious` and it is 12 of
30 videos — 40% — picking music that fights the narration.

Aliasing is the right fix rather than new folders: the LLM writes whatever
adjective suits the video, and the library will never cover the whole language.
"""
from pathlib import Path

import pytest

from pipeline.assemble import MOOD_ALIASES, choose_music


def _library(tmp_path: Path, *moods: str) -> Path:
    for m in moods:
        (tmp_path / m).mkdir(parents=True)
        (tmp_path / m / "track.mp3").write_bytes(b"mp3")
    return tmp_path


@pytest.mark.parametrize("asked, folder", [
    ("inspiring", "upbeat"),
    ("melancholic", "sad"),
    ("mysterious", "dramatic"),
])
def test_an_unstocked_mood_resolves_to_a_stocked_one(tmp_path, asked, folder):
    root = _library(tmp_path, "upbeat", "sad", "dramatic", "calm")
    choice = choose_music(root, asked)
    assert choice.path.parent.name == folder
    assert choice.source == "mood", "an aliased hit is a real match, not a fallback"


def test_a_real_folder_always_wins_over_its_alias(tmp_path):
    """If the library gains music/inspiring/, that must be used — the alias is
    a fallback for a gap, not a redirect."""
    root = _library(tmp_path, "upbeat", "inspiring")
    assert choose_music(root, "inspiring").path.parent.name == "inspiring"


def test_an_unknown_mood_still_falls_back_and_says_so(tmp_path):
    root = _library(tmp_path, "upbeat")
    choice = choose_music(root, "klezmer")
    assert choice.source == "fallback", "no alias, no folder — still announced"


def test_matching_is_case_and_space_insensitive(tmp_path):
    root = _library(tmp_path, "upbeat")
    assert choose_music(root, "  Inspiring ").path.parent.name == "upbeat"


def test_every_alias_target_is_a_mood_the_repo_ships():
    """An alias pointing at a folder nobody has is worse than no alias — it
    looks handled and silently falls through."""
    shipped = {d.name for d in Path("music").iterdir() if d.is_dir()} if Path("music").is_dir() else set()
    if not shipped:
        pytest.skip("no music library in this checkout")
    for asked, target in MOOD_ALIASES.items():
        assert target in shipped, f"{asked!r} -> {target!r}, which is not in music/"
