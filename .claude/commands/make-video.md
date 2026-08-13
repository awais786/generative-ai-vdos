---
description: Produce a finished video from an idea — intake, plan, images, voiceover, cards, assembly
argument-hint: [what the video should be about]
---

Produce a finished video for: **$ARGUMENTS**

Follow [`AGENT_GUIDE.md`](../../AGENT_GUIDE.md) — it is the operating contract
for this pipeline and it overrides your defaults. The short version:

1. **Preflight first.** Run `python -m pipeline.registry` before anything else
   and read every row. It tells you which backends actually work on this
   machine, what each one costs, and what is missing. Never assume.

2. **Intake, if the brief is bare.** If `$ARGUMENTS` is just a topic, read the
   `creative-intake` skill and ask what the video needs — purpose, audience,
   length, tone — one question at a time, starting with the biggest gap. If the
   brief already carries those, summarise it back in one sentence and proceed.
   Intake exists for vague input, not as a toll booth.

3. **Run the stages, in order, through their CLIs.** Each stage has a director
   skill with its gotchas: `plan-director`, `images-director`,
   `voiceover-director`, `compose-director`, `assemble-director`. Read the one
   for the stage you are about to run. Never import pipeline internals or call
   a provider API directly.

4. **Announce cost before spending, and stop at the two gates.** The plan gate
   and the image gate both need the user's explicit approval before you go on.
   Show them what was produced; do not describe it and move on.

## Money — the part to get right

Read the Money rules in `CLAUDE.md`. In particular:

- **No image backend here is free.** qwen bills ~$0.025/image after its trial
  quota, gpt-image-1 ~$0.01-0.02, gemini ~$0.10. `placeholder` is genuinely
  $0 and renders gradients — offer it when the user wants to test the flow
  rather than produce something watchable.
- **`gpt-image-1` and `gemini-image` need an explicit `--backend`.** `.env`
  alone will not select them; that guard is deliberate.
- **Never run `pipeline.video`** (Wan animation) unless the user asks for it.
- State the actual number of images before generating. Character reference
  portraits are billed too — the run banner counts them.

## When something looks wrong

Show the user a frame rather than describing it: extract one with
`ffmpeg -i output/<name>/clips/scene_NN.mp4 -ss 1.0 -frames:v 1 frame.png` and
read it. A scene that came out wrong is regenerated on its own with
`python -m pipeline.images <dir> --scene N` — never re-run the whole stage and
re-spend on the scenes that were already fine.
