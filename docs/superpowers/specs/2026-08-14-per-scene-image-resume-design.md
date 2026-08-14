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
- **Changing the fallback rule.** Whether an explicit `--backend` should still
  fall back to *free* providers is a real question, and a separate one.

## Design

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

Unchanged. A scene that raises still propagates and still fails the stage. The
only difference is that the next run does not re-bill what already succeeded.

## Testing

All four run offline and free with `--backend placeholder`:

1. **Partial resume** — 3 of 8 images present on disk generates exactly 5.
2. **The banner counts pending** — with 3 present, the header says 5 images, not
   8. This is the assertion that catches the cost regression.
3. **`--redo` regenerates all 8** even when every file is present.
4. **A zero-byte file counts as missing** — the trap `is_file()` alone falls
   into.

## Success criteria

1. A stage that fails on scene 6 of 8, re-run, generates 3 scenes and bills for 3.
2. The announced image count equals the number actually generated, always.
3. `--redo` reproduces today's behaviour exactly.
4. `--scene N` still regenerates that scene regardless of what is on disk.
