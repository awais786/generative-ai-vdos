---
name: voiceover-tts
description: The edge-tts voiceover stage (pipeline/voiceover.py) — free Microsoft neural voices with word-level timestamps that drive captions. Use when working on narration, changing or adding voices, per-scene dialogue voices, debugging missing audio or caption timing, regenerating voiceover for specific scenes, or considering a TTS provider swap. Triggers include voiceover, TTS, edge-tts, voice, narration, WordBoundary, words.json, NoAudioReceived, AndrewNeural, captions timing.
---

# Voiceover / TTS (Stage 3)

`pipeline/voiceover.py` synthesizes per-scene narration with **edge-tts** — free Microsoft neural voices. Outputs per scene: `audio/scene_NN.mp3` + `audio/scene_NN.words.json`. Cost: $0, no API key.

## How it works (and why it's fragile)

There is **no official API**. Microsoft Edge's built-in "Read Aloud" talks to a public websocket (`wss://speech.platform.bing.com/...`) authorized by a token baked into the browser; the `edge-tts` package sends byte-identical traffic, so the server treats it as Edge. Microsoft can rotate the token or throttle non-Edge traffic at any time — the library has tracked such breakages for years.

**If this becomes production-critical**: swap in Azure Speech (same neural voices, official, free 500k chars/month). Stage isolation means only `voiceover.py` changes — keep the `scene_NN.mp3` + `scene_NN.words.json` output contract and nothing downstream notices.

## WordBoundary — the load-bearing detail

```python
edge_tts.Communicate(narration, voice_id, boundary="WordBoundary")
```

`boundary="WordBoundary"` is **required** — the default only emits sentence boundaries. The word events (`offset`/`duration` in 100-nanosecond ticks, converted `/1e7` to seconds) are written to `scene_NN.words.json`, and **captions are built entirely from them** (`_build_srt` in `assemble.py` chunks them into ~4-word SRT entries). No whisper pass, no speech recognition — timing is a synthesis byproduct. Break the words.json contract and captions silently vanish or drift.

## Voices

- Voice id format: `xx-XX-NameNeural` (validated by `_VOICE_RE = ^[a-z]{2}-[A-Z]{2}-.+Neural$`). List available ones: `edge-tts --list-voices`.
- Default narrator: `en-US-AndrewNeural` (`DEFAULT_VOICE`).
- Resolution order (`resolve_voice`): scene's `voice` field → run-wide `--voice` → `DEFAULT_VOICE`. Anything failing the regex is skipped, so a typo'd voice falls back silently rather than erroring.
- Per-scene `voice` in the shot plan is the dialogue mechanism — e.g. a character line in `ur-PK-UzmaNeural` while narration stays on the default. Non-English text works; pick a voice matching the text's language.

## Reliability machinery (don't remove it)

- **Smart-punctuation normalization** (`normalize_tts_text`): curly quotes and em/en dashes occasionally make edge-tts return *no audio at all* — they're translated to ASCII before synthesis. Empty narration raises immediately.
- **Retry with linear backoff** (`synth_scene_with_retry`): 4 attempts on `NoAudioReceived` / `ConnectionError` / `TimeoutError` / `OSError`, sleeping 1.5s x attempt between tries.
- **0.4s pause between scenes** in `generate_voiceover` — avoids edge-tts rate limiting on multi-scene runs.
- `synth_scene_sync` is the blocking wrapper for web workers and Celery tasks (wraps the async retry path in `asyncio.run`).

## Common operations

```bash
python -m pipeline.voiceover                  # whole latest work dir
python -m pipeline.voiceover output/<slug> --voice en-GB-RyanNeural
```

- **Regenerate specific scenes only**: call `generate_voiceover(plan, out_dir, scene_indices=[3, 7])` — invalid indices raise. (The CLI regenerates all scenes; a subset needs the function.)
- After changing a scene's `narration`, regenerate that scene's audio AND re-run assemble — scene duration comes from the mp3, so captions, Ken Burns length, and total runtime all shift.
- Deleting `audio/scene_NN.mp3` and re-running the stage is safe; synthesis is deterministic-ish but not identical run to run.

## Debugging

| Symptom | Cause / fix |
|---|---|
| `NoAudioReceived` persisting past retries | Usually punctuation/emptiness already handled — check narration for exotic unicode; try the text alone with `edge-tts --text "..."` |
| Captions missing / all at 0:00 | `words.json` empty → `boundary="WordBoundary"` was dropped somewhere |
| Wrong voice used | Voice id failed `_VOICE_RE` and silently fell back — check the exact id spelling |
| Every scene fails with connection errors | The unofficial endpoint changed — upgrade `edge-tts` first, consider the Azure swap if it recurs |
