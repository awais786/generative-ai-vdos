# Text-Layer Redundancy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the same phrase rendering twice on one frame — an overlay or a compose card that lifts a phrase verbatim from the narration stands down, because the subtitles already show the narration.

**Architecture:** One pure predicate, `_restates(text, narration) -> bool`, added to `pipeline/assemble.py`. It is consulted at two existing call sites inside `assemble()`'s per-scene loop: a redundant `on_screen_text` yields no `drawtext` chunk, and a redundant `compose.heading` yields no `subtitles` chunk. Separately, `Scene.on_screen_text`'s field description gains a rule so the model stops writing redundant overlays in the first place.

**Tech Stack:** Python 3.13, pydantic v2 (`pipeline/schema.py`), pytest, ffmpeg filtergraphs.

**Spec:** `docs/superpowers/specs/2026-08-13-text-layer-redundancy-design.md`

## Global Constraints

- The predicate returns `False` (i.e. renders both layers, today's behaviour) for empty text, empty narration, and text under 3 words. It must never raise.
- The 3-word floor is load-bearing: it is what protects the 27 deliberate short labels (`ARGENTINA`, `FRANCE`, `Body Heart`, `It Stops!`) that a word-overlap rule destroys. Do not lower it.
- Matching is **contiguous phrase containment on normalised text**, never word-set overlap and never a similarity threshold. Paraphrase must not fire.
- Text containing `subscribe` is exempt — CTA copy repeats the narration on purpose.
- Normalisation for both sides: lowercase, replace runs of non-alphanumerics with a single space, strip and collapse whitespace.
- Winners differ by case: a redundant **overlay** loses to subtitles; redundant **subtitles** lose to a compose card.
- No new field on `ShotPlan` or `Scene`. No change to fonts, sizes, colours or positions — only to *whether* a layer runs.
- Run tests with `uv run python -m pytest` from the repo root. Bare `pytest` omits the CWD from `sys.path` and every import fails.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `pipeline/assemble.py` | the predicate + both call sites | modify |
| `pipeline/schema.py` | `Scene.on_screen_text` field description | modify (lines 89–91) |
| `tests/test_text_layers.py` | predicate unit table + corpus property test | create |
| `tests/test_text_layers_wiring.py` | end-to-end filtergraph assertions | create |

Two test files rather than one: the predicate tests are pure and fast, the wiring tests need the full `assemble()` monkeypatch harness. They fail for different reasons and a reviewer reads them differently.

---

### Task 1: The `_restates` predicate

**Files:**
- Modify: `pipeline/assemble.py` (add after `_hex_to_drawtext`, before `_overlay_filter` at line 62)
- Test: `tests/test_text_layers.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_restates(text: str | None, narration: str | None) -> bool` in `pipeline.assemble`. Task 2 calls it at both sites.

- [ ] **Step 1: Write the failing unit table**

Create `tests/test_text_layers.py`:

```python
"""The redundancy predicate that decides when a text layer stands down.

Because the subtitles ARE the narration, an overlay or card heading that lifts
a phrase from the narration prints the same words twice on one frame. This
predicate finds that case -- and, just as importantly, does NOT fire on the
short labels ('ARGENTINA', 'Subscribe!') where repeating the narration is the
deliberate visual design of a listicle.
"""
import pytest

from pipeline.assemble import _restates

WAVE = "Everyone has a wave coming. Yours is out there too, past the horizon."


@pytest.mark.parametrize("text, narration", [
    # Verbatim lifts -- the defect this exists to catch.
    ("Everyone has a wave coming", WAVE),
    ("Cosmic vacuum cleaners!", "And black holes? They’re like cosmic vacuum cleaners!"),
    ("Vision and Strength", "It perches proudly, embodying vision and strength."),
    # Punctuation and case must not save a lift from being caught.
    ("everyone HAS a WAVE coming...", WAVE),
])
def test_fires_on_verbatim_lift(text, narration):
    assert _restates(text, narration) is True


@pytest.mark.parametrize("text, narration, why", [
    ("ARGENTINA", "Argentina — champions by destiny.", "under the 3-word floor"),
    ("Body Heart", "The third heart pumps blood to the body.", "under the floor"),
    ("Subscribe for more!", "Comment below and subscribe for more facts!", "CTA exemption"),
    ("Meet the Professor", "Meet our professor, a fountain of knowledge.", "paraphrase, not a lift"),
    ("Why is the Sky Blue?", "Did you know the sky isn't always blue?", "adds 'why'"),
    ("wave coming Everyone has a", WAVE, "same words, not contiguous"),
    ("", WAVE, "empty text"),
    (None, WAVE, "no text"),
    ("Everyone has a wave coming", "", "empty narration"),
    ("Everyone has a wave coming", None, "no narration"),
])
def test_does_not_fire(text, narration, why):
    assert _restates(text, narration) is False, why
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run python -m pytest tests/test_text_layers.py -q
```

Expected: collection error — `ImportError: cannot import name '_restates'`.

- [ ] **Step 3: Implement the predicate**

In `pipeline/assemble.py`, add `import re` to the stdlib imports at the top (alphabetically, after `random`), then insert this immediately above `def _overlay_filter`:

```python
def _flatten(text: Optional[str]) -> str:
    """Lowercase, punctuation to spaces, whitespace collapsed — so that
    'everyone HAS a WAVE coming...' and 'Everyone has a wave coming' compare equal."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def _restates(text: Optional[str], narration: Optional[str]) -> bool:
    """True when `text` is a verbatim phrase already spoken in `narration`.

    The subtitles are built from the narration, so anything this returns True
    for would render twice on the same frame. Deliberately conservative:

    - Contiguous phrase only. Paraphrase ('Meet the Professor' against "Meet
      our professor") never fires — catching it needs judgement we don't have.
    - Under 3 words never fires. This is what protects the short labels that
      repeat the narration on purpose: in a listicle, 'ARGENTINA' over
      "Argentina — champions by destiny" IS the visual design.
    - 'subscribe' never fires. CTA copy repeats the narration on purpose.
    """
    flat = _flatten(text)
    spoken = _flatten(narration)
    if not flat or not spoken:
        return False
    if len(flat.split()) < 3:
        return False
    if "subscribe" in flat:
        return False
    return f" {flat} " in f" {spoken} "
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
uv run python -m pytest tests/test_text_layers.py -q
```

Expected: 14 passed.

- [ ] **Step 5: Add the corpus property test**

Append to `tests/test_text_layers.py`. This guards the rule against being loosened later — the failure mode being defended against is a future change that silently suppresses the 27 deliberate labels.

It asserts **properties and a rate ceiling**, not an exact list of scenes. (The spec proposed pinning the exact 5-scene set; that would fail every time the user renders a new video, which trains people to delete the test. The ceiling catches the same regression and survives a growing `output/`.)

```python
import json
import pathlib

OUTPUT = pathlib.Path(__file__).resolve().parent.parent / "output"


def _overlay_scenes():
    for plan_file in sorted(OUTPUT.glob("*/shot_plan.json")):
        try:
            plan = json.loads(plan_file.read_text())
        except (ValueError, OSError):
            continue  # a half-written plan from an interrupted run
        for scene in plan.get("scenes", []):
            if scene.get("on_screen_text"):
                yield plan_file.parent.name, scene["on_screen_text"], scene.get("narration")


@pytest.mark.skipif(not OUTPUT.is_dir(), reason="no output/ corpus in this checkout")
def test_corpus_suppression_stays_narrow():
    scenes = list(_overlay_scenes())
    if not scenes:
        pytest.skip("output/ has no plans with overlays")

    fired = [(name, text) for name, text, narration in scenes
             if _restates(text, narration)]

    # Every hit must be a genuine lift: at or over the floor, and contiguous.
    for name, text in fired:
        assert len(_flatten(text).split()) >= 3, f"{name}: {text!r} is a short label"

    # A rule that fires on a large share of overlays is deleting deliberate
    # labels, not redundant ones. Measured rate when written: 5/139 = 3.6%.
    rate = len(fired) / len(scenes)
    assert rate < 0.15, (
        f"suppressing {rate:.0%} of overlays ({len(fired)}/{len(scenes)}) — the rule "
        f"has been loosened and is now deleting deliberate labels: {fired[:10]}"
    )
```

Add `from pipeline.assemble import _flatten, _restates` — update the existing import line at the top of the file rather than adding a second one.

- [ ] **Step 6: Run the whole file**

```bash
uv run python -m pytest tests/test_text_layers.py -q
```

Expected: 15 passed (or 14 passed + 1 skipped in a checkout with no `output/`).

- [ ] **Step 7: Commit**

```bash
git add pipeline/assemble.py tests/test_text_layers.py
git commit -m "feat(assemble): add the text-layer redundancy predicate

_restates() finds text that is already spoken verbatim in the narration,
which the subtitles render -- so the layer showing it would print the same
words twice on one frame.

Conservative by construction: contiguous phrase only (paraphrase never
fires), nothing under 3 words (protects 'ARGENTINA' and every other short
label where repeating the narration is the listicle's visual design), and
'subscribe' exempt (CTA copy repeats on purpose)."
```

---

### Task 2: Wire both call sites

**Files:**
- Modify: `pipeline/assemble.py` — the per-scene loop in `assemble()` (the block computing `overlay` and `subs`, around lines 209–223)
- Test: `tests/test_text_layers_wiring.py` (create)

**Interfaces:**
- Consumes: `_restates(text, narration) -> bool` and `_flatten(text) -> str` from Task 1.
- Produces: no new callable. Behaviour change only.

**Two traps in this task's tests.** Both make an assertion pass for the wrong reason:

1. `_overlay_filter` returns `""` when the module-level `_FONT` is `None` (`assemble.py:64`). On a machine with no matching font, "no `drawtext` in the filtergraph" is true whether or not suppression works. **Monkeypatch `_FONT` to a fake path, and include a positive control** proving an independent overlay *does* produce `drawtext`.
2. `_subtitle_filter` returns `""` when the SRT is missing or empty, and `_build_scene_srt` writes nothing when `words.json` is `[]` (the pattern `tests/test_assemble_paths.py` uses). So "no `subtitles`" is true by default. **Write real word timings**, and include a positive control proving a non-redundant card keeps its subtitles.

- [ ] **Step 1: Write the failing wiring tests**

Create `tests/test_text_layers_wiring.py`:

```python
"""The redundancy predicate must actually reach the filtergraph.

Both assertions here can pass for the wrong reason, so both have a positive
control alongside them:

  - _overlay_filter returns '' when _FONT is None, so "no drawtext" is true on
    any machine without the font. _FONT is monkeypatched.
  - _subtitle_filter returns '' when the SRT is empty, and _build_scene_srt
    writes nothing for empty words.json. Real word timings are written.
"""
import json
from pathlib import Path

import pytest

import pipeline.assemble as assemble_mod
from pipeline.schema import ShotPlan

WAVE = "Everyone has a wave coming. Yours is out there too, past the horizon."
QUOTE = "The real treasure was the journey itself."


def _words(text: str) -> list[dict]:
    """edge-tts-shaped word timings, so _build_scene_srt writes a real SRT."""
    return [{"text": w, "start": i * 0.4, "duration": 0.4}
            for i, w in enumerate(text.split())]


def _work_dir(tmp_path: Path, narration: str) -> Path:
    for sub in ("images", "audio", "video"):
        (tmp_path / sub).mkdir()
    (tmp_path / "images" / "scene_00.png").write_bytes(b"png")
    (tmp_path / "audio" / "scene_00.mp3").write_bytes(b"mp3")
    (tmp_path / "audio" / "scene_00.words.json").write_text(json.dumps(_words(narration)))
    return tmp_path


def _filtergraph(plan: ShotPlan, work_dir: Path, monkeypatch) -> str:
    """Run assemble() with ffmpeg stubbed; return the per-scene filter_complex."""
    graphs: list[str] = []

    def fake_run(cmd, cwd=None, timeout=None, tag=None):
        if "-filter_complex" in cmd:
            graphs.append(cmd[cmd.index("-filter_complex") + 1])
        out = Path(cmd[-1])
        if not out.is_absolute():
            out = Path(cwd or ".") / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"mp4")
        return 0.0

    monkeypatch.setattr(assemble_mod, "_run", fake_run)
    monkeypatch.setattr(assemble_mod, "_duration", lambda p: 2.0)
    monkeypatch.setattr(assemble_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    # Trap 1: without a font, _overlay_filter returns '' regardless of suppression.
    monkeypatch.setattr(assemble_mod, "_FONT", "/fake/Font.ttf")

    assemble_mod.assemble(plan, work_dir)
    assert graphs, "assemble() built no filtergraph"
    return graphs[0]


def _plan(scene: dict) -> ShotPlan:
    return ShotPlan.model_validate({
        "title": "Test", "description": "Test video.", "tags": ["test"],
        "music_mood": "calm", "style_prefix": "photo", "scenes": [scene],
    })


def test_redundant_overlay_is_not_drawn(tmp_path, monkeypatch):
    plan = _plan({"media_prompt": "a", "narration": WAVE,
                  "on_screen_text": "Everyone has a wave coming"})
    graph = _filtergraph(plan, _work_dir(tmp_path, WAVE), monkeypatch)
    assert "drawtext" not in graph
    assert "subtitles" in graph, "the subtitles must survive — they win over the overlay"


def test_independent_overlay_is_drawn(tmp_path, monkeypatch):
    # Positive control for trap 1: proves the absence above is suppression,
    # not a missing font.
    plan = _plan({"media_prompt": "a", "narration": WAVE,
                  "on_screen_text": "Why is the Sky Blue?"})
    graph = _filtergraph(plan, _work_dir(tmp_path, WAVE), monkeypatch)
    assert "drawtext" in graph


def test_redundant_card_drops_the_subtitles(tmp_path, monkeypatch):
    plan = _plan({"media_prompt": "a", "narration": QUOTE,
                  "compose": {"template": "quote", "heading": QUOTE}})
    work_dir = _work_dir(tmp_path, QUOTE)
    (work_dir / "video" / "scene_00.mp4").write_bytes(b"mp4")  # the rendered card
    graph = _filtergraph(plan, work_dir, monkeypatch)
    assert "subtitles" not in graph


def test_independent_card_keeps_the_subtitles(tmp_path, monkeypatch):
    # Positive control for trap 2: proves the absence above is suppression,
    # not an empty SRT.
    plan = _plan({"media_prompt": "a", "narration": QUOTE,
                  "compose": {"template": "lower_third", "heading": "Dr. Sarah Chen"}})
    work_dir = _work_dir(tmp_path, QUOTE)
    (work_dir / "video" / "scene_00.mp4").write_bytes(b"mp4")
    graph = _filtergraph(plan, work_dir, monkeypatch)
    assert "subtitles" in graph
```

- [ ] **Step 2: Run them and watch the two suppression tests fail**

```bash
uv run python -m pytest tests/test_text_layers_wiring.py -q
```

Expected: `test_redundant_overlay_is_not_drawn` and `test_redundant_card_drops_the_subtitles` FAIL (`drawtext`/`subtitles` still present). The two positive controls PASS — confirming the harness itself works before any suppression exists.

- [ ] **Step 3: Wire the overlay call site**

In `assemble()`'s per-scene loop, replace:

```python
        overlay = _overlay_filter(plan.scenes[i].on_screen_text, style=style)
```

with:

```python
        scene = plan.scenes[i]
        # An overlay that only repeats the narration would print the same words
        # the subtitles are already showing. The subtitles win: they are
        # word-timed and carry accessibility.
        overlay_text = scene.on_screen_text
        if _restates(overlay_text, scene.narration):
            overlay_text = None
        overlay = _overlay_filter(overlay_text, style=style)
```

- [ ] **Step 4: Wire the subtitle call site**

Immediately after the existing `subs = _subtitle_filter(...)` line, add:

```python
        # A compose card IS the scene's whole visual. When it shows the line the
        # narration speaks, the card wins and the subtitles stand down.
        if scene.compose and _restates(scene.compose.heading, scene.narration):
            subs = ""
```

- [ ] **Step 5: Run the wiring tests**

```bash
uv run python -m pytest tests/test_text_layers_wiring.py -q
```

Expected: 4 passed.

- [ ] **Step 6: Run the full pipeline suite for regressions**

```bash
uv run python -m pytest tests/ -q
```

Expected: all pass. `tests/test_assemble_paths.py` is the one most likely to be disturbed — it exercises the same loop.

- [ ] **Step 7: Commit**

```bash
git add pipeline/assemble.py tests/test_text_layers_wiring.py
git commit -m "feat(assemble): suppress the duplicated text layer

A redundant on_screen_text loses to the subtitles; redundant subtitles lose
to a compose card. Measured over the 27 plans in output/: 5 overlays and 1
quote card ('The real treasure was the journey itself.' in
the-journey-of-santiago, spoken verbatim by its own narration).

Both wiring tests ship with a positive control. Without one, 'no drawtext'
passes on any machine where _FONT is None, and 'no subtitles' passes for any
empty SRT -- neither of which involves the suppression under test."
```

---

### Task 3: Teach the model not to write redundant overlays

**Files:**
- Modify: `pipeline/schema.py:89-91` (`Scene.on_screen_text`)
- Test: `tests/test_text_layers.py` (append)

**Interfaces:**
- Consumes: `_restates` from Task 1 (for the test only).
- Produces: nothing callable.

This is the durable half. Task 2 hides redundant overlays at render time; this stops them being written. The rule goes on the **field description**, not in `SYSTEM` — the field description is part of the structured-output contract the model already reads on every round trip, so it costs no extra prompt budget on the polish and consistency-review passes.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_text_layers.py`:

```python
from pipeline.schema import Scene


def test_on_screen_text_description_forbids_restating_the_narration():
    """The 45% redundancy rate in output/ traces to this field's description,
    which said only 'Optional short overlay text (max ~6 words).' — nothing
    told the model the overlay should not echo what is being spoken."""
    description = Scene.model_fields["on_screen_text"].description
    assert "max ~6 words" in description, "the existing length rule must survive"
    assert "narration" in description.lower()
```

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run python -m pytest tests/test_text_layers.py::test_on_screen_text_description_forbids_restating_the_narration -q
```

Expected: FAIL — `assert 'narration' in 'optional short overlay text (max ~6 words).'`

- [ ] **Step 3: Extend the field description**

In `pipeline/schema.py`, replace lines 89–91:

```python
    on_screen_text: Optional[str] = Field(
        default=None, description="Optional short overlay text (max ~6 words)."
    )
```

with:

```python
    on_screen_text: Optional[str] = Field(
        default=None,
        description="Optional short overlay text (max ~6 words). Must add "
        "something the narration does not say — a label, a name, a number, or "
        "a question. Never repeat a phrase from the narration: the burned-in "
        "captions already show those words.",
    )
```

- [ ] **Step 4: Run the test**

```bash
uv run python -m pytest tests/test_text_layers.py -q
```

Expected: 16 passed (or 15 passed + 1 skipped without `output/`).

- [ ] **Step 5: Run the full suite**

```bash
uv run python -m pytest tests/ -q && (cd backend && python manage.py test apps 2>&1 | tail -3)
```

Expected: pipeline tests pass; backend tests pass. `Scene` is serialised by the web app's project API, so a schema field change touches both suites.

- [ ] **Step 6: Commit**

```bash
git add pipeline/schema.py tests/test_text_layers.py
git commit -m "feat(schema): on_screen_text must add to the narration, not echo it

The field's whole guidance was 'Optional short overlay text (max ~6 words).'
Nothing told the model the overlay should not repeat what is being spoken,
and 45% of the 139 overlay scenes in output/ do exactly that.

On the field description rather than in SYSTEM: it is already part of the
structured-output contract, so it costs no prompt budget on the polish and
consistency-review round trips."
```

---

## Verification

After all three tasks:

1. `uv run python -m pytest tests/ -q` — green.
2. `(cd backend && python manage.py test apps)` — green.
3. **Visual check on the real defect.** `the-journey-of-santiago` scene 3 is the card collision in the existing corpus:
   ```bash
   uv run python -m pipeline.assemble output/the-journey-of-santiago
   ```
   Scene 3's quote card must render with **no subtitles** underneath it. This re-renders from existing assets — no image, LLM or animation spend.
4. **Confirm the labels survived.** The FIFA plan is the case a looser rule destroys:
   ```bash
   uv run python -m pipeline.assemble output/fifa-world-cup-2026-predictions-trailer
   ```
   `ARGENTINA`, `FRANCE`, `SPAIN` and `ENGLAND` must all still appear on screen.
5. `git diff origin/integration/pipeline-2026-08-13 --stat -- backend/ webapp/` must be **empty** — the web app is untouched by design.

## Notes for the implementer

- `pipeline/assemble.py` already imports `Optional` from `typing` (line 10); `re` is the only new import.
- Do not reorder or restyle anything else in the per-scene loop. The `work_dir.resolve()` at the top of `assemble()` and the relative SRT path in `_subtitle_filter` are both deliberate and each fixed a real bug — see `tests/test_assemble_paths.py`.
- Money rules apply: this work needs no image, LLM, or animation calls. Every verification step re-renders from assets already on disk.
