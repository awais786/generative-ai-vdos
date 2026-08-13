---
description: Produce a finished video from an idea — intake, plan, images, voiceover, cards, assembly
argument-hint: [what the video should be about]
---

Produce a finished video for: **$ARGUMENTS**

**Run it start to finish. Ask once, then do not stop again.**

[`AGENT_GUIDE.md`](../../AGENT_GUIDE.md) is the operating contract for this
pipeline; this command overrides its per-stage review gates with a single
approval up front. Everything else in it still applies.

## The one place you stop

Show the plan, and in the **same message** state the exact number of images and
what they will cost. That is the only approval you take. After the user
approves, run images → voiceover → compose → assemble to completion and show
the finished video. Do not stop between stages. Do not ask about backends
separately — fold that into the one question.

If a scene comes out wrong, **fix it and keep going** — regenerate that scene
alone, then continue. Report what you fixed at the end rather than pausing to
ask. Only stop early if something is actually blocked, or if a fix would cost
noticeably more than the approved total.

## Order of work

1. **Preflight.** `python -m pipeline.registry`. Read every row: it says which
   backends work here, what each costs, and what is missing. Never assume.

2. **Intake, only when the brief is bare.** Read the `creative-intake` skill.
   If you can reasonably infer purpose, audience, length and tone from the
   request or the conversation, **state your assumptions in one line and
   proceed** rather than asking — that counts as intake. Ask only what you
   genuinely cannot infer.

3. **Stages, in order, through their CLIs** — `refine` → `images` →
   `voiceover` → `compose` (required whenever the plan has a card scene) →
   `assemble`. Each has a director skill worth reading first: `plan-director`,
   `images-director`, `voiceover-director`, `compose-director`,
   `assemble-director`. Never import pipeline internals or call a provider API
   directly.

## Money — the part to get right

Read the Money rules in `CLAUDE.md`. In particular:

- **No image backend is free.** qwen bills about 2.5 cents an image after its
  trial quota, gpt-image-1 about 1-2 cents, gemini about 10 cents.
  `placeholder` is genuinely zero and renders gradients — offer it when the
  user wants to test the flow rather than produce something watchable.
- **`gpt-image-1` and `gemini-image` need an explicit `--backend`.** A value in
  `.env` will not select them; that guard is deliberate.
- **Never run `pipeline.video`** (Wan animation) unless the user asks.
- Count the images before generating. Character reference portraits are billed
  alongside the scenes — the run banner counts both.

## Checking the result

Look at frames; do not describe from the prompt. Extract one with
`ffmpeg -i output/<name>/clips/scene_NN.mp4 -ss 1.0 -frames:v 1 frame.png`.

Ask of every image: **is anything here the story never mentioned?** An invented
person, a second animal, text on a sign. That is the common failure and it is
invisible in the plan — see the `image-backends` and `shot-plan` skills. The
fix is `global_negative` plus a regenerate of only the affected scenes:
`python -m pipeline.images <dir> --scene N`.
