---
name: ffmpeg-assembly
description: How this repo's FFmpeg assembly stage (pipeline/assemble.py) works and how to modify or debug it. Use when editing assembly, Ken Burns motion, captions/subtitles, on-screen text overlays, music mixing, scene timing, or debugging a failed ffmpeg render. Triggers include assemble, final.mp4, zoompan, Ken Burns, drawtext, subtitles, srt, captions, amix, music bed, concat, ffprobe, libass.
---

# FFmpeg Assembly (Stage 4)

`pipeline/assemble.py` turns per-scene assets in `output/<slug>/` into `final.mp4`, entirely locally via `subprocess` — no re-generation costs, safe to re-run any time.

## The four passes

1. **Per-scene clip** (`clips/scene_NN.mp4`) — Ken Burns over the still image, OR loop/trim the animated clip if `video/scene_NN.mp4` exists.
2. **Concat** — a `concat.txt` list file + `ffmpeg -f concat -safe 0 -c copy` → `video_raw.mp4`. Stream-copy: no re-encode, so all scene clips must share codec/resolution/fps (they do — every pass encodes libx264, 1920x1080, `FPS = 30`).
3. **Captions** — edge-tts word timings → `captions.srt` → burned with the `subtitles=` filter.
4. **Music mix** — optional music bed ducked under the voiceover → `final.mp4`.

## Timing law: audio drives everything

Scene duration = `ffprobe` on `audio/scene_NN.mp3` **+ 0.3s breath**. Never take durations from the shot plan — the plan has no durations by design. If you change the breath, change it in `pipeline/compose/__init__.py` (`BREATH`) too, or compose-track cards will be trimmed/padded wrongly.

Duration probe recipe:

```bash
ffprobe -v quiet -show_entries format=duration -of csv=p=0 file.mp3
```

## Ken Burns (still-image path)

`_KB_MODES` holds 6 `(zoom_expr, x_expr, y_expr)` zoompan patterns cycled per scene index (`i % 6`): zoom-in center, zoom-out center, pan L→R, pan R→L, zoom-in top-left, zoom-in bottom-right. Adding a mode = appending a tuple; the cycle picks it up.

Key mechanics:

- The still is upscaled to **2304x1296 before zoompan** (`scale=2304:1296`), then zoompan renders at `s=1920x1080`. The oversize input gives zoompan sub-pixel room — without it, pans jitter visibly.
- `on` = output frame number; zoom rate `0.0008*on` at 30fps ≈ 2.4%/second — keep rates in this range or motion looks mechanical.
- Zoom-out mode starts at `1.20` and decreases; floor is implicitly 1.0 for these durations.
- Fade in/out: `0.3s`, capped at `12%` of clip duration so short scenes don't over-fade.
- `-loop 1 -framerate 30 -i still.png` makes a video stream from one image; `[1:a]apad` pads audio so `-t` can trim both streams to the exact duration.

## Animated-clip path

If `video/scene_NN.mp4` exists (from the animate stage or compose track), it always wins over the still:

```
-stream_loop -1 -i clip.mp4        # loop forever (clip may be shorter than narration)
scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080   # cover-fit
-t <narration+0.3>                 # trim to narration length
```

## drawtext overlays (`on_screen_text`)

`_overlay_filter()` renders the scene's `on_screen_text` top-center. drawtext's filtergraph parser is fragile — the escaping order matters:

1. Backslash first (`\` → `\\`) so later escapes aren't doubled.
2. Newlines/CR → spaces (parser chokes on them).
3. `'` → `’` (typographic — cheaper than escaping quotes inside a quoted value).
4. Escape `:`  `%`  `[`  `]`.

Font is the first existing file from a fallback list (macOS Arial Bold / Helvetica, Linux DejaVu). No font found → overlay silently skipped, not an error.

## Captions

`_build_srt()` chunks each scene's `audio/scene_NN.words.json` (word-level timings from edge-tts) into **~4-word SRT entries**, offsetting each scene's timestamps by the accumulated duration of prior scenes. Changing caption density = the `>= 4` chunk size.

Burning uses `subtitles=captions.srt:force_style='FontSize=18,Bold=1,Outline=2,MarginV=40'`. This filter **requires libass** — plain Homebrew `ffmpeg` lacks it; macOS needs `brew install ffmpeg-full`. Symptom without it: "No such filter: 'subtitles'".

### The cwd gotcha (do not "fix" this)

The final pass runs with `cwd=work_dir` so the subtitles filter can reference `captions.srt` by bare filename (the filter's path parsing mangles absolute paths with `:` badly). Consequence: **every other path argument in that command must be absolute** (`.resolve()`). If you add an input/output to the final pass, resolve it.

## Music mix

```
[1:a]volume=0.12[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=2
```

- `volume=0.12` = the duck level for the bed. `duration=first` ends the mix with the voice track; `-stream_loop -1` on the music input loops short tracks; `-shortest` guards the container.
- `pick_music(music_root, mood)` picks a random `.mp3` from `music/<music_mood>/`, falling back to any track under `music/`. Mood dirs match the plan's `music_mood` vocabulary: calm, upbeat, dramatic, mysterious, inspiring.
- CC-BY tracks in `music/` need attribution — see `music/ATTRIBUTION.txt`.

## Debugging failed renders

`_run()` raises `RuntimeError` containing the full command + **last 2000 chars of stderr** — the actual ffmpeg error is at the end of stderr, so read the exception message before re-running anything. Common causes:

| Symptom | Cause |
|---|---|
| `No such filter: 'subtitles'` | ffmpeg without libass — install `ffmpeg-full` |
| `no voiceover for scene(s) [...]` | run `python -m pipeline.voiceover <work_dir>` first |
| `no image or clip for scene(s) [...]` | run `python -m pipeline.images <work_dir>` first |
| Garbled/failed drawtext | text with unescaped `:` `%` `[` `]` — check `_overlay_filter` escaping |
| Concat output has broken timestamps | scene clips with mismatched codec/fps (a hand-made clip snuck in) — re-encode it to libx264/30fps/yuv420p first |

## Generic recipes (for new code in this repo)

Safe encode flags this pipeline standardizes on — reuse them for any new video output:

```bash
-c:v libx264 -preset fast -pix_fmt yuv420p -c:a aac -ar 44100
```

`yuv420p` = plays everywhere (QuickTime, browsers); without it many players show black.

```bash
# Web-ready compression (lower CRF = better quality; 23 default, 28 preview-grade)
ffmpeg -i in.mp4 -c:v libx264 -crf 23 -preset medium -c:a aac -b:a 128k -movflags faststart out.mp4

# Fit inside 1920x1080 with letterbox bars
-vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"

# Cover-fill 1920x1080 (crop overflow) — what assemble.py uses
-vf "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080"
```

`-movflags faststart` moves the moov atom to the front so web playback starts before full download — add it to anything served over HTTP.
