# Creative Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ask a few targeted questions before generating a plan, and make the answers — especially length — actually steer the output.

**Architecture:** `SYSTEM` stops hardcoding "60-90 second video" and takes a rendered length clause instead, derived from a target in seconds via `SYSTEM`'s own 4-8s-per-scene rule. `--seconds` threads that through both CLIs. A markdown-only intake skill asks five questions, composes a prose brief, maps tone to a `--style` preset, and calls `pipeline.refine` with all three.

**Tech Stack:** Python 3.13+, stdlib only, pytest. Markdown for the skill.

**Spec:** `docs/superpowers/specs/2026-08-13-creative-intake-design.md`

## Global Constraints

- Python 3.13+ — `X | None`, not `Optional[X]`.
- **stdlib only.** No new dependency in `pyproject.toml`.
- `target_seconds=None` must render **byte-identical** prompt text to today's. Every existing caller — `refine.py:122`, `run.py:99`, and `backend/apps/projects/tasks.py:90` — passes no target and must be unaffected.
- Do NOT modify `backend/`, `webapp/`, `remotion/`, `pipeline/schema.py`, `pipeline/images/`, `pipeline/compose/`, `pipeline/assemble.py`.
- Do NOT touch `SYSTEM`'s character-consistency section. It is the strongest part of the prompt.
- The new length clause must **not** restate a per-scene duration. `SYSTEM` already says "roughly 4-8 seconds to speak aloud"; a second, narrower range would recreate the contradiction this change removes.
- **The working tree has uncommitted changes to `.gitignore`, `CLAUDE.md`, `Makefile`, `scripts/git-hooks/pre-commit` belonging to the user.** Never `git add -A` or `git commit -a`. Stage files by name.
- **No `Co-Authored-By` trailer** in any commit message.
- Run tests with `uv run python -m pytest` — the bare `pytest` binary omits the working directory from `sys.path` and `import pipeline` fails.
- 7 errors in `tests/test_voiceover_helpers.py` are pre-existing on `main` (a Django settings issue). They are not yours.

---

## File Structure

| File | Responsibility |
|---|---|
| `pipeline/script_agent.py` | **Modify.** `scene_count_for()`, `system_for()`, a `system_base` parameter on `_parse_with_llm`, and `target_seconds` on `generate_shot_plan`. |
| `pipeline/refine.py` | **Modify.** `--seconds` flag, threaded to `generate_shot_plan`. |
| `pipeline/run.py` | **Modify.** Same. |
| `.claude/skills/creative-intake/SKILL.md` | **New.** The five questions, the tone→preset map, and how to compose the brief. |
| `tests/test_plan_length.py` | **New.** Scene-count arithmetic, clamp, byte-identity, CLI threading. |

## Cross-branch dependency — read before starting

The spec calls for one line in `plan-director` handing off to the intake skill.
**`plan-director` does not exist on this branch** — it lives on
`feat/agentic-pipeline-interface`, which is unmerged. Task 3 therefore creates
`creative-intake` only, and records the hand-off as a follow-up. Do not create a
stub `plan-director` here; two versions of that file on two branches would
conflict on merge.

---

## Task 1: A length the prompt can hit

**Files:**
- Modify: `pipeline/script_agent.py`
- Test: `tests/test_plan_length.py` (new)

**Interfaces:**
- Produces:
  - `scene_count_for(seconds: int) -> int`
  - `system_for(target_seconds: int | None) -> str`
  - `_parse_with_llm(..., system_base: str | None = None)`
  - `generate_shot_plan(..., target_seconds: int | None = None)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_plan_length.py`:

```python
"""The scriptwriting prompt has to ask for a length it can actually hit.

SYSTEM opened with "produce a complete shot plan for a 60-90 second video" and
separately said each scene's narration runs "roughly 4-8 seconds" — but never
stated a scene count, so the two rules were never connected. The model picked
its own count and the median finished video came out at 28s. None of the 16
rendered videos landed in the stated range.

These pin the arithmetic, the clamp, and — most importantly — that a caller
passing no target gets byte-identical text, since the web app's Celery path
calls generate_shot_plan with no target and must not shift.
"""
import pytest

from pipeline.script_agent import SYSTEM, scene_count_for, system_for


@pytest.mark.parametrize("seconds,expected", [
    (30, 5),    # round(30/6)
    (60, 10),
    (12, 2),
    (66, 11),
])
def test_scene_count_follows_the_six_second_midpoint(seconds, expected):
    # Six is the midpoint of SYSTEM's own "roughly 4-8 seconds" rule, so the
    # count and the rule agree by construction rather than by coincidence.
    assert scene_count_for(seconds) == expected


@pytest.mark.parametrize("seconds", [1, 5, 11])
def test_scene_count_clamps_at_the_bottom(seconds):
    # A careless --seconds 5 must not ask for a one-scene video.
    assert scene_count_for(seconds) == 2


@pytest.mark.parametrize("seconds", [90, 600, 100000])
def test_scene_count_clamps_at_the_top(seconds):
    # Nor a forty-scene one: every scene is a paid image.
    assert scene_count_for(seconds) == 12


def test_no_target_renders_todays_prompt_byte_for_byte():
    # The web app's Celery path (backend/apps/projects/tasks.py) passes no
    # target. Any drift here changes every web-app video's script.
    assert system_for(None) == SYSTEM


def test_a_target_states_the_scene_count_and_the_seconds():
    rendered = system_for(30)
    assert "about 30 seconds" in rendered
    assert "5 scenes" in rendered
    assert "Do not exceed 5 scenes" in rendered


def test_a_target_removes_the_hardcoded_range():
    # The 60-90s claim is the thing being fixed; it must not survive alongside
    # the new clause, or the prompt contradicts itself exactly as before.
    assert "60-90 second" not in system_for(30)


def test_the_length_clause_does_not_restate_a_per_scene_duration():
    # SYSTEM already says "roughly 4-8 seconds to speak aloud". A second,
    # narrower range in the new clause would recreate the contradiction.
    rendered = system_for(30)
    head = rendered.split("Rules:")[0]
    assert "5-6 second" not in head
    assert "seconds of narration each" not in head


def test_the_character_consistency_section_survives():
    # The strongest part of the prompt; templating must not clip it.
    for rendered in (system_for(None), system_for(30)):
        assert "CHARACTER AND VISUAL CONSISTENCY" in rendered
        assert "Argentina flag" in rendered
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_plan_length.py -v`
Expected: FAIL — `ImportError: cannot import name 'scene_count_for' from 'pipeline.script_agent'`

- [ ] **Step 3: Split the length clause out of `SYSTEM`**

In `pipeline/script_agent.py`, the module currently opens with:

```python
SYSTEM = """You are a scriptwriter for a faceless YouTube channel. Given a topic or rough
script, produce a complete shot plan for a 60-90 second video built from still images,
voiceover, and captions.
```

Replace that with a template plus a default, keeping every other line of the
prompt exactly as it is:

```python
# The length clause is the only part of the prompt that varies. It used to be a
# hardcoded "60-90 second video" that nothing could satisfy: the prompt states
# no scene count, so the model chose its own and the median finished video came
# out at 28s. Now the count is derived from the 4-8s-per-scene rule below.
_DEFAULT_LENGTH = "a 60-90 second video"

_SYSTEM_TEMPLATE = """You are a scriptwriter for a faceless YouTube channel. Given a topic or rough
script, produce a complete shot plan for {length} built from still images,
voiceover, and captions.
```

…and at the end of the template string, after the existing final line, close it
and render the default:

```python
SYSTEM = _SYSTEM_TEMPLATE.format(length=_DEFAULT_LENGTH)
```

`SYSTEM` stays a module-level constant with its current value, so every existing
reference keeps working.

- [ ] **Step 4: Add the two helpers**

```python
MIN_SCENES, MAX_SCENES = 2, 12
_SECONDS_PER_SCENE = 6  # midpoint of the "roughly 4-8 seconds" rule in the prompt


def scene_count_for(seconds: int) -> int:
    """Scenes for a target duration, clamped to something renderable.

    Derived from the prompt's own 4-8s-per-scene rule so the two agree. The
    clamp matters because every scene is a paid image: `--seconds 600` asking
    for a hundred scenes is a costly typo, not an instruction.
    """
    return max(MIN_SCENES, min(MAX_SCENES, round(seconds / _SECONDS_PER_SCENE)))


def system_for(target_seconds: int | None) -> str:
    """The scriptwriting prompt, with a length clause the model can satisfy.

    None renders exactly today's text — the web app's celery path passes no
    target and must not shift.

    The clause deliberately states no per-scene duration: the prompt already
    carries "roughly 4-8 seconds to speak aloud", and a second, narrower range
    here would recreate the contradiction this exists to remove.
    """
    if target_seconds is None:
        return SYSTEM
    scenes = scene_count_for(target_seconds)
    return _SYSTEM_TEMPLATE.format(
        length=(f"a video of about {target_seconds} seconds — that is "
                f"{scenes} scenes. Do not exceed {scenes} scenes")
    )
```

- [ ] **Step 5: Let `_parse_with_llm` take a base**

`_parse_with_llm` currently builds its system message from the module constant
(`pipeline/script_agent.py:283`):

```python
    system = SYSTEM if not system_extra else f"{SYSTEM}\n\n{system_extra}"
```

Add a `system_base: str | None = None` parameter to its signature and use it:

```python
    base = system_base or SYSTEM
    system = base if not system_extra else f"{base}\n\n{system_extra}"
```

Defaulting to `None` rather than to `SYSTEM` keeps the byte-identity guarantee
structural: a caller that passes nothing cannot get different text.

- [ ] **Step 6: Thread it through `generate_shot_plan`**

Add `target_seconds: int | None = None` to the signature
(`pipeline/script_agent.py:324-331`), and pass the rendered base:

```python
    return _parse_with_llm(f"Topic / rough script:\n\n{topic}", model,
                           system_extra=system_extra,
                           system_base=system_for(target_seconds),
                           provider=provider, api_key=api_key)
```

`system_for(None)` returns `SYSTEM`, so callers passing no target are unchanged.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_plan_length.py -v`
Expected: PASS — 15 passed (4+3+3 parametrized, plus 5 single)

- [ ] **Step 8: Run the whole suite**

Run: `uv run python -m pytest tests/ -q`
Expected: no new failures; the 7 `test_voiceover_helpers` errors remain.

- [ ] **Step 9: Commit**

```bash
git add pipeline/script_agent.py tests/test_plan_length.py
git commit -m "feat(plan): make the video's target length steerable

SYSTEM asked for a 60-90 second video and stated no scene count, so the model
picked its own and the median finished video came out at 28s — none of the 16
rendered videos hit the stated range. The scene count is now derived from the
prompt's own 4-8s-per-scene rule, and the clause says so. Passing no target
renders byte-identical text, so the web app's celery path is untouched."
```

---

## Task 2: `--seconds` on both CLIs

**Files:**
- Modify: `pipeline/refine.py`
- Modify: `pipeline/run.py`
- Test: `tests/test_plan_length.py` (append)

**Interfaces:**
- Consumes: `generate_shot_plan(..., target_seconds=...)`, `scene_count_for()` from Task 1

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_plan_length.py`:

```python
# --- CLI threading ---

import sys
from pathlib import Path


def test_refine_passes_seconds_through(tmp_path, monkeypatch):
    # The flag is worthless unless it reaches the prompt. This drives main()
    # rather than the helper, because the wiring is where it would be dropped.
    import pipeline.refine as refine_mod

    seen = {}

    def fake_generate(topic, **kw):
        seen.update(kw)
        raise SystemExit(0)  # stop before any file is written

    monkeypatch.setattr("pipeline.script_agent.generate_shot_plan", fake_generate)
    monkeypatch.setattr(sys, "argv", ["refine", "a topic", "--seconds", "30"])
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        refine_mod.main()
    assert seen.get("target_seconds") == 30


def test_refine_without_seconds_passes_none(tmp_path, monkeypatch):
    import pipeline.refine as refine_mod

    seen = {}

    def fake_generate(topic, **kw):
        seen.update(kw)
        raise SystemExit(0)

    monkeypatch.setattr("pipeline.script_agent.generate_shot_plan", fake_generate)
    monkeypatch.setattr(sys, "argv", ["refine", "a topic"])
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        refine_mod.main()
    assert seen.get("target_seconds") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_plan_length.py -k refine -v`
Expected: FAIL — `assert None == 30`, because `--seconds` is not yet a flag
(argparse will error on the unknown argument, which is also an acceptable RED).

- [ ] **Step 3: Add the flag to `refine.py`**

Next to the existing `--style` argument, add:

```python
    parser.add_argument("--seconds", type=int, default=None,
                        help="Target video length; sets the scene count "
                             "(default: the prompt's own 60-90s guidance)")
```

Then pass it at the call site (`pipeline/refine.py:122`):

```python
        plan = generate_shot_plan(args.input, model=args.model, style=style,
                                  target_seconds=args.seconds)
```

And print the resolved count when a target was given, so the clamp is visible:

```python
    if args.seconds:
        from .script_agent import scene_count_for
        print(f"target: ~{args.seconds}s -> {scene_count_for(args.seconds)} scenes")
```

Place that immediately before the `generate_shot_plan` call.

- [ ] **Step 4: Add the flag to `run.py`**

Same argument definition, and pass `target_seconds=args.seconds` at
`pipeline/run.py:99`'s `generate_shot_plan(...)` call.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_plan_length.py -v`
Expected: PASS — 17 passed

- [ ] **Step 6: Verify on a real run**

Run: `uv run python -m pipeline.refine "why the sky is blue" --seconds 18`

Expected: prints `target: ~18s -> 3 scenes`, and the resulting plan has 3
scenes rather than the usual 7. Costs ~$0.001.

Clean up: `rm -rf output/<slug>`

- [ ] **Step 7: Commit**

```bash
git add pipeline/refine.py pipeline/run.py tests/test_plan_length.py
git commit -m "feat(cli): --seconds sets the target video length

Prints the resolved scene count so the 2-12 clamp is visible rather than
silently applied."
```

---

## Task 3: The intake skill

**Files:**
- Create: `.claude/skills/creative-intake/SKILL.md`

This task writes markdown only. There is no test; the skill is verified
behaviourally in Task 4.

- [ ] **Step 1: Create the skill**

```markdown
---
name: creative-intake
description: Gathering what a video actually needs before generating a plan — purpose, audience, length, tone, and must-include content. Use when the user asks for a video with a bare topic and no brief, before running pipeline.refine. Triggers include make a video, create a video, video about, I want a video, produce a video, before planning, vague brief.
---

# Creative Intake

Do not start production on a vague brief. "Make me a video about X" does not say
who it is for, how long it should be, or what it should feel like — so the model
guesses, and the guess is only visible once seven scenes exist.

Ask first. It costs one exchange and changes the whole output.

## The five questions

Ask **one at a time**, starting with the biggest gap. Never present them as a
survey.

| Question | What it changes |
|---|---|
| **Purpose** — educate, sell, inspire, entertain? | the narration's register |
| **Audience** — who watches this? | vocabulary, and what can be assumed |
| **Length and platform** — how long, and where does it live? | `--seconds` |
| **Tone** — what should it feel like? | `--style <preset>` |
| **Must-include** — any fact, name, or quote that has to appear? | the brief |

Stop when you have enough to write a brief. You do not need all five.

## Skip what the user already told you

A detailed brief is summarised back in one sentence, not interrogated. If
someone says *"a 30-second cinematic Instagram clip about our new coffee
roaster"*, that is length, platform, tone and subject already answered — ask
only about audience and must-include, or just proceed.

Intake exists for vague input. It is not a toll booth on every request.

## Tone maps to a style preset

Pass `--style` so the video does not default to the model's house style. Every
existing plan in `output/` chose some variant of "cinematic photo, warm colors";
the presets below are the way out of that.

| The user says | Preset |
|---|---|
| tense, noir, crime, high contrast | `noir` |
| gentle, childlike, bedtime, whimsical | `storybook` |
| factual, journalistic, real-world | `documentary` |
| soft, painterly, dreamy | `watercolor` |
| anime, manga, cel-shaded | `anime` |
| retro, 8-bit, pixel, arcade | `retro-pixel` |
| cinematic, filmic, moody (the default register) | `cinematic` |

If nothing fits, pass no `--style` — the model writes its own `style_prefix`,
which is today's behaviour.

## Then run the stage

Compose a **prose brief** — a short paragraph carrying the answers, not a
bulleted form — and hand it to stage 1:

    python -m pipeline.refine "<brief>" --style <preset> --seconds <n>

A worked example. The user said "a video about our coffee roaster", then
answered: to sell, for cafe owners, 30 seconds on Instagram, warm and
craft-focused, must mention single-origin Ethiopian beans.

    python -m pipeline.refine "A 30-second Instagram video selling our new
    coffee roaster to independent cafe owners. Warm, craft-focused tone —
    close-up texture, hands, steam. Must mention single-origin Ethiopian
    beans. End on the roaster itself, no subscribe CTA." \
      --style cinematic --seconds 30

Then continue with `plan-director` — the plan review gate still applies. Intake
does not replace it; it makes the plan worth reviewing.
```

- [ ] **Step 2: Verify the frontmatter parses**

Run: `ls .claude/skills/`
Expected: `creative-intake` alongside the existing skills. Confirm the file
starts with `---` on line 1, `name:` matches the directory, `description:` is a
single line, and there are no tabs.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/creative-intake/SKILL.md
git commit -m "feat(skills): ask what the video needs before planning it

Five questions, one at a time, skipping whatever the user already said. Tone
maps to a --style preset, which is what finally puts the seven presets to use:
every style_prefix in output/ is a variant of 'cinematic photo, warm colors'."
```

---

## Task 4: Verification

**Files:** none — this verifies Tasks 1–3.

- [ ] **Step 1: Full suite**

Run: `uv run python -m pytest tests/ -q`
Expected: 17 new tests pass; the 7 pre-existing `test_voiceover_helpers` errors
remain and nothing else fails.

- [ ] **Step 2: Length actually steers**

```bash
uv run python -m pipeline.refine "the history of the paperclip" --seconds 18
```

Expected: `target: ~18s -> 3 scenes`, and a plan with 3 scenes. Compare against
the corpus median of 7 — that difference is the whole point.

Then the other end:

```bash
uv run python -m pipeline.refine "the history of the paperclip" --seconds 60 --name paperclip-60
```

Expected: 10 scenes.

Clean up both output dirs.

- [ ] **Step 3: No target is unchanged**

```bash
uv run python -c "
from pipeline.script_agent import SYSTEM, system_for
assert system_for(None) == SYSTEM, 'byte-identity broken'
print('byte-identical:', len(SYSTEM), 'chars')
"
```

- [ ] **Step 4: The web app is untouched**

```bash
git diff origin/main --stat -- backend/ webapp/ remotion/ pyproject.toml
```

Expected: **empty**. `backend/apps/projects/tasks.py:90` calls
`generate_shot_plan` with no `target_seconds`, so it renders `SYSTEM` exactly as
before.

- [ ] **Step 5: Behavioural check on the skill**

In a **fresh** Claude Code session in this repo, say: `make me a video about
sourdough`.

Verify it asks about purpose/audience/length/tone **before** running anything,
rather than generating a plan immediately. A failure here is a skill-description
problem — the trigger terms are not matching — and is fixed by editing the
`description:` line, then retrying in another fresh session.

- [ ] **Step 6: Push**

```bash
git push -u origin feat/creative-intake
```

---

## Follow-ups this plan deliberately leaves open

- **The `plan-director` hand-off.** The spec calls for a line in
  `plan-director` pointing at `creative-intake` when the brief is a bare topic.
  That file lives on `feat/agentic-pipeline-interface` and is unmerged, so the
  line must be added after those branches meet. Creating a second copy here
  would conflict on merge.
- **Nothing compares intent to outcome.** `--seconds 30` steers the scene
  count, but no one checks the finished `final.mp4` against the target. The
  durations are already measured at assembly; comparing them to a stored intent
  would close the loop that let the 60-90s claim go unnoticed for so long.

## Success criteria

1. `--seconds 30` yields a ~5-scene plan instead of the model's default 7. *(Task 4 Step 2)*
2. A run with no `--seconds` renders byte-identical prompt text. *(Task 4 Step 3)*
3. A cold agent given a bare topic asks before generating. *(Task 4 Step 5)*
4. A tone answer results in a `--style` preset being passed. *(Task 3's mapping table)*
5. `backend/`, `webapp/`, `remotion/` unchanged. *(Task 4 Step 4)*
