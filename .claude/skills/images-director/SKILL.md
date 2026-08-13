---
name: images-director
description: Running stage 2 of a video production — generating one image per scene and holding the image review gate. Use when producing a video and about to run pipeline.images, when a scene image looks wrong, or when choosing an image backend. Triggers include stage 2, generate images, image gate, wrong character, regenerate scene, --backend, qwen, gpt-image-1.
---

# Stage 2 — Images

**Command:** `python -m pipeline.images`
**Produces:** `output/<name>/images/scene_NN.png`
**Gate:** YES — show the images and wait.

For backends, the fallback chain, and character reference portraits, read the
`image-backends` skill. This file covers running the stage.

## Before running

Announce the backend. **Qwen (free) is the default first choice.** Never let
`gpt-image-1` be selected implicitly — it is excluded from auto-pick and from
the fallback chain by `AUTO_EXCLUDE`, and reaching it requires an explicit
`--backend gpt-image-1`, which costs money and needs approval.

If preflight showed only `placeholder` available, say so before running —
the output will be gradient placeholders, not images.

## What "good" looks like

- **The same character looks the same in every scene.** If not, the cause is
  almost always a plan problem, not an image problem — go back to stage 1 and
  check `characters` / `{name}` placeholders.
- **No unwanted trait that was negated in prose.** A beard on a character
  specified as clean-shaven means the trait is in the prompt instead of
  `Character.negative`.
- **Scene matches its narration beat.**

## When one scene is wrong

Regenerate that scene alone — do not re-run the whole stage and re-spend on
scenes that were fine. `--scene` takes the **0-based** scene index:

    python -m pipeline.images [work_dir] --scene N

If Qwen keeps refusing an instruction (strong model priors), regenerate that
one scene with `--backend gpt-image-1`:

    python -m pipeline.images [work_dir] --scene N --backend gpt-image-1

`gpt-image-1` follows instructions much better, but that is a paid call —
announce and get approval first.

## The gate

Show the images. Wait for approval before voiceover.
