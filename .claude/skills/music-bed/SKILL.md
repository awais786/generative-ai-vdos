---
name: music-bed
description: The background music library — how a track is chosen from music_mood, the mood alias map, adding tracks or moods, licensing and attribution, and debugging a soundtrack that fights the video. Use when a video gets music from the wrong mood, when adding music, when the assemble stage warns about a missing mood folder, or when choosing music_mood in a plan. Triggers include music, music_mood, soundtrack, background track, wrong music, random fallback, MOOD_ALIASES, music folder, attribution, CC-BY, --music.
---

# The music bed

`assemble.py` scores every video from `music/<mood>/*.mp3`, picked at random
within the folder that matches `ShotPlan.music_mood`. It is free, local, and
the only stage output the user hears before they see anything.

## How a track is chosen

1. `resolve_mood()` — the mood itself if `music/<mood>/` exists, else its entry
   in `MOOD_ALIASES`, else the mood unchanged.
2. `choose_music()` — a random `.mp3` from that folder.
3. No folder and no alias → **a random track from any mood**, and
   `music_report()` warns, naming the missing folder and the moods that exist.

`--music path/to/track.mp3` overrides all of it.

## Why the alias map exists

The model writes whatever adjective suits the video; the library will never
cover the whole language. Measured across 30 plans in `output/`:

| Mood written | Videos | Folder? |
|---|---:|---|
| `inspiring` | **9** | never existed |
| `calm` | 6 | ✓ |
| `upbeat` | 6 | ✓ |
| `dramatic` | 5 | ✓ |
| `melancholic` | 2 | no |
| `mysterious` | 1 | no |

**The single most-picked mood had no folder**, so all nine of those videos drew
a random track from an unrelated one — a bee documentary scored with a heist
theme. With `melancholic` and `mysterious` that was 12 of 30 videos, 40%.

`MOOD_ALIASES` in `pipeline/assemble.py` maps the vocabulary onto the six
folders that exist. After it: 30 of 30 match.

**A real folder always beats its alias.** Stocking `music/inspiring/` later
just works — no table edit.

## Adding to the library

- **A new track:** drop the `.mp3` into `music/<mood>/`. Nothing to register.
- **A new mood:** create `music/<mood>/` with at least one `.mp3`. An empty
  folder is not a mood — `choose_music()` requires a track in it.
- **A new adjective:** add it to `MOOD_ALIASES` pointing at a folder that
  **exists**. An alias to a missing folder is worse than none: it looks handled
  and silently falls through to random. A test enforces this.

## Licensing — this one bites

`music/` is **gitignored**, so the library is per-clone and never shipped.
CC-BY tracks require attribution: record every track in
`music/ATTRIBUTION.txt` as you add it, with the source URL and licence. A video
published without it is a licence breach, and nothing in the pipeline checks.

## When the soundtrack is wrong

- **Fights the narration** — check the run header. `RANDOM FALLBACK` means the
  mood missed; add the alias or the folder. A *matched* mood that still feels
  wrong is a plan problem: revise `music_mood` with
  `pipeline.refine <dir> --change "make the music mood calm"`.
- **Drowns the voiceover** — mix levels are in `assemble.py`; see
  `ffmpeg-assembly`.
- **Different track every render** — expected. Selection is `random.choice()`
  within the folder. Pin one with `--music` when it matters.
- **No music at all** — `music/` is empty or absent. The run says so and the
  video is narration-only, which is valid.
