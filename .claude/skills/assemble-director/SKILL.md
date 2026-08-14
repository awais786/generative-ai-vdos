---
name: assemble-director
description: Running stage 4 of a video production — rendering the final mp4 from images, audio, captions and music. Use when producing a video and about to run pipeline.assemble, or when the final render fails or looks wrong. Triggers include stage 4, assemble, final.mp4, render, captions, subtitles, music, ffmpeg failed, libass.
---

# Stage 4 — Assemble

**Command:** `python -m pipeline.assemble [--music FILE]`
**Produces:** `output/<name>/final.mp4`
**Gate:** none — this is the deliverable.

For the ffmpeg filter graph, Ken Burns motion, drawtext, and music mixing,
read the `ffmpeg-assembly` skill. For title and quote cards, read
`remotion-compose`. This file covers running the stage.

## Before running

**Check that preflight reported libass available.** `assemble.py` verifies
that ffmpeg exists but not that it can render subtitles, so a plain Homebrew
ffmpeg on macOS fails at the very last step — after every image and voiceover
has already been generated and paid for.

If libass is missing: `brew install ffmpeg-full && brew link --overwrite
ffmpeg-full`. Do not work around it by disabling captions without asking.

Run `python -m pipeline.compose` first if any scene has a `compose` spec.
`no image or clip for scene(s) N` usually means a compose scene was never
rendered — `pipeline.images` skips compose scenes, so re-running it will never
fix that case. But the same error equally means an ordinary scene's image is
just missing: if scene N has no `compose` spec in `shot_plan.json`, then an
image really is missing and `pipeline.images` is the right fix.

Confirm every scene has an mp3 first. Scene durations are measured from
those files; a missing one changes the whole timeline.

## What "good" looks like

- Captions appear and track the narration.
- No scene sits visibly too long or too short against its narration.
- Music, if used, sits under the voice rather than competing with it.
- CC-BY tracks in `music/` require attribution — see
  `music/ATTRIBUTION.txt`.

## When it fails

ffmpeg errors are long; the useful part is the last few lines. Report the
actual error. Common causes, in order: missing libass, a scene missing its
mp3, and unescaped characters in drawtext text.

## After it renders

`final.mp4` existing is not the same as the video being good. Read the
`final-video-qa` skill and run its checklist before showing it to anyone: every
scene has audio, captions burned in, cards rendered, duration inside 4-8s per
scene, and the music matched its mood rather than falling back at random.

Re-assembly is free, so there is no reason to ship a video that fails it.
