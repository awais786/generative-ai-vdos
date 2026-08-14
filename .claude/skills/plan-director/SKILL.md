---
name: plan-director
description: Running stage 1 of a video production — turning an idea into shot_plan.json and holding the plan review gate. Use when producing a video and about to run pipeline.refine, when revising a plan, or when deciding whether a plan is good enough to generate images from. Triggers include make a video, produce a video, stage 1, refine, shot plan review, plan gate, revise plan, --change.
---

# Stage 1 — Plan

**Command:** `python -m pipeline.refine "idea"` (auto-polish and consistency
review run automatically — never add a manual polish call)
**Produces:** `output/<name>/shot_plan.json`
**Gate:** YES — show the plan and wait.

For the plan's structure and fields read `shot-plan`; for the narration
itself — length, the hook, and text the TTS can speak — read `scene-script`.
Narration sets every scene's duration, so it is the field to get right here. This file covers running the stage.

## Before running

**If the brief is a bare topic** ("make a video about X"), read the
`creative-intake` skill first and ask before generating — purpose, audience,
length, tone. It composes the brief and picks `--style` / `--seconds` for you.
When the brief already carries those, summarise it back in one sentence and
proceed; intake exists for vague input, not as a toll booth.

Preflight must show an available LLM row. Announce the model **preflight
reported** and its cost before running — `default_model()` resolves from
`LLM_PROVIDER` to `gpt-4o-mini` (~$0.001), `claude-haiku-4-5`,
`gemini-3.1-flash-lite`, or an arbitrary `LITELLM_MODEL`, so do not assume
gpt-4o-mini without checking.

## What "good" looks like

Check these before showing the plan — they are invisible later but ruin the
finished video:

- **Every character appears in `characters`**, described once, and is
  referenced as `{name}` in scene prompts. A character's look must never be
  written inline in a scene prompt. LLMs cannot repeat a description verbatim
  across scenes; `ShotPlan.expand()` is what makes faces consistent.
- **No negated traits in prompts.** Image models draw negated words — "no
  beard" produces a beard. Unwanted traits go in `Character.negative`,
  `scene.negative_prompt`, or `global_negative`.
- **`Character.negative` is set for any absence-defined trait** — bald,
  white-haired, clean-shaven. The pipeline merges it into every scene.
- **Video-wide rules live in `global_negative`**, not repeated per scene.
- **No pose or emotion inside a character description** — those belong in the
  scene prompt.
- **Subscribe/CTA scenes only for listicle-style videos.** Story and dialogue
  videos end on the story's final beat.

## The gate

Show the plan — scene count, the narration beats, the characters. Wait.

Revise **narrative content** — narration, scene order, characters, what a scene
depicts — with `python -m pipeline.refine --change "..."`. Do not hand-edit
those: editing skips auto-polish and consistency review, which is what keeps
characters and story beats coherent across scenes.

**Rendering hints are different and may be edited directly**: `negative_prompt`,
`outfit`, `voice`, `animate`. They are per-scene knobs the polish pass does not
reason about, and `--change` would regenerate the whole plan — re-rolling scenes
that were already approved. After editing one, regenerate only the affected
scene (`--scene N`), not the stage.

The common case: an image comes back with an unwanted subject or mood. That is
an image-level defect, not a plan-level one. Add the unwanted traits to that
scene's `negative_prompt` and regenerate that scene alone.

Advance to stage 2 only after explicit approval.
