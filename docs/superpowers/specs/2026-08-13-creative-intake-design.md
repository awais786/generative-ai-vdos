# Creative Intake, and a Length the Prompt Can Actually Hit

**Date:** 2026-08-13
**Status:** Approved, ready for implementation planning

## Problem

A one-line topic becomes seven scenes and seven images with no conversation in
between. Nothing asks who the video is for, how long it should be, or what it
should feel like — so the model guesses, and the guess is only visible after the
plan exists.

Two measurements from the 26 finished videos in `output/`:

**The scriptwriting prompt asks for a length it never gets.** `SYSTEM`
(`pipeline/script_agent.py:19-21`) opens with *"produce a complete shot plan for
a 60-90 second video"* and later says *"each scene's narration should take
roughly 4-8 seconds to speak aloud"* — but **states no scene count**. The two
rules are never connected, so the model picks its own scene count and the totals
land elsewhere:

| | Stated | Actual (16 rendered videos) |
|---|---|---|
| Duration | 60–90s | median **28s**, min 11s, max 52s |

Not one video hit the stated range. Nothing surfaced this because scene
durations are measured from the voiceover mp3s at assembly and never compared
against the plan's intent.

**Every video looks the same.** The `style_prefix` values the model writes are
near-identical variants of "cinematic photo, warm colors, soft focus". Seven
presets exist — `anime`, `watercolor`, `noir`, `retro-pixel`, `storybook`,
`documentary` — and are effectively never used, because nothing asks about tone
and nothing defaults to a preset.

## Goal

Ask a few targeted questions before generating, and make the answers actually
steer the output — in particular length, which today is unsteerable because the
prompt contradicts itself.

## Non-goals

- **Web app intake.** The web app already has the *verification* half
  (`Status.REVIEW`, `approve`, `refine`, `IMAGE_REVIEW`, `approve_images` in
  `backend/apps/projects/views.py`); what it lacks is intake. Adding it there
  means a Next.js form, a Django field, and a migration. Out of scope here, and
  the agent path is the surface in use.
- **Rewriting the rest of `SYSTEM`.** Its character-consistency section is the
  strongest part of the prompt and is left untouched.
- **A structured brief format.** The skill composes a prose brief and passes it
  as the existing topic argument. No new file format, no schema change.

## Reference

OpenMontage's `skills/meta/creative-intake.md` opens with *"Before the research
stage, gather user intent through targeted questions. Do NOT start production on
a vague brief."* It asks seven — purpose, audience, platform, tone, references,
outcome, constraints — with two rules this design adopts:

1. **Do not dump all the questions at once.** Start with the most important gap
   and let the conversation flow.
2. **Skip what the user already told you.** A detailed brief is summarised back,
   not interrogated.

It is markdown with no supporting code, which is why this design is cheap.

## Findings that shaped the design

Established by reading the code and measuring the corpus:

1. **`SYSTEM` states no scene count.** The 60–90s claim and the 4–8s-per-scene
   rule are never reconciled, which is the whole defect. Median output is 7
   scenes — the model's own default.
2. **`generate_shot_plan` already accepts a `system_extra`**
   (`pipeline/script_agent.py:283`: `system = SYSTEM if not system_extra else
   f"{SYSTEM}\n\n{system_extra}"`), used by `inject_style_instruction`. Length
   could ride that channel, but a hardcoded contradiction in the base prompt
   would remain — so the base text is parameterised instead.
3. **The plan carries no duration intent.** `ShotPlan` has no length field, and
   `assemble.py` measures real durations from the mp3s. Nothing ever compares
   the two, which is why the mismatch went unnoticed.
4. **`plan-director` starts at "run `pipeline.refine`."** It has no notion of a
   step before the command, so intake needs an explicit hand-off.

## Architecture

Two independent pieces. The prompt change is useful alone; the skill is not
useful without it.

```
user: "make me a video about X"
        │
        ▼
.claude/skills/creative-intake/SKILL.md      ← markdown only
   asks purpose / audience / length / tone / must-include
        │  composes a prose brief, maps tone -> preset
        ▼
python -m pipeline.refine "<brief>" --style <preset> --seconds <n>
        │
        ▼
generate_shot_plan(topic, target_seconds=n)
   SYSTEM renders "about {n} seconds — that is {scenes} scenes"
```

## Component: the length parameter

`SYSTEM` becomes a template. The opening clause is replaced by one built from
the target:

```
produce a complete shot plan for a video of about {seconds} seconds —
that is {scenes} scenes. Do not exceed {scenes} scenes.
```

The clause deliberately does **not** restate a per-scene duration: `SYSTEM`
already carries *"each scene's narration should take roughly 4-8 seconds to
speak aloud"*, and stating a second, narrower range here would recreate exactly
the contradiction this change exists to remove. The scene count is derived from
that existing rule instead.

`generate_shot_plan()` gains `target_seconds: int | None = None`. When it is
`None` the prompt renders **exactly today's text**, so every existing caller —
including the web app's Celery path — is unaffected.

Scene count is `round(seconds / 6)`, clamped to **2–12**. Six is the midpoint of
`SYSTEM`'s existing 4–8s rule, so the count and the rule agree by construction.
The clamp keeps a careless `--seconds 5` or `--seconds 600` from producing a
one-scene or forty-scene plan.

`refine.py` and `run.py` gain `--seconds`. The flag is optional; omitting it
preserves current behaviour.

## Component: the intake skill

`.claude/skills/creative-intake/SKILL.md`, using the same frontmatter as the
existing skills. It covers five questions, not OpenMontage's seven — `references`
and `outcome` are dropped because nothing downstream consumes them:

| Question | What it steers |
|---|---|
| Purpose — educate, sell, inspire, entertain | narration register |
| Audience | vocabulary, and how much knowledge is assumed |
| Length and platform | `--seconds` |
| Tone | `--style <preset>` |
| Must-include | facts, names, or a quote that has to appear |

Then it composes a **prose brief** — a short paragraph carrying the answers —
and runs `pipeline.refine` with it, plus `--style` and `--seconds`.

**Tone maps to a preset**, which is what finally puts the seven presets to use
and addresses the sameness finding. The skill carries the mapping (e.g. tense or
noir → `noir`; gentle or childlike → `storybook`; factual → `documentary`) and
falls back to no `--style` when nothing fits, which leaves today's behaviour.

Two rules are adopted verbatim from OpenMontage: ask one question at a time
starting with the biggest gap, and skip anything already supplied. A detailed
brief is summarised back in one sentence and proceeds — intake exists for vague
input, not as a toll booth on every request.

## Integration

`plan-director` gains one line at the top of its "Before running" section: when
the user's brief is a bare topic, read `creative-intake` first. When the brief
already carries purpose, audience, length and tone, proceed directly.

## Error handling

- `--seconds` outside 2–12 scenes' worth is clamped rather than rejected, and
  the resolved scene count is printed so the clamp is visible.
- A tone with no matching preset means no `--style` — the model writes its own
  `style_prefix`, exactly as now.
- A user who declines to answer gets today's behaviour: the skill proceeds with
  a bare topic rather than blocking.

## Testing

- `target_seconds=30` renders a prompt naming 5 scenes; `target_seconds=60`
  renders 10.
- `target_seconds=None` renders byte-identical text to today's `SYSTEM`.
- The clamp holds at both ends: `--seconds 5` yields 2 scenes, `--seconds 600` yields 12.
- `--seconds` is threaded from both CLIs into `generate_shot_plan`.
- Behavioural, not unit-testable: a cold agent given "make me a video about X"
  asks before generating, and a detailed brief is not interrogated.

## Success criteria

1. `python -m pipeline.refine "<topic>" --seconds 30` produces a plan of about
   5 scenes rather than the model's default 7.
2. A run with no `--seconds` behaves exactly as before.
3. A cold agent given a bare topic asks about purpose, audience, length and tone
   before spending anything.
4. A tone answer results in a `--style` preset being passed, so videos stop
   defaulting to "cinematic photo, warm colors".
