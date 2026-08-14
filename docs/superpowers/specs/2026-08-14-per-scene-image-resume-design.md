# Per-Scene Resume for the Images Stage

**Date:** 2026-08-14
**Status:** Approved, ready for implementation

## Problem

The images stage is the only stage that costs money, and it is the one with no
partial recovery. `generate_images()` writes every scene unconditionally — there
is no skip-if-exists check anywhere in its loop — and `pipeline/run.py` records
completion **per stage**, appending `"images"` to `state["done"]` only after the
whole stage returns.

So a stage that dies on scene 6 of 8 records nothing, and the re-run regenerates
all eight. **The five that already succeeded are billed twice.**

`character_refs()` in the same module already caches by file existence
(`if not p.is_file()`), and `generate_images()` already counts only uncached
portraits for its cost line, with the comment *"so a re-run reports what it will
actually spend."* Scene images never got the same treatment.

## Why this is now worse than it was

`generate_scene_image()` takes `fallback=backend is None`. With an auto-picked
backend a failing scene falls through the provider chain and the run completes
with a placeholder. **An explicit `--backend` disables fallback**, so one bad
scene kills the stage.

On 2026-08-13 the money-rule fix made `IMAGE_BACKEND` unable to select a paid
backend, which means the paid path now *requires* `--backend gpt-image-1`. That
is exactly the path with no fallback and no partial resume. A single moderation
block or transient 500 on scene 6 costs a full re-bill, and can loop.

Neither change was wrong alone; the interaction is what bites.

## Goal

A re-run of the images stage costs only the scenes that are actually missing.

## Non-goals

- **Retries.** Not added here. A permanent failure — a moderation block, a
  malformed prompt — would retry forever, and the web app already has bounded
  retries for the transient case. Making recovery cheap is the fix that helps
  both failure kinds.
- **The web app.** It drives `generate_scene_image` per scene and tracks
  `Scene.media_status` in the database, so it already resumes per scene. This
  gap is CLI-only.

**Removed from Non-goals.** An earlier draft treated the fallback rule as
separable, framed as "falling back to free providers". That framing was wrong:
**there are no free generators.** qwen bills ~$0.025/image after its trial
quota, flux ~$0.003 past its free tier, pexels returns stock photos rather than
your scene, and placeholder draws gradients. Falling back therefore never means
"cheaper" — it means "not the picture you asked for". The rule is designed
below rather than deferred.

## Design

### Fail instead of silently drawing gradients

`get_provider(None)` walks `PROVIDERS` and returns the first `available()` one.
`PlaceholderProvider.available()` is unconditionally `True`, so **with no keys
configured at all, auto-pick returns `placeholder` and the run completes** — a
full video of gradient frames, no error, discovered on playback after the plan
was paid for and every downstream stage ran.

The same applies per scene: with fallback on, a scene that fails on a real
provider falls through to `placeholder`, producing a video that is part
illustration and part gradient. That is worse than a failure, because it looks
like output.

`placeholder` becomes unreachable by auto-pick and by the fallback chain,
exactly as `gpt-image-1` already is — for the opposite reason. `AUTO_EXCLUDE`
means "too expensive to choose silently"; this is "too useless to choose
silently". Both are only ever reached by an explicit `--backend`.

With nothing configured, `get_provider(None)` raises and names what to set:

```
no image backend configured — set one of:
  DASHSCOPE_API_KEY + QWEN_IMAGE_MODEL   (qwen-image)
  REPLICATE_API_TOKEN + REPLICATE_IMAGE_MODEL   (flux-schnell)
  OPENAI_API_KEY + OPENAI_IMAGE_MODEL    (gpt-image-1, paid, needs --backend)
run `python -m pipeline.registry` to see what this machine has.
```

**This is only reasonable because of the resume work below.** Today a failure
loses every scene generated before it, which is why degrading to a gradient is
the lesser evil. Once a re-run costs only the missing scenes, failing early is
free — the two halves of this spec depend on each other.

`make example` is unaffected: it passes `--backend placeholder` explicitly.

### Pending list instead of a full loop

`generate_images()` computes which scenes actually need work:

```python
pending = [i for i, s in enumerate(plan.scenes)
           if not s.compose
           and (redo or not _usable(out_dir / f"scene_{i:02d}.png"))]
```

`_usable(path)` is `path.is_file() and path.stat().st_size > 0`. The size check
is load-bearing: a crash during `path.write_bytes(data)` leaves a zero-byte
file, and `is_file()` alone would call that scene done and skip it forever.

### The cost banner counts pending, not total

`selection_report(..., scenes=len(pending), refs=pending_refs)`.

This matters as much as the skipping. A resumed run that announces eight images
and generates three is the same class of wrong-cost defect shipped twice on
2026-08-13 — first by omitting reference portraits from the count, then by
quoting a price for a model that was not in use.

### Skipping is announced

```
images  gpt-image-1   PAID ~$0.01-0.02/image (gpt-image-1), 3 images
        -> 5 scenes already generated — pass --redo to regenerate them
```

Silent skipping would be the same defect as the silent overlay suppression
found in review: the pipeline making a decision the user cannot see. The note
also names the flag, so the escape hatch is discoverable at the moment it is
wanted rather than in `--help`.

### `--redo`

A flag on `pipeline.images` and `pipeline.run`, threaded to
`generate_images(redo=...)`. It restores today's behaviour: regenerate
everything.

**This changes the default.** Today a bare re-run re-rolls every image, which is
how a user gets a different set. After this it skips them and does nothing
without `--redo`. The safer default is the one that does not spend, matching
`character_refs()`, and the banner advertises the flag every time it skips.

### `--scene N` is unaffected

It runs through `pipeline/images/__main__.py`, not `generate_images()`, and
naming a scene is already an explicit instruction to regenerate it. It never
consults the skip.

## Error handling

A scene that raises propagates and fails the stage — now including a scene that
would previously have degraded to a gradient. The next run re-bills only what is
missing, so the cost of failing is one scene rather than the whole video.

A run with no image backend configured fails **before** generating anything,
rather than after producing a gradient video.

## Testing

All seven run offline and free — no API keys, no spend:

1. **Partial resume** — 3 of 8 images present on disk generates exactly 5.
2. **The banner counts pending** — with 3 present, the header says 5 images, not
   8. This is the assertion that catches the cost regression.
3. **`--redo` regenerates all 8** even when every file is present.
4. **A zero-byte file counts as missing** — the trap `is_file()` alone falls
   into.
5. **No keys configured raises**, naming at least one backend and its env vars,
   rather than returning `placeholder`.
6. **`--backend placeholder` still works**, so `make example` and free offline
   testing are unaffected.
7. **A failing scene does not degrade to a gradient** — with a real backend
   forced or auto-picked, a provider error propagates.

Two existing tests assert the old behaviour and are updated rather than deleted:
`test_get_provider_none_autopicks_first_available` and the placeholder assertion
in `test_image_provider_selection.py`. They pinned "auto-pick returns
placeholder", which is precisely the behaviour being removed.

## Success criteria

1. A stage that fails on scene 6 of 8, re-run, generates 3 scenes and bills for 3.
2. The announced image count equals the number actually generated, always.
3. `--redo` reproduces today's behaviour exactly.
4. `--scene N` still regenerates that scene regardless of what is on disk.
5. A machine with no image keys fails immediately with an actionable message,
   instead of producing a gradient video.
