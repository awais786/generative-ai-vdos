# Style Playbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One style source so a video's images, compose cards, captions and overlays cannot disagree about how it looks.

**Architecture:** Each preset in `pipeline/styles.py` gains concrete colours, consistency anchors and text sizes. When a run picks a style, the resolved values are written to `work_dir/style.json` — a sidecar beside `shot_plan.json`. The four renderers read that file instead of guessing. `ShotPlan` is not modified, because it is the LLM's structured-output schema.

**Tech Stack:** Python 3.13+, stdlib only (`json`, `pathlib`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-13-style-playbook-design.md`

## Global Constraints

- Python 3.13+ — use `X | None` union syntax, not `Optional[X]`.
- **Do not modify `pipeline/schema.py`'s `ShotPlan` fields.** It is passed as
  `output_format=ShotPlan` to the LLM (`pipeline/script_agent.py:265`); any new
  field becomes something the model is asked to invent on all three round trips.
  The one permitted change to that file is adding an `extra_overhead` parameter to
  `expand()` (Task 3).
- **stdlib only.** No new dependency in `pyproject.toml` — in particular no YAML.
- **Every consumer falls back.** A missing `style.json`, a missing key inside it,
  or a preset without the new keys must all behave exactly as the code does today.
  Existing `output/*/` folders have no `style.json` and must render unchanged.
- **No TypeScript changes.** `remotion/src/theme.ts` and the templates stay as
  they are; Remotion already receives the palette as a prop.
- **No web-app changes.** Nothing under `backend/` or `webapp/`.
- Palette keys are exactly `bg1`, `bg2`, `fg`, `accent`, `glow` — matching
  `MOOD_PALETTES`, so the Remotion props contract is unchanged.
- Run tests with `uv run python -m pytest` — the bare `pytest` binary omits the
  working directory from `sys.path` and `import pipeline` fails.
- Commit after every task.

---

## File Structure

| File | Responsibility |
|---|---|
| `pipeline/styles.py` | **Modify.** The style guide itself: presets gain `palette`/`consistency_anchors`/`text`, plus `save_style()` and `load_style()`. |
| `pipeline/refine.py` | **Modify.** Write the sidecar after refinement completes. |
| `pipeline/run.py` | **Modify.** Same, in the one-shot path. |
| `pipeline/schema.py` | **Modify (one parameter).** `expand()` gains `extra_overhead: int = 0`. |
| `pipeline/images/__init__.py` | **Modify.** Append consistency anchors to every image prompt. |
| `pipeline/compose/__init__.py` | **Modify.** `_palette_for` prefers the style file. |
| `pipeline/assemble.py` | **Modify.** Captions and overlays read the style file. |
| `tests/test_styles_playbook.py` | **New.** Preset shape, save/load round trip, fallbacks. |
| `tests/test_style_consumers.py` | **New.** Anchors in prompts, budget, palette to props, caption/overlay colours. |

## Colour conversion — get this right or every colour is wrong

The two renderers want different formats, and one of them is byte-reversed:

| Consumer | Format | Example for `#f4ead6` |
|---|---|---|
| libass (`subtitles=…:force_style=`) | `&HAABBGGRR` — **BGR**, alpha first | `&H00D6EAF4` |
| ffmpeg `drawtext` (`fontcolor=`) | `0xRRGGBB` | `0xf4ead6` |
| Remotion (props JSON) | `#rrggbb` as-is | `#f4ead6` |

Task 5 defines one helper per format. Passing an `#rrggbb` string straight to
libass silently produces the wrong colour rather than an error.

---

## Task 1: Style presets, save and load

**Files:**
- Modify: `pipeline/styles.py`
- Test: `tests/test_styles_playbook.py` (new)

**Interfaces:**
- Consumes: existing `PRESETS`, `resolve_style(raw) -> dict | None`
- Produces:
  - `STYLE_FILE = "style.json"`
  - `save_style(work_dir: Path, preset: dict | None) -> Path | None`
  - `load_style(work_dir: Path) -> dict`  (returns `{}` when absent/unreadable)
  - every preset in `PRESETS` gains `palette`, `consistency_anchors`, `text`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_styles_playbook.py`:

```python
"""The style guide and its sidecar file.

A video's look is decided in four places (image prompts, compose cards,
captions, overlays). Before this, each read a different source and they drifted:
a plan with style_prefix "warm desert tones" rendered a purple quote card,
because the card's palette was looked up by music_mood. These tests pin the
single source and, just as importantly, the fallbacks — every existing
output/*/ folder has no style.json and must keep rendering.
"""
import json
from pathlib import Path

import pytest

from pipeline.styles import PRESETS, load_style, resolve_style, save_style

PALETTE_KEYS = {"bg1", "bg2", "fg", "accent", "glow"}
TEXT_KEYS = {"caption_size", "caption_outline", "overlay_size", "overlay_border"}


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_every_preset_is_complete(name):
    # A preset missing a key would silently fall back for that one value,
    # producing a video that is styled *almost* consistently — the hardest
    # kind of drift to notice.
    preset = PRESETS[name]
    assert PALETTE_KEYS == set(preset["palette"]), name
    assert TEXT_KEYS == set(preset["text"]), name
    assert preset["consistency_anchors"], name


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_palette_values_are_hex(name):
    # Remotion, libass and drawtext all need parseable colours; a stray
    # "warm gold" here surfaces as a broken render, not a config error.
    for key, value in PRESETS[name]["palette"].items():
        if key == "glow":
            continue  # rgba(...) by design — used for CSS shadows only
        assert value.startswith("#") and len(value) == 7, f"{name}.{key}={value}"
        int(value[1:], 16)


def test_save_then_load_round_trips(tmp_path):
    written = save_style(tmp_path, PRESETS["cinematic"])
    assert written == tmp_path / "style.json"
    loaded = load_style(tmp_path)
    assert loaded["palette"] == PRESETS["cinematic"]["palette"]
    assert loaded["consistency_anchors"] == PRESETS["cinematic"]["consistency_anchors"]
    assert loaded["name"] == "cinematic"


def test_save_style_with_no_preset_writes_nothing(tmp_path):
    # A run with no --style must leave the work dir exactly as it was.
    assert save_style(tmp_path, None) is None
    assert not (tmp_path / "style.json").exists()


def test_load_style_missing_file_returns_empty(tmp_path):
    # Every existing output/*/ folder is in this state.
    assert load_style(tmp_path) == {}


def test_load_style_corrupt_file_returns_empty(tmp_path):
    # Falling back beats crashing stage 4 on a hand-edited file.
    (tmp_path / "style.json").write_text("{not json")
    assert load_style(tmp_path) == {}


def test_custom_style_saves_without_palette(tmp_path):
    # resolve_style("custom:...") returns a partial dict with no palette;
    # saving it must not invent one.
    preset = resolve_style("custom: oil painting, thick impasto")
    save_style(tmp_path, preset)
    assert load_style(tmp_path).get("palette") in (None, {})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_styles_playbook.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_style' from 'pipeline.styles'`

- [ ] **Step 3: Add the palette/anchors/text to every preset**

In `pipeline/styles.py`, add three keys to each of the seven presets. Use exactly
these values:

```python
# --- cinematic ---
    "palette": {"bg1": "#0b0b12", "bg2": "#3a1f22", "fg": "#f4ead6",
                "accent": "#e0714a", "glow": "rgba(224,113,74,0.24)"},
    "consistency_anchors": [
        "same colour grade across every scene",
        "same time of day and lighting direction",
    ],
    "text": {"caption_size": 18, "caption_outline": 2,
             "overlay_size": 58, "overlay_border": 3},

# --- anime ---
    "palette": {"bg1": "#101a2e", "bg2": "#2f4d7a", "fg": "#fdf6ec",
                "accent": "#ffb84d", "glow": "rgba(255,184,77,0.26)"},
    "consistency_anchors": [
        "same cel-shading treatment in every scene",
        "same line weight and colour saturation",
    ],
    "text": {"caption_size": 19, "caption_outline": 3,
             "overlay_size": 60, "overlay_border": 4},

# --- watercolor ---
    "palette": {"bg1": "#2a2a33", "bg2": "#6b6478", "fg": "#fbf6ef",
                "accent": "#e3a7a1", "glow": "rgba(227,167,161,0.22)"},
    "consistency_anchors": [
        "same pastel wash palette in every scene",
        "same paper texture and brush treatment",
    ],
    "text": {"caption_size": 18, "caption_outline": 2,
             "overlay_size": 54, "overlay_border": 3},

# --- documentary ---
    "palette": {"bg1": "#14161a", "bg2": "#39424d", "fg": "#f2f4f6",
                "accent": "#7fa8c9", "glow": "rgba(127,168,201,0.20)"},
    "consistency_anchors": [
        "same neutral colour grade across every scene",
        "same natural lighting quality",
    ],
    "text": {"caption_size": 18, "caption_outline": 2,
             "overlay_size": 52, "overlay_border": 3},

# --- storybook ---
    "palette": {"bg1": "#1d1426", "bg2": "#5a3b52", "fg": "#fdf0dd",
                "accent": "#f0b563", "glow": "rgba(240,181,99,0.26)"},
    "consistency_anchors": [
        "same warm illustrative palette in every scene",
        "same soft lighting and rounded shapes",
    ],
    "text": {"caption_size": 19, "caption_outline": 3,
             "overlay_size": 58, "overlay_border": 3},

# --- noir ---
    "palette": {"bg1": "#08080a", "bg2": "#2b2b30", "fg": "#ededf0",
                "accent": "#c0392b", "glow": "rgba(192,57,43,0.24)"},
    "consistency_anchors": [
        "same high-contrast black and white grade in every scene",
        "same hard directional key light",
    ],
    "text": {"caption_size": 18, "caption_outline": 3,
             "overlay_size": 56, "overlay_border": 4},

# --- retro-pixel ---
    "palette": {"bg1": "#12102a", "bg2": "#3b2f6b", "fg": "#f7f5ff",
                "accent": "#41e0a3", "glow": "rgba(65,224,163,0.26)"},
    "consistency_anchors": [
        "same limited pixel palette in every scene",
        "same pixel grid size and dithering",
    ],
    "text": {"caption_size": 20, "caption_outline": 3,
             "overlay_size": 56, "overlay_border": 4},
```

- [ ] **Step 4: Add save/load**

Append to `pipeline/styles.py`:

```python
import json
from pathlib import Path

STYLE_FILE = "style.json"

# Keys copied into the sidecar. style_prefix / global_negative / music_mood are
# deliberately excluded: those already live in shot_plan.json, and duplicating
# them would create a second source that could disagree with the first.
_SIDECAR_KEYS = ("palette", "consistency_anchors", "text")


def save_style(work_dir: Path, preset: dict | None) -> Path | None:
    """Write the resolved style to work_dir/style.json.

    Call this AFTER refine_plan() — polish and consistency review each return a
    fresh plan parsed from the LLM, so a style written earlier would describe a
    plan that no longer exists.

    Returns None (writing nothing) when there is no preset, or when the preset
    carries none of the sidecar keys — as with `custom:` styles, which are just a
    style_prefix.
    """
    if not preset:
        return None
    payload = {k: preset[k] for k in _SIDECAR_KEYS if preset.get(k)}
    if not payload:
        return None
    for name, candidate in PRESETS.items():
        if candidate is preset:
            payload["name"] = name
            break
    path = Path(work_dir) / STYLE_FILE
    path.write_text(json.dumps(payload, indent=2))
    return path


def load_style(work_dir: Path) -> dict:
    """Read work_dir/style.json, or {} when absent or unreadable.

    Never raises: every consumer must fall back to its previous hardcoded
    behaviour rather than failing a render over a style file.
    """
    path = Path(work_dir) / STYLE_FILE
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_styles_playbook.py -v`
Expected: PASS — 18 passed (7 presets × 2 parametrized + 6 others)

- [ ] **Step 6: Register the test file if needed**

`make test` runs `$(PY) -m pytest tests/`, which picks up new files automatically.
Confirm with: `uv run python -m pytest tests/ -q` — no collection errors.

- [ ] **Step 7: Commit**

```bash
git add pipeline/styles.py tests/test_styles_playbook.py
git commit -m "feat(styles): give every preset a palette, anchors and text sizes

Adds the style sidecar (work_dir/style.json) and its save/load helpers. Nothing
reads it yet. Style deliberately does not go on ShotPlan: that model is passed
as output_format to the LLM, so a field there is a field the model is asked to
invent on every round trip."
```

---

## Task 2: Write the sidecar from both entry points

**Files:**
- Modify: `pipeline/refine.py`
- Modify: `pipeline/run.py`
- Test: `tests/test_styles_playbook.py` (append)

**Interfaces:**
- Consumes: `save_style(work_dir, preset)` from Task 1
- Produces: a `style.json` in the work dir whenever `--style` names a preset

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_styles_playbook.py`:

```python
# --- entry points ---

def test_refine_writes_style_after_refinement(tmp_path, monkeypatch):
    # Ordering matters: refine_plan() returns a fresh ShotPlan parsed from the
    # LLM. Anything written before it runs describes a plan that no longer
    # exists. This asserts save_style is called after, by recording the order.
    import pipeline.refine as refine_mod

    calls: list[str] = []

    def fake_refine_plan(plan, **kwargs):
        calls.append("refine_plan")
        return plan

    def fake_save_style(work_dir, preset):
        calls.append("save_style")
        return None

    monkeypatch.setattr(refine_mod, "refine_plan", fake_refine_plan, raising=False)
    monkeypatch.setattr(refine_mod, "save_style", fake_save_style, raising=False)

    # The helper under test is the small function extracted in Step 3.
    refine_mod._finalize_plan_artifacts(
        plan=object(), work_dir=tmp_path, preset=PRESETS["noir"],
        model="m", animate=False, do_polish=True, do_review=True,
        on_write=lambda p: None,
    )
    assert calls == ["refine_plan", "save_style"]


def test_finalize_writes_a_real_style_file(tmp_path, monkeypatch):
    import pipeline.refine as refine_mod
    monkeypatch.setattr(refine_mod, "refine_plan",
                        lambda plan, **kw: plan, raising=False)
    refine_mod._finalize_plan_artifacts(
        plan=object(), work_dir=tmp_path, preset=PRESETS["noir"],
        model="m", animate=False, do_polish=False, do_review=False,
        on_write=lambda p: None,
    )
    assert json.loads((tmp_path / "style.json").read_text())["name"] == "noir"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_styles_playbook.py -k finalize -v`
Expected: FAIL — `AttributeError: module 'pipeline.refine' has no attribute '_finalize_plan_artifacts'`

- [ ] **Step 3: Extract the shared finalize step in `pipeline/refine.py`**

`refine.py` and `run.py` both run "refine, then persist". Extract it once so the
ordering rule lives in a single place. Add to `pipeline/refine.py`:

```python
from .styles import save_style


def _finalize_plan_artifacts(*, plan, work_dir, preset, model, animate,
                             do_polish, do_review, on_write):
    """Run the refinement passes, then persist the resolved style.

    save_style runs last on purpose: refine_plan() returns a fresh ShotPlan
    parsed from the LLM, so a style file written before it would be describing a
    superseded plan.
    """
    if do_polish or do_review:
        from .script_agent import refine_plan
        plan = refine_plan(
            plan, model=model, animate=animate,
            polish=do_polish, review=do_review, on_write=on_write,
        )
    save_style(work_dir, preset)
    return plan
```

Then replace the existing refinement block in `main()` — currently:

```python
    if do_polish or do_review:
        from .script_agent import refine_plan
        plan = refine_plan(
            plan, model=args.model, animate=False,
            polish=do_polish, review=do_review,
            on_write=lambda p: (work_dir / "shot_plan.json").write_text(p.model_dump_json(indent=2)),
        )
```

with:

```python
    plan = _finalize_plan_artifacts(
        plan=plan, work_dir=work_dir,
        # Only persist a style when this invocation is actually establishing one:
        # a brand-new plan, or an explicit --style on an existing one. Passing
        # `style` unconditionally would let `python -m pipeline.refine <dir>` —
        # the plain "view this plan" command — silently rewrite an older video's
        # style.json from the VIDEO_STYLE env default, which is the same class of
        # bug (something unrelated picks the colours) this whole design removes.
        preset=style if (not is_existing_plan or args.style) else None,
        model=args.model, animate=False,
        do_polish=do_polish, do_review=do_review,
        on_write=lambda p: (work_dir / "shot_plan.json").write_text(p.model_dump_json(indent=2)),
    )
```

`style` and `is_existing_plan` are both already in scope in `main()` — `style` is
the result of `resolve_style(args.style)` (line 92), and `is_existing_plan` is set
at line 100.

Note `args.style` defaults to `os.environ.get("VIDEO_STYLE")`, so "explicit
`--style`" here means "a style was resolved for this invocation", including from
the env. That is the intended behaviour for a *new* plan; the `is_existing_plan`
guard is what stops it touching old ones.

- [ ] **Step 4: Wire the one-shot path in `pipeline/run.py`**

Find the plan stage's `refine_plan(...)` call in `run.py` and add, immediately
after the plan stage finishes and `shot_plan.json` has been written:

```python
    from .styles import save_style
    save_style(work_dir, style)
```

Use the same `style` variable `run.py` already resolves for the plan stage. If
`run.py` resumes a run whose plan stage is already done, this line is skipped
along with the rest of that stage — an existing `style.json` is left alone.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_styles_playbook.py -v`
Expected: PASS — 20 passed

- [ ] **Step 6: Verify against a real run (free)**

Run: `uv run python -m pipeline.refine "a lighthouse in a storm, 2 scenes" --style noir`
Expected: `output/<slug>/style.json` exists and contains `"name": "noir"`.
Then: `cat output/<slug>/style.json`

Clean up: `rm -rf output/<slug>`

- [ ] **Step 7: Commit**

```bash
git add pipeline/refine.py pipeline/run.py tests/test_styles_playbook.py
git commit -m "feat(styles): write style.json from both entry points

Extracts _finalize_plan_artifacts so the 'refine first, then persist style'
ordering exists in one place. refine_plan returns a fresh LLM-parsed plan, so a
style written before it would describe a superseded plan."
```

---

## Task 3: Images consume the consistency anchors

**Files:**
- Modify: `pipeline/schema.py` (one parameter on `expand()`)
- Modify: `pipeline/images/__init__.py`
- Test: `tests/test_style_consumers.py` (new)

**Interfaces:**
- Consumes: `load_style(work_dir)` from Task 1
- Produces: `ShotPlan.expand(..., extra_overhead: int = 0)`; image prompts that
  end with the anchors

- [ ] **Step 1: Write the failing tests**

Create `tests/test_style_consumers.py`:

```python
"""The four renderers reading one style source.

Each of these pins a drift that actually happened: image scenes re-interpreting
a style phrase per scene, and a quote card picking its colours from music_mood.
"""
import json
from pathlib import Path

import pytest

from pipeline.schema import ShotPlan
from pipeline.styles import PRESETS, save_style


def _plan(**over):
    base = {
        "title": "T", "description": "d", "tags": ["t"],
        "music_mood": "calm", "style_prefix": "cinematic photo",
        "scenes": [{"media_prompt": "a lighthouse", "narration": "hello"}],
    }
    base.update(over)
    return ShotPlan.model_validate(base)


def test_extra_overhead_changes_the_compaction_threshold():
    # expand() cannot see the anchors (they are not on ShotPlan), so callers
    # declare their length. The compaction branch is gated on
    # `len(refs) >= 3 and len(result) > budget`, so this only bites with three
    # or more characters actually referenced — a plan with none would exercise
    # nothing at all, and the test would pass against an implementation that
    # ignored extra_overhead entirely.
    chars = [{"name": n, "description": f"a person called {n}, " + "d" * 120}
             for n in ("ana", "ben", "cal")]
    plan = _plan(characters=chars,
                 scenes=[{"media_prompt": "{ana} and {ben} and {cal} talk",
                          "narration": "hi"}])
    text = "{ana} and {ben} and {cal} talk"

    roomy = plan.expand(text, include_style_overhead=True,
                        extra_overhead=0, max_chars=600)
    tight = plan.expand(text, include_style_overhead=True,
                        extra_overhead=400, max_chars=600)

    # Same budget, same text — only the declared overhead differs, and that must
    # be enough to push the tight case over the threshold into compaction.
    assert roomy != tight, "extra_overhead did not affect the compaction threshold"
    assert len(tight) < len(roomy)


def test_expand_extra_overhead_defaults_to_zero():
    # Every existing call site must behave exactly as before.
    plan = _plan()
    assert plan.expand("a lighthouse", include_style_overhead=True) == "a lighthouse"


def test_anchors_are_appended_to_scene_prompts(tmp_path, monkeypatch):
    import pipeline.images as images

    save_style(tmp_path, PRESETS["noir"])
    seen: list[str] = []

    class FakeProvider:
        name = "fake"
        requires = ""
        def available(self): return True
        def generate(self, prompt, query=None, negative=None, api_key=None,
                     model=None, on_preview_url=None):
            seen.append(prompt)
            return b"png"

    plan = _plan()
    images.generate_scene_image(plan, 0, FakeProvider(), fallback=False,
                               work_dir=tmp_path)
    assert seen, "provider was never called"
    for anchor in PRESETS["noir"]["consistency_anchors"]:
        assert anchor in seen[0], f"missing anchor: {anchor}"


def test_no_style_file_leaves_prompts_unchanged(tmp_path):
    import pipeline.images as images

    seen: list[str] = []

    class FakeProvider:
        name = "fake"
        requires = ""
        def available(self): return True
        def generate(self, prompt, query=None, negative=None, api_key=None,
                     model=None, on_preview_url=None):
            seen.append(prompt)
            return b"png"

    plan = _plan()
    images.generate_scene_image(plan, 0, FakeProvider(), fallback=False,
                               work_dir=tmp_path)
    assert "same high-contrast" not in seen[0]
    assert seen[0].startswith("cinematic photo")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_style_consumers.py -v`
Expected: FAIL — `TypeError: expand() got an unexpected keyword argument 'extra_overhead'`

- [ ] **Step 3: Add `extra_overhead` to `expand()`**

In `pipeline/schema.py`, change the signature and the budget line. Currently:

```python
        budget = max_chars
        if include_style_overhead:
            budget -= len(self.style_prefix) + 2  # ", " separator added by caller
```

Add `extra_overhead: int = 0` **after** `include_style_overhead` in the
keyword-only section (after the `*`), so every existing positional call site is
unaffected. The only current `include_style_overhead=True` caller is
`pipeline/images/__init__.py:116`. Then:

```python
        budget = max_chars
        if include_style_overhead:
            # style_prefix is prepended by the caller; extra_overhead covers
            # anything else the caller appends (the style's consistency anchors,
            # which live in style.json rather than on the plan).
            budget -= len(self.style_prefix) + 2 + extra_overhead
```

- [ ] **Step 4: Thread `work_dir` all the way to the prompt**

**This is the step the feature lives or dies on.** `generate_scene_image` is not
what a normal run calls — `generate_images()` is
(`pipeline/images/__init__.py:211`, called from `run.py:128` and
`images/__main__.py:51`). Its current signature is:

```python
def generate_images(plan: ShotPlan, out_dir: Path, backend: str | None = None) -> list[Path]:
```

and at line 232-233 it calls `generate_scene_image(plan, i, primary, fallback=…,
char_refs=refs)` with no `work_dir`. Adding the parameter only to
`generate_scene_image` leaves anchors permanently empty on every real run, while
every test that calls `generate_scene_image` directly still passes — a feature
that ships inert.

Add `work_dir: Path | None = None` to **both** functions, and pass it through:

```python
def generate_images(plan: ShotPlan, out_dir: Path, backend: str | None = None,
                    work_dir: Path | None = None) -> list[Path]:
    ...
        data, used = generate_scene_image(plan, i, primary, fallback=…,
                                          char_refs=refs, work_dir=work_dir)
```

Then update both callers to pass it: `pipeline/run.py:128` and
`pipeline/images/__main__.py:51` (the no-`--scene` path). Both already have the
work dir in scope. `images/__main__.py`'s `--scene N` path calls
`generate_scene_image` directly and also needs `work_dir=`.

Now add near the top of `generate_scene_image`:

```python
    from ..styles import load_style
    anchors = load_style(work_dir).get("consistency_anchors", []) if work_dir else []
    anchor_text = ", ".join(anchors)
```

Change the `expand` call to declare the overhead:

```python
    scene_prompt = plan.expand(scene.media_prompt, scene_outfit=scene.outfit,
                               include_style_overhead=True,
                               extra_overhead=len(anchor_text) + 2 if anchor_text else 0)
```

And change the prompt assembly at line 132 from:

```python
    prompt = f"{plan.style_prefix}, {scene_prompt}"
```

to:

```python
    prompt = f"{plan.style_prefix}, {scene_prompt}"
    if anchor_text:
        prompt = f"{prompt}, {anchor_text}"
```

Also append the anchors to the two reference-portrait prompts in
`character_refs()` (`pipeline/images/__init__.py:88` and `:92`). Those portraits
are the visual anchor every character scene is edited from, so leaving them
un-anchored means the reference itself is not held to the same colour grade the
scenes are. `character_refs()` gains the same `work_dir: Path | None = None`
parameter and is called from `generate_images()`, which now has it.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_style_consumers.py -v`
Expected: PASS — 4 passed

- [ ] **Step 6: Run the whole suite**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS — no regressions in `test_expand.py` or `test_image_provider_selection.py`

- [ ] **Step 7: Commit**

```bash
git add pipeline/schema.py pipeline/images/__init__.py tests/test_style_consumers.py
git commit -m "feat(images): append the style's consistency anchors to every prompt

style_prefix is a phrase the model re-reads per scene, so neighbouring scenes
drift. Anchors state the invariants explicitly, the positive counterpart to
global_negative. expand() gains extra_overhead because the anchors live in
style.json and it cannot see them when computing the prompt budget."
```

---

## Task 4: Compose cards read the palette

**Files:**
- Modify: `pipeline/compose/__init__.py`
- Test: `tests/test_style_consumers.py` (append)

**Interfaces:**
- Consumes: `load_style(work_dir)` from Task 1
- Produces: `_palette_for(plan, work_dir=None)` preferring the style file

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_style_consumers.py`:

```python
# --- compose ---

def test_palette_comes_from_style_not_music_mood(tmp_path):
    # The bug this fixes: a plan whose style_prefix said "warm desert tones" got
    # a purple quote card, because the palette was looked up by music_mood.
    import pipeline.compose as compose

    save_style(tmp_path, PRESETS["cinematic"])
    plan = _plan(music_mood="inspiring")  # would have selected the purple palette
    palette = compose._palette_for(plan, work_dir=tmp_path)
    assert palette == PRESETS["cinematic"]["palette"]
    assert palette["bg1"] != compose.MOOD_PALETTES["inspiring"]["bg1"]


def test_palette_falls_back_to_music_mood_without_style(tmp_path):
    # Every existing output/*/ folder is in this state.
    import pipeline.compose as compose

    plan = _plan(music_mood="inspiring")
    assert compose._palette_for(plan, work_dir=tmp_path) == compose.MOOD_PALETTES["inspiring"]


def test_partial_palette_falls_back_per_key(tmp_path):
    # A hand-edited style.json missing one key must not produce a card with an
    # empty background; only that key falls back.
    import pipeline.compose as compose

    (tmp_path / "style.json").write_text(json.dumps({"palette": {"accent": "#ff0000"}}))
    palette = compose._palette_for(_plan(music_mood="calm"), work_dir=tmp_path)
    assert palette["accent"] == "#ff0000"
    assert palette["bg1"] == compose.MOOD_PALETTES["calm"]["bg1"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_style_consumers.py -k palette -v`
Expected: FAIL — `TypeError: _palette_for() got an unexpected keyword argument 'work_dir'`

- [ ] **Step 3: Implement**

In `pipeline/compose/__init__.py`, replace:

```python
def _palette_for(plan: ShotPlan) -> dict[str, str]:
    return MOOD_PALETTES.get((plan.music_mood or "").strip().lower(), _DEFAULT_PALETTE)
```

with:

```python
def _palette_for(plan: ShotPlan, work_dir: Path | None = None) -> dict[str, str]:
    """The card palette, preferring the video's own style.

    Falls back to the music-mood table per key, so a work dir with no style.json
    behaves exactly as before and a partially hand-edited palette cannot produce
    an unreadable card.
    """
    base = MOOD_PALETTES.get((plan.music_mood or "").strip().lower(), _DEFAULT_PALETTE)
    if work_dir is None:
        return base
    from ..styles import load_style
    override = load_style(work_dir).get("palette") or {}
    return {**base, **{k: v for k, v in override.items() if v}}
```

Update the one call site (`render_compositions`, currently `palette =
_palette_for(plan)`) to `palette = _palette_for(plan, work_dir)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_style_consumers.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add pipeline/compose/__init__.py tests/test_style_consumers.py
git commit -m "fix(compose): card palette comes from the style, not the soundtrack

_palette_for looked the palette up by music_mood, so a video whose images were
warm gold rendered a dark purple quote card. It now prefers the video's own
palette and falls back per key, so existing work dirs are unaffected."
```

---

## Task 5: Captions and overlays read the style

**Files:**
- Modify: `pipeline/assemble.py`
- Test: `tests/test_style_consumers.py` (append)

**Interfaces:**
- Consumes: `load_style(work_dir)` from Task 1
- Produces: `_hex_to_ass(hex_colour) -> str`, `_hex_to_drawtext(hex_colour) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_style_consumers.py`:

```python
# --- captions and overlays ---

def test_hex_to_ass_reverses_byte_order():
    # libass takes &HAABBGGRR — blue first. Passing #rrggbb straight through
    # produces the wrong colour silently, with no error anywhere.
    import pipeline.assemble as assemble
    assert assemble._hex_to_ass("#f4ead6") == "&H00D6EAF4"
    assert assemble._hex_to_ass("#000000") == "&H00000000"


def test_hex_to_drawtext_keeps_byte_order():
    import pipeline.assemble as assemble
    assert assemble._hex_to_drawtext("#f4ead6") == "0xf4ead6"


def test_caption_filter_uses_style_values(tmp_path):
    import pipeline.assemble as assemble

    save_style(tmp_path, PRESETS["retro-pixel"])
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    filt = assemble._subtitle_filter("s.srt", srt, style=json.loads(
        (tmp_path / "style.json").read_text()))
    assert "FontSize=20" in filt          # retro-pixel caption_size
    assert "Outline=3" in filt            # retro-pixel caption_outline
    assert assemble._hex_to_ass(PRESETS["retro-pixel"]["palette"]["fg"]) in filt


def test_caption_filter_without_style_keeps_todays_values(tmp_path):
    import pipeline.assemble as assemble
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    filt = assemble._subtitle_filter("s.srt", srt, style={})
    assert "FontSize=18" in filt
    assert "Outline=2" in filt
    assert "MarginV=40" in filt


def test_overlay_filter_uses_style_values():
    import pipeline.assemble as assemble
    if assemble._FONT is None:
        pytest.skip("no drawtext font discovered on this machine")
    filt = assemble._overlay_filter("Hello", style=PRESETS["noir"])
    assert "fontsize=56" in filt          # noir overlay_size
    assert "borderw=4" in filt            # noir overlay_border
    assert assemble._hex_to_drawtext(PRESETS["noir"]["palette"]["fg"]) in filt


def test_overlay_filter_without_style_keeps_todays_values():
    import pipeline.assemble as assemble
    if assemble._FONT is None:
        pytest.skip("no drawtext font discovered on this machine")
    filt = assemble._overlay_filter("Hello", style={})
    assert "fontsize=58" in filt
    assert "fontcolor=white" in filt
    assert "borderw=3" in filt
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_style_consumers.py -k "hex or caption or overlay" -v`
Expected: FAIL — `AttributeError: module 'pipeline.assemble' has no attribute '_hex_to_ass'`

- [ ] **Step 3: Add the colour converters**

Add near the top of `pipeline/assemble.py`:

```python
def _hex_to_ass(hex_colour: str) -> str:
    """#rrggbb -> &HAABBGGRR for libass force_style.

    libass stores colours blue-first with alpha leading. Handing it an #rrggbb
    string produces a wrong-but-plausible colour and no error, so every colour
    reaching force_style must come through here.
    """
    h = hex_colour.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _hex_to_drawtext(hex_colour: str) -> str:
    """#rrggbb -> 0xrrggbb for ffmpeg drawtext fontcolor."""
    return "0x" + hex_colour.lstrip("#").lower()
```

- [ ] **Step 4: Make the two filters style-aware**

Change `_subtitle_filter` to accept `style: dict | None = None` and build its
`force_style` from it, keeping today's literals as the defaults:

```python
    text = (style or {}).get("text") or {}
    palette = (style or {}).get("palette") or {}
    size = text.get("caption_size", 18)
    outline = text.get("caption_outline", 2)
    colour = f",PrimaryColour={_hex_to_ass(palette['fg'])}" if palette.get("fg") else ""
    return (f",subtitles={rel_path}:force_style="
            f"'FontSize={size},Bold=1,Outline={outline},MarginV=40{colour}'")
```

Change `_overlay_filter` to accept `style: dict | None = None`:

```python
    text_cfg = (style or {}).get("text") or {}
    palette = (style or {}).get("palette") or {}
    size = text_cfg.get("overlay_size", 58)
    border = text_cfg.get("overlay_border", 3)
    colour = _hex_to_drawtext(palette["fg"]) if palette.get("fg") else "white"
    return (f",drawtext=fontfile='{_FONT}':text='{esc}':fontsize={size}:"
            f"fontcolor={colour}:borderw={border}:bordercolor=black@0.8:"
            f"x=(w-text_w)/2:y=70")
```

In `assemble()`, load the style once and pass it to both call sites:

```python
    from .styles import load_style
    style = load_style(work_dir)
```

`load_style()` is a plain file read, so a relative `work_dir` works regardless.

**Branch dependency:** the `work_dir = Path(work_dir).resolve()` fix lives on
`fix/assemble-relative-path` (commit `8a34696`) and is **not** on this branch or
on `main`. Until it merges, `python -m pipeline.assemble output/<dir>` with a
relative path fails with "Error opening input file" — unrelated to this work, but
it blocks Task 6's verification. Either merge that branch first or use an
absolute path when verifying.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_style_consumers.py -v`
Expected: PASS — 13 passed

- [ ] **Step 6: Commit**

```bash
git add pipeline/assemble.py tests/test_style_consumers.py
git commit -m "feat(assemble): captions and overlays take colour from the style

Both were hardcoded (FontSize=18 / white 58px), so they could not match either
the images or the cards. Colours come from the style's palette, which is why
they cannot disagree with the compose cards. libass wants &HAABBGGRR and
drawtext wants 0xRRGGBB — separate converters, because passing #rrggbb to
libass yields a wrong colour and no error."
```

---

## Task 6: End-to-end verification

**Files:** none — this task verifies Tasks 1–5.

- [ ] **Step 1: Full suite**

Run: `make test`
Expected: exit 0.

Note: this requires `fix/refining-status-stale-tests` to be merged. If it is not,
four pre-existing Django failures appear that are unrelated to this work — verify
they are exactly `RunPlanStageTest.test_happy_path`,
`RunRefineStageTest.test_happy_path`, `test_review_to_planning`,
`test_failed_to_review`, and proceed.

- [ ] **Step 2: Regenerate the Alchemist plan's card and compare**

The purple-card bug is the headline fix, so reproduce it directly. Using the
existing `output/discovering-the-alchemist/` work dir:

```bash
uv run python -c "
from pathlib import Path
from pipeline.styles import PRESETS, save_style
save_style(Path('output/discovering-the-alchemist'), PRESETS['cinematic'])
"
uv run python -m pipeline.compose output/discovering-the-alchemist
ffmpeg -y -v quiet -ss 2 -i output/discovering-the-alchemist/video/scene_03.mp4 \
  -frames:v 1 /tmp/card-after.png
```

Expected: `/tmp/card-after.png` is warm (cinematic `bg1 #0b0b12` → `bg2 #3a1f22`),
not the purple `#0f0b1e` → `#4a2f52` it rendered before. Open it and confirm.

- [ ] **Step 2b: Verify anchors reach a real run**

The blocking risk is that anchors are wired only into `generate_scene_image` and
never reach `generate_images`, leaving the feature inert while all unit tests
pass. Prove it end to end:

```bash
uv run python -m pipeline.refine "a bell tower at dusk, 2 scenes" --style noir
uv run python -m pipeline.images output/<slug> --backend placeholder 2>&1 | head
uv run python -c "
from pathlib import Path
from pipeline.styles import load_style
print(load_style(Path('output/<slug>'))['consistency_anchors'])
"
```

Expected: `style.json` exists with the noir anchors. Then confirm the anchors
actually reach a prompt by adding a temporary print, or by running with a real
backend and inspecting the provider call. The placeholder backend ignores prompts,
so the unit test in Task 3 is the binding check — but `style.json` being present
and `generate_images` accepting `work_dir` is what proves the wiring.

Clean up: `rm -rf output/<slug>`

- [ ] **Step 3: Backward compatibility on a real untouched work dir**

Pick any `output/*/` folder that has no `style.json` and re-assemble it:

```bash
ls output/*/style.json 2>/dev/null   # confirm which dirs are untouched
uv run python -m pipeline.assemble "$(pwd)/output/<an-untouched-dir>"
```

(Absolute path per the branch dependency noted in Task 5.)

Expected: renders successfully, captions look exactly as before.

- [ ] **Step 4: Full free run with a style**

```bash
uv run python -m pipeline.refine "two friends watch a meteor shower, 3 scenes" --style noir
uv run python -m pipeline.images output/<slug> --backend placeholder
uv run python -m pipeline.voiceover output/<slug>
uv run python -m pipeline.compose output/<slug>
uv run python -m pipeline.assemble output/<slug>
```

Expected: `style.json` written with `"name": "noir"`; the final video's captions
use the noir foreground colour. Costs ~$0.001 for the plan; images are free on
the placeholder backend.

Clean up: `rm -rf output/<slug>`

- [ ] **Step 5: Confirm nothing out of scope changed**

```bash
git diff origin/main --stat -- backend/ webapp/ remotion/ pyproject.toml
```

Expected: **empty**. Any output violates a global constraint.

- [ ] **Step 6: Push**

```bash
git push -u origin feat/style-playbook
```

---

## Success criteria

1. A video generated with `--style cinematic` has cards, captions and overlays
   whose colours come from the same palette as its images. *(Step 2, Step 4)*
2. The Alchemist card renders warm rather than purple. *(Step 2)*
3. Every existing `output/*/` folder renders unchanged, and viewing an existing
   plan never creates or overwrites its `style.json`. *(Step 3, Task 2 guard)*
4. No new dependency, no TypeScript change, no web-app change. *(Step 5)*
5. `tests/test_styles_playbook.py` and `tests/test_style_consumers.py` pass, and
   the pre-existing suite is unaffected. *(Step 1)*

---

## Task 7: A palette for the default path (added after Task 5)

**Why this exists.** Tasks 1–5 fix the drift only when `--style <preset>` is
passed. The video that motivated the whole feature — "Discovering The Alchemist"
— was generated with **no** `--style`: the LLM freely chose
`style_prefix: "cinematic photo, warm desert tones, soft golden hour light"`, so
`resolve_style(None)` returned `None`, no `style.json` was written, and the card
fell back to `music_mood` and rendered purple. On the default path nothing
changed.

**How OpenMontage solves it.** It has no "no style" path at all.
`lib/playbook_generator.py`: *"When none of the existing 4 playbooks match the
production brief, the agent can generate a custom playbook. This replaces the old
behavior of forcing everything through the closest preset."* The generated
playbook is `jsonschema.validate`d (line 214) before use. The model supplies the
values; the schema guarantees the shape.

**The reversal, stated plainly.** The spec says style must never go on `ShotPlan`
because that model is the LLM's structured-output contract. This task adds
exactly one field to it — `palette` — because we now *want* the model to author
that one value. The spec's original reasoning still holds for everything else:
`consistency_anchors` and `text` stay off the plan. A preset, when given, always
overrides whatever the model proposed.

**Files:**
- Modify: `pipeline/schema.py` (add `palette` to `ShotPlan`)
- Modify: `pipeline/styles.py` (add `validate_palette`)
- Modify: `pipeline/refine.py`, `pipeline/run.py` (fall back to the plan's palette)
- Test: `tests/test_styles_playbook.py` (append)

**Interfaces:**
- Consumes: `save_style`, `load_style` from Task 1
- Produces: `validate_palette(raw) -> dict | None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_styles_playbook.py`:

```python
# --- LLM-proposed palettes for the no-preset path ---

from pipeline.styles import validate_palette


def test_validate_palette_accepts_four_hex_keys_and_derives_glow():
    # The model supplies four colours; glow is derived so it cannot be malformed
    # and the model has one less thing to get wrong.
    out = validate_palette({"bg1": "#0b0b12", "bg2": "#3a1f22",
                            "fg": "#f4ead6", "accent": "#e0714a"})
    assert set(out) == {"bg1", "bg2", "fg", "accent", "glow"}
    assert out["accent"] == "#e0714a"
    assert out["glow"].startswith("rgba(224,113,74,")


def test_validate_palette_normalises_case():
    out = validate_palette({"bg1": "#0B0B12", "bg2": "#3A1F22",
                            "fg": "#F4EAD6", "accent": "#E0714A"})
    assert out["bg1"] == "#0b0b12"


@pytest.mark.parametrize("bad", [
    None,
    "purple",
    {},
    {"bg1": "#0b0b12"},                                   # incomplete
    {"bg1": "warm", "bg2": "#3a1f22", "fg": "#f4ead6", "accent": "#e0714a"},
    {"bg1": "#0b0b1", "bg2": "#3a1f22", "fg": "#f4ead6", "accent": "#e0714a"},
    {"bg1": "#zzzzzz", "bg2": "#3a1f22", "fg": "#f4ead6", "accent": "#e0714a"},
])
def test_validate_palette_rejects_bad_input(bad):
    # Anything the model gets wrong must fall back to today's behaviour rather
    # than reaching Remotion or libass, where a bad value is a silent wrong
    # colour rather than an error.
    assert validate_palette(bad) is None


def test_preset_beats_the_models_proposal(tmp_path):
    # A named style is a promise that two videos in that style match. The
    # model's per-video suggestion must never override it.
    from pipeline.styles import PRESETS, resolve_style, style_for_plan
    proposed = {"bg1": "#111111", "bg2": "#222222",
                "fg": "#333333", "accent": "#444444"}
    chosen = style_for_plan(resolve_style("noir"), proposed)
    assert chosen["palette"] == PRESETS["noir"]["palette"]


def test_model_palette_used_when_no_preset():
    from pipeline.styles import style_for_plan
    proposed = {"bg1": "#111111", "bg2": "#222222",
                "fg": "#333333", "accent": "#444444"}
    chosen = style_for_plan(None, proposed)
    assert chosen["palette"]["bg1"] == "#111111"
    assert chosen["consistency_anchors"] == []


def test_no_preset_and_no_proposal_yields_nothing():
    from pipeline.styles import style_for_plan
    assert style_for_plan(None, None) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_styles_playbook.py -k "palette or preset_beats or style_for_plan" -v`
Expected: FAIL — `ImportError: cannot import name 'validate_palette'`

- [ ] **Step 3: Add `validate_palette` and `style_for_plan` to `pipeline/styles.py`**

```python
import re

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_PALETTE_REQUIRED = ("bg1", "bg2", "fg", "accent")


def validate_palette(raw: object) -> dict[str, str] | None:
    """A model-proposed palette, or None if it is not usable.

    Mirrors OpenMontage's playbook_generator, which jsonschema-validates a
    generated playbook before use: the model supplies the values, the validator
    guarantees the shape. A bad colour must never reach Remotion or libass,
    where it renders wrong rather than raising.

    `glow` is derived from `accent` rather than requested, so it cannot be
    malformed and the model has one fewer field to get wrong.
    """
    if not isinstance(raw, dict):
        return None
    out: dict[str, str] = {}
    for key in _PALETTE_REQUIRED:
        value = raw.get(key)
        if not isinstance(value, str) or not _HEX.match(value):
            return None
        out[key] = value.lower()
    r, g, b = (int(out["accent"][i:i + 2], 16) for i in (1, 3, 5))
    out["glow"] = f"rgba({r},{g},{b},0.24)"
    return out


def style_for_plan(preset: dict | None, proposed: object) -> dict | None:
    """The style to persist: a named preset always wins over the model.

    A preset is a promise that every video in that style matches; a per-video
    suggestion must not break it. With no preset, a valid proposal is better
    than the music_mood fallback, which is what the card would otherwise use.
    """
    if preset:
        return preset
    palette = validate_palette(proposed)
    if not palette:
        return None
    return {"palette": palette, "consistency_anchors": [], "text": {}}
```

- [ ] **Step 4: Add the field to `ShotPlan`**

In `pipeline/schema.py`, add to `ShotPlan`:

```python
    palette: Optional[dict[str, str]] = Field(
        default=None,
        description=(
            "Four hex colours matching style_prefix, for the text cards and "
            "captions so they match the generated images: bg1 (darkest "
            "background), bg2 (lighter background for a gradient), fg (text, "
            "high contrast against bg1), accent (a highlight drawn from the "
            "imagery). Format #rrggbb. Omit only if the style is purely "
            "photographic with no dominant colour."
        ),
    )
```

This is the one field the model is asked to author, and it is deliberate — see
this task's preamble.

- [ ] **Step 5: Use it in both entry points**

In `pipeline/refine.py`, replace the `preset=` argument with the resolved choice:

```python
        preset=(style_for_plan(style, getattr(plan, "palette", None))
                if (not is_existing_plan or style_explicit) else None),
```

In `pipeline/run.py`, replace `save_style(work_dir, style)` with:

```python
        save_style(work_dir, style_for_plan(style, getattr(plan, "palette", None)))
```

Import `style_for_plan` alongside the existing `save_style` import in both files.
`getattr` is used so an older plan object without the field cannot raise.

- [ ] **Step 6: Run the tests**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS — the pre-existing 7 `test_voiceover_helpers` errors remain.

- [ ] **Step 7: Verify on a real free run**

```bash
uv run python -m pipeline.refine "a lantern in a snowstorm, 2 scenes"
cat output/<slug>/style.json
```

Expected: a `style.json` exists **with no `--style` flag**, carrying a palette the
model chose to match its own `style_prefix`. That is the case that was broken.

Clean up: `rm -rf output/<slug>`

- [ ] **Step 8: Commit**

```bash
git add pipeline/schema.py pipeline/styles.py pipeline/refine.py pipeline/run.py tests/test_styles_playbook.py
git commit -m "feat(styles): let the model propose a palette when no preset is given"
```
