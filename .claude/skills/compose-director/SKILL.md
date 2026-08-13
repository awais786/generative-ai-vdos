---
name: compose-director
description: Running stage 3.5 of a video production — rendering title cards, quote cards, lower thirds, and outros with Remotion. Use when producing a video with any compose scenes, or when a card render fails or looks wrong. Triggers include compose, title card, quote card, lower third, outro, Remotion, stage 3.5, cards.
---

# Stage 3.5 — Compose

**Command:** `python -m pipeline.compose [work_dir]`
**Produces:** `output/<name>/video/scene_NN.mp4`
**Gate:** none — runs after voiceover; no gate.

For templates, palettes, theme mechanics, and card customization, read the
`remotion-compose` skill. This file covers running the stage.

## Before running

Verify `npx` is on PATH and `remotion/node_modules` is present. Missing either
raises a `RuntimeError` with the exact remediation (`cd remotion && npm install`).
Preflight already reports this as the `Compose` row.

Running `pipeline.compose` is always safe — if the plan has no `compose` specs,
it returns immediately without rendering anything.

## What "good" looks like

- Cards render without errors and match the shot plan's template choice.
- Card durations match their narration beats — if a scene has no audio yet,
  fallback durations are used (title_card 4.0s, quote 6.0s, lower_third 4.0s,
  outro 4.0s).
- Text positioning and colors are consistent with the plan's style and mood.

## When it fails

Remotion render errors are usually configuration or text issues. Check:

- Missing `npx` or `node_modules` — run `cd remotion && npm install`.
- Missing narration audio for a card scene — run voiceover first.
- Invalid characters in card text fields (unescaped quotes, newlines in JSON).

Re-run the stage; it will only re-render scenes with `compose` specs.
