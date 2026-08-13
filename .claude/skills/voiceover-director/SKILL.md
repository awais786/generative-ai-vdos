---
name: voiceover-director
description: Running stage 3 of a video production — generating narration audio and the word timings captions depend on. Use when producing a video and about to run pipeline.voiceover, when audio is missing for a scene, or when captions are mistimed. Triggers include stage 3, voiceover, narration, TTS, edge-tts, words.json, NoAudioReceived, caption timing, voice.
---

# Stage 3 — Voiceover

**Command:** `python -m pipeline.voiceover`
**Produces:** `audio/scene_NN.mp3` and `audio/scene_NN.words.json`
**Gate:** none — runs after image approval.

For voices, per-scene dialogue voices, and provider details, read the
`voiceover-tts` skill. This file covers running the stage.

## Before running

edge-tts is free and needs no key, but it **does** need a network. If
preflight showed it missing, fix that before starting — there is no fallback.

Default voice is `en-US-AndrewNeural` (`DEFAULT_VOICE`). Override with `--voice`.
Note `NARRATOR_VOICE` in `.env` is read only by the one-shot `python -m pipeline.run`
path — `python -m pipeline.voiceover` ignores it, so pass `--voice` explicitly here.
Per-scene `voice` in `shot_plan.json` overrides both.

## What "good" looks like

- **Every scene has both files.** A missing `.words.json` means captions for
  that scene will be absent or mistimed — the word timings come from
  `boundary="WordBoundary"` and nothing else regenerates them.
- **Scene durations come from these mp3s**, measured in `assemble.py`. They
  are never taken from the plan, so a too-long narration silently stretches
  that scene. Check for outliers before assembling.

## When it fails

`NoAudioReceived` is usually a transient network issue or a text edge case, not a bug.

Re-running the stage regenerates **every** scene — there is no skip-if-exists check
(`pipeline/voiceover.py:100-138`), so it overwrites mp3s and `.words.json` for scenes
that were already fine, and can shift their caption timings.

The CLI has no per-scene flag — `python -m pipeline.voiceover` regenerates every
scene. The one sanctioned exception to Rule Zero is a single-purpose call for a
targeted retry:

    python -c "from pathlib import Path; from pipeline.schema import ShotPlan; \
from pipeline.voiceover import generate_voiceover; \
w=Path('output/<name>'); \
generate_voiceover(ShotPlan.model_validate_json((w/'shot_plan.json').read_text()), \
w/'audio', scene_indices=[N])"

Announce it before running. If several scenes failed, re-running the whole stage
is simpler — say so, and note it will shift caption timings on scenes that were fine.

If one scene fails repeatedly, report it rather than switching TTS providers.
