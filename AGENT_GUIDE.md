# Agent Guide — Producing a Video

Read this before making, creating, or producing any video. It is a contract,
not documentation. For working *on* the codebase, see `CLAUDE.md`.

## Mandatory preflight — skip this and assemble fails after you've already paid

Before any creative work:

    python -m pipeline.registry

This reports what actually works on this machine. Never start a run without
it — a missing libass means the final assemble step fails *after* every image
and voiceover has been generated and paid for.

Preflight reports **configuration, not liveness**. An entry marked
"configured" means the key is present, not that it works. Say so when you
report it, so a first-call auth failure is not a surprise.

To actually verify the OpenAI key before spending:

    scripts/check-openai-key

It authenticates via `GET /v1/models`, which costs nothing and generates
nothing, and confirms the plan and image models are available to the account.
Run it when preflight says "configured" but a call fails with a 401 — a revoked
or rotated key reads as configured and fails only on first use.

## Rule Zero — every video goes through five stages

    python -m pipeline.refine "idea"     # stage 1 — shot plan
    python -m pipeline.images            # stage 2 — one image per scene
    python -m pipeline.voiceover         # stage 3 — narration + word timings
    python -m pipeline.compose           # stage 3.5 — title/quote cards ($0, skips if none)
    python -m pipeline.assemble          # stage 4 — final.mp4

Do NOT write ad-hoc scripts that import pipeline internals, call provider APIs
directly, or skip a stage. The stages encode ordering, fallback, and money
rules that improvised code silently loses. The single documented exception is
the voiceover per-scene retry described in the `voiceover-director` skill —
it must still be announced before running.

**Never use `python -m pipeline.auto`, or `pipeline.run --approve` /
`AUTO_APPROVE=1`, when producing a video for a user.** They pre-approve Gate 1
and run every stage unattended, which defeats the review gates entirely. Use
the five stage commands.

Each stage defaults to the most recently touched `output/*/` folder. Pass a
folder to target an older video.

## Announce before you spend

Before the first generation call, state:

- the stage and the command you will run,
- the backend and model,
- whether it is free or paid, and the estimated cost,
- whether it is one sample scene or the full run.

Wait for approval on anything paid. Free defaults (qwen-image, edge-tts, and
the plan model preflight reported — `gpt-4o-mini` is ~$0.001; other
`LLM_PROVIDER` choices differ) still get announced, but do not need approval.

## Review gates — stop and show

**Gate 1 — after the plan.** Show `shot_plan.json`. Wait.
Revise with `python -m pipeline.refine --change "..."`, not by hand-editing,
so auto-polish and consistency review re-run.

**Gate 2 — after the images.** Show the generated images. Wait.
Regenerate a single scene rather than the whole set when only one is wrong.

Voiceover and assemble run without a gate once images are approved.

## Money rules

- **Never run `pipeline.video`** (Wan animation) unless the user explicitly
  asks. It spends limited DashScope credit. The stage is disabled in code;
  do not uncomment `pipeline/video/__main__.py`.
- **`gpt-image-1` is never auto-selected.** It requires an explicit
  `--backend gpt-image-1`. Qwen (free) is the default first choice.
- **`flux-schnell` is not free past its free tier** (~$0.003/image), and unlike
  `gpt-image-1` it *is* auto-pickable and sits in the per-scene fallback chain.
  If preflight shows it as `~ metered`, say so before announcing a run as free:
  a scene that fails on Qwen can fall through to it and spend.
- Do not add a paid backend to a run that was planned as free.

## When something breaks

Report in this shape, then **stop**:

1. What was attempted (the exact command).
2. What failed (the actual error, not a paraphrase).
3. Whether it is auth, provider access, a tool bug, or prompt/design quality.
4. What options exist.
5. Which one you recommend, and why.

Do not swap backends, retry against a paid provider, or write a workaround
script without approval. `state.json` records only the plan stage
(`pipeline.refine`) and the one-shot `pipeline.run` path. Re-running a stage
command regenerates **every** scene from scratch — nothing is skipped and
nothing resumes. After a partial failure, regenerate only the failed scene
(see that stage's director skill).

## Stage map

| Stage | Command | Reads | Writes | Read first |
|---|---|---|---|---|
| 1 plan | `pipeline.refine` | the idea | `shot_plan.json` | `plan-director` skill |
| 2 images | `pipeline.images` | `shot_plan.json` | `images/scene_NN.png` | `images-director` skill |
| 3 voice | `pipeline.voiceover` | `shot_plan.json` | `audio/scene_NN.mp3` + `.words.json` | `voiceover-director` skill |
| 3.5 compose | `pipeline.compose` | `shot_plan.json` + `audio/scene_NN.mp3` | `video/scene_NN.mp4` | `compose-director` skill |
| 4 assemble | `pipeline.assemble` | all of the above | `final.mp4` | `assemble-director` skill |

Read the stage's director skill **before** running that stage. The directors
carry the failure modes that are invisible until the video is finished.
