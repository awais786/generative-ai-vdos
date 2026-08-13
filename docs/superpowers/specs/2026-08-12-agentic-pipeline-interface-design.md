# Agentic Pipeline Interface — Design

**Date:** 2026-08-12
**Status:** Approved, ready for implementation planning
**Phase:** 1 of N (later phases: output quality, voice)

## Problem

The video pipeline can only be driven two ways today: by hand on the CLI
(`python -m pipeline.refine|images|voiceover|assemble`), or through the Django +
Next.js web app. Neither lets a coding agent produce a video reliably.

An unguided agent pointed at this repo fails in predictable, silent ways: it writes
`"no beard"` into a prompt and gets a beard, re-describes a character in every scene
and gets twelve different faces, calls a retired image model, spends DashScope credit
without asking, or renders every asset and then dies on the `subtitles` filter because
the machine has no libass.

Every one of those failures is already documented in `CLAUDE.md`. The knowledge exists;
it is written as prose documentation for humans rather than as a contract an agent must
read before acting.

## Goal

Let a developer open this repo in Claude Code and say *"make me a video about X"*, and
get a correct video — with review gates at plan and images, no unapproved spending, and
no silent quality failures.

## Non-goals (phase 1)

- **MCP server.** Deferred. Claude Code with the repo open is the phase-1 client.
  MCP would require a job-handle polling layer, because the image stage runs up to
  10 minutes and the video stage up to 30 — longer than an MCP call can block. It is
  also the layer that carries the least of the repo's hard-won knowledge. If remote or
  multi-user agent access becomes a requirement, MCP wraps the same registry cheaply
  once the registry exists.
- **Output quality and voice work.** Separate, later phases.
- **New capability tools** (more image/video/TTS providers). Out of scope.
- **Changes to the web app.** Untouched.

## Reference

`OpenMontage` (`/Users/awais.qureshi/Documents/devstack/OpenMontage`) is a mature
instruction-driven video repo: ~60 tools, 12 pipeline manifests, 22 artifact schemas,
~100 skill files, and deliberately **no MCP server**. Its load-bearing idea is that
Python holds tools and persistence only — orchestration, creative decisions, and review
policy live in markdown the agent reads. This design borrows that shape at roughly 5%
of the size, sized to one pipeline rather than twelve.

## Findings that shaped the design

Established by reading the codebase, not assumed:

1. **`pipeline/images/__init__.py` already implements the registry pattern** for one
   capability family: `PROVIDERS` ordered by priority, per-provider `available()`,
   `ALIASES` for friendly names, a per-scene fallback chain, and
   `AUTO_EXCLUDE = {"gpt-image-1"}` enforcing a money rule in code. The design extends
   this pattern rather than replacing it.

2. **`pipeline/assemble.py:106` checks `shutil.which("ffmpeg")` but not libass.** On a
   machine with plain Homebrew ffmpeg, all four stages appear to succeed and the
   `subtitles` filter fails at line 203 — after every image and voiceover has been
   generated and paid for. This is the single strongest argument for preflight.

3. **`AGENTS.md` and `.cursorrules` are not agent contracts.** They contain
   auto-generated `code-review-graph` MCP blurbs. They are unusable as-is for routing.

4. **Seven env vars are read by code but absent from `.env.example`:**
   `PEXELS_API_KEY`, `REPLICATE_API_TOKEN`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`,
   `VIDEO_STYLE`, `CELERY_BROKER_URL`, `DASHSCOPE_BASE_URL`.
   (Most other pipeline vars — `LLM_PROVIDER`, `LITELLM_*`, `NARRATOR_VOICE`,
   `IMAGE_BACKEND`, `QWEN_*`, `OPENAI_IMAGE_MODEL` — are present as commented
   entries and need no change.)

5. **`CLAUDE.md` is stale on tests.** It claims "No real test suite — just
   `tests/test_expand.py`"; there are 7 test files, including
   `tests/test_image_provider_selection.py`.

6. **The pipeline core already has two callers** — the CLI (`pipeline/run.py`) and
   Celery (`apps/projects/tasks.py`, `apps/projects/utils.py`). The agent interface
   must reuse the CLI rather than becoming a third parallel wrapper.

## Architecture

Four layers. Only one is new code.

### Layer 0 — Routing

Claude Code auto-loads `CLAUDE.md`, so the five-file router indirection OpenMontage
uses (for five different harnesses) is unnecessary in phase 1.

`CLAUDE.md` currently mixes two audiences: how to work on this codebase (webapp layout,
Django settings, test commands) and how to produce a video (money rules, negative
prompts, character consistency). An agent asked to make a video reads ~200 lines of
Django detail first.

- `CLAUDE.md` stays, trimmed to development concerns, plus one routing line:
  *"If the user asks to make, create, or produce a video, read `AGENT_GUIDE.md` before
  acting."*
- `AGENT_GUIDE.md` (new, repo root) holds the production contract only.

### Layer 1 — Preflight

`pipeline/registry.py` (~150 lines), following the existing stage-CLI convention
(`main()` + `python -m` invocation). Answers one question: *what works on this machine
right now?*

It reads state from the existing provider modules — it does not duplicate their logic.

### Layer 2 — Stage directors

The 5 existing skills in `.claude/skills/` are **tool-level** (`ffmpeg-assembly`,
`image-backends`, `shot-plan`, `remotion-compose`, `voiceover-tts`) — they explain a
component. Four new **stage-level** directors are added, one per pipeline stage. Each
states what the stage must produce, which gate to stop at, what "good" looks like, and
what to verify before advancing. Directors point down into the existing 5 skills for
mechanics; no content is duplicated.

### Layer 3 — Gates

Enforced in code where possible, in the guide where not. See the enforcement matrix
below.

## File inventory

### New (7)

| File | Approx. size | Purpose |
|---|---|---|
| `AGENT_GUIDE.md` | 150 lines | Production contract |
| `pipeline/registry.py` | 150 lines | Preflight |
| `.claude/skills/plan-director/SKILL.md` | 60 lines | Stage 1 director |
| `.claude/skills/images-director/SKILL.md` | 60 lines | Stage 2 director |
| `.claude/skills/voiceover-director/SKILL.md` | 50 lines | Stage 3 director |
| `.claude/skills/assemble-director/SKILL.md` | 60 lines | Stage 4 director |
| `tests/test_registry.py` | 80 lines | Unit tests for preflight (see Testing) |

### Modified (3)

| File | Change |
|---|---|
| `CLAUDE.md` | Trim to dev concerns; add routing line; fix the stale test-suite claim |
| `.env.example` | Add the 7 undocumented vars from finding 4, values empty |
| `pipeline/images/__init__.py` | Add a `describe()` helper so the registry reads provider state instead of reimplementing it |

### Unchanged

`pipeline/schema.py`, all four stage CLIs, `pipeline/run.py`, `state.json` handling,
Celery tasks, the entire web app.

## Component: `pipeline/registry.py`

### Checks

| Group | Check | Source |
|---|---|---|
| LLM (plan) | call `script_agent.default_model()`; it already requires `LLM_PROVIDER` plus that provider's key and raises `RuntimeError` with a remediation message otherwise | `pipeline/script_agent.py` |
| Images | each provider in `PROVIDERS` via its `available()` | `pipeline/images/__init__.py` |
| Video | reports `disabled-by-policy` unconditionally | `pipeline/video/__main__.py` is commented out |
| Voiceover | `edge_tts` importable; network required, no key | import check |
| Compose | `node` on PATH and `remotion/node_modules` present | filesystem |
| Assemble | `ffmpeg` and `ffprobe` on PATH; **libass present** | `shutil.which` + ffmpeg capability probe |
| Config | env vars read by code but unset | env |

### libass detection

`ffmpeg -hide_banner -filters` is parsed for a `subtitles` filter entry. Absence means
captions will fail at `assemble.py:203`. This is reported as a blocking error for any
run that produces captions, not a warning.

### `configured` vs `verified`

`available()` checks that a key is *present*, not that it *works*. A revoked
`DASHSCOPE_API_KEY` still reports as available. The registry therefore labels
API-backed entries **`configured`**, never `verified`, and makes no live network calls —
those cost money and add latency to every run. `AGENT_GUIDE.md` requires the agent to
pass this distinction on to the user, so a first-call auth failure is not a surprise.

> **Correction, from later reviews.** "A key is present" turned out to be the
> wrong bar, in two ways.
>
> **A key alone is not enough to generate.** Every backend also needs a model
> id, and `_gen_model()` raises without it. Since `available()` only saw the
> key, qwen — first in `PROVIDERS` — was auto-picked and then died on scene 1,
> which is the late failure this whole module exists to prevent. Each provider
> now declares an `env_required` tuple covering everything `generate()` needs,
> and the default `available()` checks all of it. `EXTRA_REQUIRED_ENV` in this
> module remains only for the preflight *hint*.
>
> **Do not infer the missing var from `available()`.** `probe_images` derived
> the gap list by parsing `provider.requires`, which is prose for humans
> (`"REPLICATE_API_TOKEN (+ pip install replicate)"`). The result blamed keys
> that were set: with `DASHSCOPE_API_KEY` present and only the model id
> missing, the Images row said the key was unset while the Video row three
> lines below said it was set. The gap list is now derived from the same
> `env_required` tuple, checking each variable directly.
>
> `scripts/check-openai-key` had the matching bug: it tested `gpt-4o-mini`
> regardless of `LLM_PROVIDER`, failing a working Anthropic or Gemini setup
> over a model it never asks OpenAI for. It now checks the plan model only when
> OpenAI is the configured provider.

### Output

Human-readable table on stdout by default; `--json` for machine consumption. Example:

```
LLM (plan)      ✓ gpt-4o-mini via OPENAI_API_KEY          (configured)
Images          ✓ qwen-image      free, default            (configured)
                ✓ flux-schnell    free tier, then paid     (configured)
                ✗ pexels          PEXELS_API_KEY not set
                ✓ placeholder     always
                $ gpt-image-1     paid — explicit --backend only
Video           ⊘ wan2.2-i2v-flash — DISABLED by policy (money rule)
Voiceover       ✓ edge-tts        free, needs network
Compose         ✗ Remotion        node_modules missing → npm install
Assemble        ✓ ffmpeg 7.1
                ✗ libass MISSING  → captions will fail. brew install ffmpeg-full
```

Legend: `✓` available · `✗` unavailable · `$` paid, explicit opt-in only ·
`⊘` disabled by policy.

Exit code is `0` even when entries are unavailable — the registry reports, it does not
gate. The agent decides based on what the run needs.

## Component: `AGENT_GUIDE.md`

Contents, in order:

1. **Rule Zero** — every video production request goes through the pipeline
   stages (plan → images → voiceover → compose → assemble). No ad-hoc scripts
   calling pipeline internals directly.
2. **Mandatory preflight** — run `python -m pipeline.registry` before any creative work.
3. **Decision announcement** — before any generation call, state the stage, the backend,
   the model, whether it is free or paid, the estimated cost, and whether it is a sample
   or a full run. Wait for approval on anything paid.
4. **Review gates** — stop after the plan and after the images. Show the artifacts.
   Wait. (Matches the stated user preference: plan → images → the rest.)
5. **Money rules**, promoted verbatim from `CLAUDE.md`: never run `pipeline.video`
   unprompted; `gpt-image-1` only via explicit `--backend`; Qwen first.
6. **Escalation format** for blockers — what was attempted, what failed, whether it is
   auth / provider access / tool bug / prompt quality, what options exist, which one is
   recommended. Then stop.
7. **No unilateral substitutions** — do not swap backends, retry on a paid provider, or
   write a workaround script when the approved path is blocked.
8. **Stage map** — the four commands, what each consumes and produces, and which
   director skill to read first.

## Component: stage director skills

Each uses the existing `SKILL.md` frontmatter format (`name`, `description` with
trigger terms) already used by the 5 current skills.

| Director | Command | Gate | Points to |
|---|---|---|---|
| `plan-director` | `python -m pipeline.refine "idea"` | **Gate 1** — show `shot_plan.json` | `shot-plan` |
| `images-director` | `python -m pipeline.images` | **Gate 2** — show images | `image-backends` |
| `voiceover-director` | `python -m pipeline.voiceover` | none | `voiceover-tts` |
| `compose-director` | `python -m pipeline.compose` | none | `remotion-compose` |
| `assemble-director` | `python -m pipeline.assemble` | none | `ffmpeg-assembly` |

> **Correction (found during implementation).** This spec originally described the
> pipeline as four stages. `pipeline/run.py:21` actually defines six —
> `["plan", "images", "animate", "voice", "compose", "assemble"]`. `animate` is
> disabled by policy, but `compose` (Remotion title/quote/lower-third/outro cards)
> is a live, documented feature that runs after voiceover and renders into
> `video/scene_NN.mp4`. Omitting it made the manual path fail at
> `pipeline/assemble.py:126` for any plan containing a card, with an error message
> suggesting a fix that cannot work. Five directors, not four.

Each director covers: what the stage must produce, the gate, what "good" looks like,
what to verify before advancing, and the known silent-failure modes for that stage
(e.g. `plan-director` covers negated words, character placeholders, and
`global_negative` placement).

## Flow

For *"make me a video about black holes"*:

1. Claude Code loads `CLAUDE.md` → routing line → reads `AGENT_GUIDE.md`
2. Runs `python -m pipeline.registry`
3. Announces pipeline, image backend (`qwen-image`, free), plan model
   (`gpt-4o-mini`, ~$0.001), and any blockers. **Waits.**
4. Reads `plan-director` → `python -m pipeline.refine "black holes"`
5. **Gate 1** — shows `shot_plan.json`. Waits. Revisions via
   `python -m pipeline.refine --change "..."`
6. Reads `images-director` → `python -m pipeline.images`
7. **Gate 2** — shows the images. Waits.
8. `voiceover` → `assemble` → `output/<name>/final.mp4`

The agent runs the same commands a developer runs by hand. There is no agent-only code
path to maintain or debug.

## Enforcement matrix

| Risk | Enforcement | Strength | Status |
|---|---|---|---|
| Wan animation burns DashScope credit | `pipeline/video/__main__.py` commented out | Hard | Already done |
| Paid `gpt-image-1` auto-selected | `AUTO_EXCLUDE` in `images/__init__.py` | Hard | Already done |
| Run starts on a machine that will fail at assemble | `pipeline/registry.py` | Hard | New |
| Agent skips a review gate | `AGENT_GUIDE.md` | **Soft** | New |
| Agent improvises a script instead of using stages | `AGENT_GUIDE.md` Rule Zero | **Soft** | New |

The two soft rows are a genuine limitation of the instruction-driven approach, shared
by OpenMontage. Partial mitigation: gates land on process boundaries — `refine` and
`images` are separate commands — so skipping a gate requires actively launching the next
command rather than continuing in-process. This is weaker than a lock, and is recorded
here as an accepted risk rather than a solved problem.

## Failure handling

A stage failure does **not** leave resumable progress. `state.json` is written only by
`pipeline.refine` (records `{"done": ["plan"]}`) and the one-shot `pipeline.run` path —
`pipeline.images`, `pipeline.voiceover`, `pipeline.compose`, and `pipeline.assemble`
never read or write it. Re-running any of the four stage commands regenerates every
scene unconditionally (`generate_images` loops all scenes, `generate_voiceover`
likewise); nothing is skipped. The agent reports using the escalation format and
**stops**. It does not swap backends, retry against a paid provider, or write a
workaround script. After a partial failure, regenerate only the failed scene rather
than re-running the whole stage.

*Correction: an earlier draft of this section claimed the same stage command would
resume from `state.json`. That was false and was caught by the final whole-branch
review (2026-08-12) — `AGENT_GUIDE.md` originally repeated the same claim and cost
real re-spend risk on paid backends. Both were corrected together.*

## Testing

**Unit** — `tests/test_registry.py`, plain asserts matching the style of the existing 7
test files, placed next to `tests/test_image_provider_selection.py`:

- each backend reports correctly with keys present and absent (monkeypatched env)
- `gpt-image-1` never appears as auto-selectable
- video reports `disabled-by-policy` even when `DASHSCOPE_API_KEY` is set
- libass detection returns the correct result for both ffmpeg capability outputs
- `--json` output parses and contains one entry per capability group

**End-to-end** — the path `CLAUDE.md` already prescribes: copy
`examples/the-sharing-berry/`, run all four stages with `--backend placeholder`. Free,
no keys required.

**Behavioral** — not unit-testable. In a fresh Claude Code session, ask for a video and
verify three things: preflight ran first, backend and cost were announced before
spending, and the run stopped at Gate 1. Failures here are guide bugs and are fixed by
editing `AGENT_GUIDE.md`. This loop is manual and expected to need two or three
iterations.

## Success criteria

1. `python -m pipeline.registry` correctly reports every capability group on a
   developer machine, including a missing-libass machine.
2. A fresh Claude Code session, given *"make me a video about X"*, runs preflight,
   announces cost, stops at Gate 1, stops at Gate 2, and produces
   `output/<name>/final.mp4`.
3. No unapproved paid call occurs in that run.
4. `tests/test_registry.py` passes; the existing 7 test files still pass.
5. The web app and Celery path are byte-for-byte unaffected.
