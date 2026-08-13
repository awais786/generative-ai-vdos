# Agentic Pipeline Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a developer open this repo in Claude Code, say "make me a video about X", and get a correct video with review gates at plan and images and no unapproved spending.

**Architecture:** Four layers, only one of which is new code. A `pipeline/registry.py` preflight module reports what works on this machine; an `AGENT_GUIDE.md` holds the production contract; four stage-director skills tell the agent how to run each stage; `CLAUDE.md` gains a routing line. The agent drives the existing `python -m pipeline.*` stage CLIs — no new caller alongside the CLI and Celery paths.

**Tech Stack:** Python 3.13+, pytest (with `monkeypatch`), stdlib only for the registry (`argparse`, `dataclasses`, `json`, `shutil`, `subprocess`, `importlib.util`). Markdown for the guide and skills.

**Spec:** `docs/superpowers/specs/2026-08-12-agentic-pipeline-interface-design.md`

## Global Constraints

- Python 3.13+ — use `X | None` union syntax, not `Optional[X]`.
- The registry uses **stdlib only**. No new dependencies in `pyproject.toml`.
- The registry makes **no network calls**. API-backed entries are reported as `configured`, never `verified`, because live probes cost money and add latency to every run.
- Never modify `pipeline/schema.py`, `pipeline/run.py`, the four stage CLIs, `state.json` handling, `backend/apps/projects/*`, or anything under `webapp/`.
- `pipeline/video/__main__.py` stays commented out. The registry reports video as `disabled-by-policy` **regardless** of whether `DASHSCOPE_API_KEY` is set.
- `gpt-image-1` must never be reported as auto-selectable. It is reported with state `paid`.
- Registry `main()` always exits `0`. It reports; it does not gate.
- Follow the existing test style in `tests/test_image_provider_selection.py`: pytest functions, `monkeypatch`, a docstring explaining *why* the behavior matters.
- Stage-director skills use the same `SKILL.md` frontmatter as the existing 5 skills: `---` / `name:` / `description:` (with trigger terms) / `---`.
- Commit after every task.

---

## File Structure

| File | Responsibility |
|---|---|
| `pipeline/registry.py` | **New.** All preflight probing. One `Capability` record type, one probe function per capability group, a table renderer, a CLI. |
| `tests/test_registry.py` | **New.** Unit tests for every probe and the pure helpers. |
| `AGENT_GUIDE.md` | **New.** Production contract the agent reads before making a video. |
| `.claude/skills/{plan,images,voiceover,assemble}-director/SKILL.md` | **New.** One director per stage. |
| `CLAUDE.md` | **Modify.** Add routing line; fix stale test claim; replace the Money-rules body with a pointer so there is one source of truth. |
| `.env.example` | **Modify.** Add 7 missing vars. |
| `Makefile` | **Modify.** Add a `preflight` target; register `tests/test_registry.py` in `test`. |

## Deviations from the spec

Two spec items are deliberately dropped. Both are recorded here rather than
silently omitted; revisit if either turns out to matter.

1. **`pipeline/images/__init__.py` is not modified.** The spec proposed adding a
   `describe()` helper for the registry to read. But `PROVIDERS`, `p.name`,
   `p.requires`, `p.available()`, and `AUTO_EXCLUDE` are already public and
   sufficient — a wrapper would be indirection with no second caller. The
   Makefile takes its place in the modified-files list, so the count stays at 3.

2. **No `probe_config()`.** The spec's check table has a "Config" row for env
   vars the code reads but that are unset. It is dropped as redundant: every
   `MISSING` row already names the exact env var that would fix it
   (`pexels — PEXELS_API_KEY not set`), so a separate list would repeat that
   information without an actionable target. A standalone list of *every*
   unset optional var would also be mostly noise, since most are optional
   model-name overrides with working defaults.

---

## Task 1: Capability model and provider probes

**Files:**
- Create: `pipeline/registry.py`
- Create: `tests/test_registry.py`
- Modify: `Makefile` (register the new test file in the `test` target)

**Interfaces:**
- Consumes: `pipeline.images.PROVIDERS`, `pipeline.images.AUTO_EXCLUDE`, `pipeline.video.PROVIDERS`, `pipeline.script_agent.default_model()`
- Produces:
  - `class State` with string constants `AVAILABLE = "available"`, `MISSING = "missing"`, `PAID = "paid"`, `DISABLED = "disabled"`
  - `@dataclass(frozen=True) class Capability(group: str, name: str, state: str, detail: str = "", hint: str = "")`
  - `probe_llm() -> list[Capability]`
  - `probe_images() -> list[Capability]`
  - `probe_video() -> list[Capability]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_registry.py`:

```python
"""Preflight regression tests.

The registry exists so a run fails in second one rather than at minute nine.
These tests pin the three behaviors that make it trustworthy: it never reports
the paid backend as auto-selectable, it never reports the animation stage as
runnable, and it detects a libass-less ffmpeg (which otherwise fails only at
the very last assemble step, after every asset is already paid for).
"""
import pipeline.registry as registry
from pipeline.registry import Capability, State


def _by_name(caps: list[Capability], name: str) -> Capability:
    matches = [c for c in caps if c.name == name]
    assert matches, f"no capability named {name!r} in {[c.name for c in caps]}"
    return matches[0]


def test_llm_missing_provider_reports_remediation(monkeypatch):
    # default_model() raises when LLM_PROVIDER is unset; the registry must turn
    # that into a MISSING row carrying the message, not propagate the exception.
    def boom() -> str:
        raise RuntimeError("no LLM provider set — put LLM_PROVIDER in .env")

    monkeypatch.setattr(registry, "default_model", boom)
    cap = _by_name(registry.probe_llm(), "plan model")
    assert cap.state == State.MISSING
    assert "LLM_PROVIDER" in cap.detail


def test_llm_configured_reports_model(monkeypatch):
    monkeypatch.setattr(registry, "default_model", lambda: "gpt-4o-mini")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    cap = _by_name(registry.probe_llm(), "gpt-4o-mini")
    assert cap.state == State.AVAILABLE
    assert "configured" in cap.detail


def test_images_paid_backend_never_available(monkeypatch):
    # Even with a working key, gpt-image-1 must read as PAID (explicit opt-in),
    # never AVAILABLE — otherwise an agent could treat it as a free default.
    import pipeline.images as images
    for p in images.PROVIDERS:
        monkeypatch.setattr(p, "available", lambda: True)
    cap = _by_name(registry.probe_images(), "gpt-image-1")
    assert cap.state == State.PAID


def test_images_unavailable_backend_names_its_env_var(monkeypatch):
    import pipeline.images as images
    for p in images.PROVIDERS:
        monkeypatch.setattr(p, "available", lambda: False)
    cap = _by_name(registry.probe_images(), "pexels")
    assert cap.state == State.MISSING
    assert "PEXELS_API_KEY" in cap.detail


def test_video_disabled_even_with_key(monkeypatch):
    # The money rule is enforced by pipeline/video/__main__.py being commented
    # out. Preflight must reflect policy, not key presence.
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-real-looking-key")
    caps = registry.probe_video()
    assert caps, "expected at least one video provider"
    assert all(c.state == State.DISABLED for c in caps)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.registry'`

- [ ] **Step 3: Write the minimal implementation**

Create `pipeline/registry.py`:

```python
"""Preflight — what works on this machine right now.

Every pipeline stage depends on something that can be absent: an API key, a
Node install, an ffmpeg built with libass. Without this module those absences
surface mid-run, after assets have been generated and paid for. `assemble.py`
checks that ffmpeg exists but not that it can render subtitles, so a plain
Homebrew ffmpeg on macOS fails at the very last step of the very last stage.

Reports configuration, not liveness. An entry marked "configured" means the
credential is present, NOT that it works — a revoked key still reads as
configured. Live probes would cost money and add latency to every run, so
callers must pass that caveat on to the user.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .images import AUTO_EXCLUDE, PROVIDERS as IMAGE_PROVIDERS
from .script_agent import default_model
from .video import PROVIDERS as VIDEO_PROVIDERS


class State:
    """Capability states. Plain strings so `--json` output stays readable."""
    AVAILABLE = "available"
    MISSING = "missing"
    PAID = "paid"            # usable, but only via an explicit opt-in flag
    DISABLED = "disabled"    # turned off by policy, regardless of config


@dataclass(frozen=True)
class Capability:
    """One probed capability: what it is, whether it works, and how to fix it."""
    group: str
    name: str
    state: str
    detail: str = ""
    hint: str = ""


def probe_llm() -> list[Capability]:
    """The shot-plan model. `default_model()` already encodes the rules — it
    requires LLM_PROVIDER plus that provider's key and raises with a
    remediation message otherwise. Reuse it rather than restating them."""
    try:
        model = default_model()
    except RuntimeError as exc:
        return [Capability("llm", "plan model", State.MISSING, str(exc),
                           hint="set LLM_PROVIDER and its API key in .env")]
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    return [Capability("llm", model, State.AVAILABLE,
                       f"configured via LLM_PROVIDER={provider}")]


def probe_images() -> list[Capability]:
    """One row per image backend, in PROVIDERS order (= auto-pick priority)."""
    caps: list[Capability] = []
    for provider in IMAGE_PROVIDERS:
        if provider.name in AUTO_EXCLUDE:
            caps.append(Capability(
                "images", provider.name, State.PAID,
                "paid — never auto-picked",
                hint=f"use --backend {provider.name} to opt in explicitly"))
        elif provider.available():
            caps.append(Capability("images", provider.name, State.AVAILABLE,
                                   "configured"))
        else:
            need = provider.requires or "credentials"
            caps.append(Capability("images", provider.name, State.MISSING,
                                   f"{need} not set",
                                   hint=f"set {need} in .env"))
    return caps


def probe_video() -> list[Capability]:
    """Animation is disabled by policy — pipeline/video/__main__.py is
    commented out because a run spends limited DashScope credit. Report that
    regardless of whether DASHSCOPE_API_KEY happens to be set."""
    return [Capability("video", provider.name, State.DISABLED,
                       "DISABLED by policy (money rule)",
                       hint="uncomment pipeline/video/__main__.py to re-enable")
            for provider in VIDEO_PROVIDERS]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_registry.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Register the test file in the Makefile**

In `Makefile`, find the `test:` target:

```make
test:
	uv sync --all-extras
	$(MANAGE) test apps
	$(PY) -m pytest tests/test_pipeline_isolation.py
	$(PY) -m tests.test_expand
```

Add the new file (`make test` runs named files, so a new test file is invisible until listed):

```make
test:
	uv sync --all-extras
	$(MANAGE) test apps
	$(PY) -m pytest tests/test_pipeline_isolation.py tests/test_registry.py
	$(PY) -m tests.test_expand
```

- [ ] **Step 6: Verify the existing suite still passes**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS — all pre-existing tests plus the 5 new ones

- [ ] **Step 7: Commit**

```bash
git add pipeline/registry.py tests/test_registry.py Makefile
git commit -m "feat(registry): capability model and LLM/image/video probes

Reports what works on this machine. Paid gpt-image-1 reads as PAID (never
auto-selectable) and the animation stage reads as DISABLED regardless of
DASHSCOPE_API_KEY, matching the money rules enforced in code."
```

---

## Task 2: System probes — voiceover, compose, assemble

**Files:**
- Modify: `pipeline/registry.py` (append)
- Modify: `tests/test_registry.py` (append)

**Interfaces:**
- Consumes: `State`, `Capability` from Task 1
- Produces:
  - `_has_subtitles_filter(filters_output: str) -> bool` — pure parser
  - `_ffmpeg_hint() -> str` — platform-specific remediation string
  - `probe_voiceover() -> list[Capability]`
  - `probe_compose() -> list[Capability]`
  - `probe_assemble() -> list[Capability]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_registry.py`:

```python
# --- system probes ---

# Real `ffmpeg -hide_banner -filters` output is a flags/name/signature/description
# table. Two fixtures: one from a libass build, one without.
FILTERS_WITH_LIBASS = """\
Filters:
 T.. ass               V->V       Render ASS subtitles onto input video using the libass library.
 ... scale             V->V       Scale the input video size.
 T.. subtitles         V->V       Render text subtitles onto input video using the libass library.
"""

FILTERS_WITHOUT_LIBASS = """\
Filters:
 ... scale             V->V       Scale the input video size.
 ... overlay           VV->V      Overlay a video source on top of the input.
"""


def test_subtitles_filter_detected():
    assert registry._has_subtitles_filter(FILTERS_WITH_LIBASS) is True


def test_subtitles_filter_absent():
    assert registry._has_subtitles_filter(FILTERS_WITHOUT_LIBASS) is False


def test_subtitles_not_matched_by_description_text():
    # A naive substring search matches the word "subtitles" inside the `ass`
    # filter's description and reports a false positive. Match the name column.
    only_ass = " T.. ass               V->V       Render ASS subtitles onto input video.\n"
    assert registry._has_subtitles_filter(only_ass) is False


def test_assemble_reports_missing_libass(monkeypatch):
    # The failure this whole module exists to prevent: ffmpeg present, libass
    # absent, so assemble.py dies on the subtitles filter after everything else
    # has already been generated and paid for.
    monkeypatch.setattr(registry.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(registry, "_ffmpeg_filters", lambda ffmpeg: FILTERS_WITHOUT_LIBASS)
    cap = _by_name(registry.probe_assemble(), "libass")
    assert cap.state == State.MISSING
    assert "captions" in cap.detail.lower()
    assert cap.hint


def test_assemble_reports_present_libass(monkeypatch):
    monkeypatch.setattr(registry.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(registry, "_ffmpeg_filters", lambda ffmpeg: FILTERS_WITH_LIBASS)
    cap = _by_name(registry.probe_assemble(), "libass")
    assert cap.state == State.AVAILABLE


def test_assemble_missing_ffmpeg_short_circuits(monkeypatch):
    # No ffmpeg at all: report that one fact and stop, rather than emitting a
    # confusing "libass missing" row that implies ffmpeg is installed.
    monkeypatch.setattr(registry.shutil, "which", lambda name: None)
    caps = registry.probe_assemble()
    assert [c.name for c in caps] == ["ffmpeg"]
    assert caps[0].state == State.MISSING


def test_compose_missing_node(monkeypatch):
    monkeypatch.setattr(registry.shutil, "which", lambda name: None)
    cap = _by_name(registry.probe_compose(), "Remotion")
    assert cap.state == State.MISSING
    assert "node" in cap.detail.lower()


def test_compose_missing_node_modules(monkeypatch, tmp_path):
    monkeypatch.setattr(registry.shutil, "which", lambda name: "/usr/bin/node")
    monkeypatch.setattr(registry, "REMOTION_DIR", tmp_path)
    cap = _by_name(registry.probe_compose(), "Remotion")
    assert cap.state == State.MISSING
    assert "npm install" in cap.hint


def test_compose_ready(monkeypatch, tmp_path):
    (tmp_path / "node_modules").mkdir()
    monkeypatch.setattr(registry.shutil, "which", lambda name: "/usr/bin/node")
    monkeypatch.setattr(registry, "REMOTION_DIR", tmp_path)
    cap = _by_name(registry.probe_compose(), "Remotion")
    assert cap.state == State.AVAILABLE


def test_voiceover_missing_package(monkeypatch):
    monkeypatch.setattr(registry.importlib.util, "find_spec", lambda name: None)
    cap = _by_name(registry.probe_voiceover(), "edge-tts")
    assert cap.state == State.MISSING


def test_voiceover_available(monkeypatch):
    monkeypatch.setattr(registry.importlib.util, "find_spec", lambda name: object())
    cap = _by_name(registry.probe_voiceover(), "edge-tts")
    assert cap.state == State.AVAILABLE
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_registry.py -v`
Expected: FAIL — `AttributeError: module 'pipeline.registry' has no attribute '_has_subtitles_filter'`

- [ ] **Step 3: Write the minimal implementation**

Add these imports to the top of `pipeline/registry.py`, alongside the existing ones:

```python
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
```

Then append to `pipeline/registry.py`:

```python
REMOTION_DIR = Path(__file__).resolve().parent.parent / "remotion"


def _ffmpeg_hint() -> str:
    """Platform-correct remediation, matching the Makefile `ffmpeg` target."""
    if sys.platform == "darwin":
        return ("brew install ffmpeg-full && brew link --overwrite ffmpeg-full "
                "(plain Homebrew ffmpeg has no libass)")
    return "sudo apt-get install -y ffmpeg"


def _has_subtitles_filter(filters_output: str) -> bool:
    """True when `ffmpeg -filters` lists a filter *named* `subtitles`.

    Match the name column, not the whole line: several filter descriptions
    contain the word "subtitles", so a substring search reports libass as
    present on builds that lack it.
    """
    for line in filters_output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "subtitles":
            return True
    return False


def _ffmpeg_filters(ffmpeg: str) -> str:
    """Raw `ffmpeg -filters` output, or "" if it cannot be run."""
    try:
        result = subprocess.run([ffmpeg, "-hide_banner", "-filters"],
                                capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout


def probe_voiceover() -> list[Capability]:
    """edge-tts is free and needs no key — only the package and a network."""
    if importlib.util.find_spec("edge_tts") is None:
        return [Capability("voiceover", "edge-tts", State.MISSING,
                           "package not installed", hint="uv sync")]
    return [Capability("voiceover", "edge-tts", State.AVAILABLE,
                       "free, needs network")]


def probe_compose() -> list[Capability]:
    """Remotion renders the $0 text/motion cards. Needs Node and an install."""
    if shutil.which("node") is None:
        return [Capability("compose", "Remotion", State.MISSING,
                           "node not on PATH", hint="install Node 18+")]
    if not (REMOTION_DIR / "node_modules").is_dir():
        return [Capability("compose", "Remotion", State.MISSING,
                           "node_modules missing",
                           hint=f"npm install --prefix {REMOTION_DIR}")]
    return [Capability("compose", "Remotion", State.AVAILABLE, "ready")]


def probe_assemble() -> list[Capability]:
    """ffmpeg, ffprobe, and — the one assemble.py forgets — libass."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return [Capability("assemble", "ffmpeg", State.MISSING,
                           "not on PATH", hint=_ffmpeg_hint())]

    caps = [Capability("assemble", "ffmpeg", State.AVAILABLE, ffmpeg)]

    if shutil.which("ffprobe") is None:
        caps.append(Capability("assemble", "ffprobe", State.MISSING,
                               "not on PATH — scene durations are measured "
                               "with it", hint=_ffmpeg_hint()))
    else:
        caps.append(Capability("assemble", "ffprobe", State.AVAILABLE, "ok"))

    if _has_subtitles_filter(_ffmpeg_filters(ffmpeg)):
        caps.append(Capability("assemble", "libass", State.AVAILABLE,
                               "captions supported"))
    else:
        caps.append(Capability("assemble", "libass", State.MISSING,
                               "captions WILL fail at the final assemble step",
                               hint=_ffmpeg_hint()))
    return caps
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_registry.py -v`
Expected: PASS — 16 passed

- [ ] **Step 5: Commit**

```bash
git add pipeline/registry.py tests/test_registry.py
git commit -m "feat(registry): voiceover, compose and assemble probes

Detects a libass-less ffmpeg up front. assemble.py checks that ffmpeg exists
but not that it can render subtitles, so that build fails only at the final
step — after every image and voiceover is already generated and paid for."
```

---

## Task 3: Preflight CLI

**Files:**
- Modify: `pipeline/registry.py` (append)
- Modify: `tests/test_registry.py` (append)
- Modify: `Makefile` (add `preflight` target)

**Interfaces:**
- Consumes: all six `probe_*` functions from Tasks 1 and 2
- Produces:
  - `preflight() -> list[Capability]` — every group, in stage order
  - `render_table(caps: list[Capability]) -> str`
  - `main() -> None` — accepts `--json`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_registry.py`:

```python
# --- CLI ---

import json


def _stub_all_probes(monkeypatch):
    """Pin every probe so table/JSON assertions don't depend on the machine."""
    monkeypatch.setattr(registry, "probe_llm", lambda: [
        Capability("llm", "gpt-4o-mini", State.AVAILABLE, "configured")])
    monkeypatch.setattr(registry, "probe_images", lambda: [
        Capability("images", "qwen-image", State.AVAILABLE, "configured"),
        Capability("images", "gpt-image-1", State.PAID, "paid — never auto-picked",
                   hint="use --backend gpt-image-1 to opt in explicitly")])
    monkeypatch.setattr(registry, "probe_video", lambda: [
        Capability("video", "wan-i2v", State.DISABLED, "DISABLED by policy (money rule)")])
    monkeypatch.setattr(registry, "probe_voiceover", lambda: [
        Capability("voiceover", "edge-tts", State.AVAILABLE, "free, needs network")])
    monkeypatch.setattr(registry, "probe_compose", lambda: [
        Capability("compose", "Remotion", State.AVAILABLE, "ready")])
    monkeypatch.setattr(registry, "probe_assemble", lambda: [
        Capability("assemble", "libass", State.MISSING, "captions WILL fail",
                   hint="brew install ffmpeg-full")])


def test_preflight_covers_every_group(monkeypatch):
    _stub_all_probes(monkeypatch)
    groups = {c.group for c in registry.preflight()}
    assert groups == {"llm", "images", "video", "voiceover", "compose", "assemble"}


def test_render_table_marks_each_state(monkeypatch):
    _stub_all_probes(monkeypatch)
    table = registry.render_table(registry.preflight())
    assert "✓ qwen-image" in table
    assert "$ gpt-image-1" in table
    assert "⊘ wan-i2v" in table
    assert "✗ libass" in table


def test_render_table_shows_hints_for_problems(monkeypatch):
    _stub_all_probes(monkeypatch)
    table = registry.render_table(registry.preflight())
    assert "brew install ffmpeg-full" in table


def test_json_output_is_parseable(monkeypatch, capsys):
    _stub_all_probes(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["registry", "--json"])
    registry.main()
    payload = json.loads(capsys.readouterr().out)
    assert {"group", "name", "state", "detail", "hint"} <= set(payload[0])


def test_main_exits_zero_despite_missing_capabilities(monkeypatch, capsys):
    # The registry reports; it does not gate. The agent decides whether a
    # missing capability blocks the run it was actually asked to do.
    _stub_all_probes(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["registry"])
    registry.main()          # must not raise SystemExit
    assert "libass" in capsys.readouterr().out
```

Add `import sys` to the top of `tests/test_registry.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_registry.py -v`
Expected: FAIL — `AttributeError: module 'pipeline.registry' has no attribute 'preflight'`

- [ ] **Step 3: Write the minimal implementation**

Add to the imports at the top of `pipeline/registry.py`:

```python
import argparse
import json
from dataclasses import asdict

from .env import load_env
```

Append to `pipeline/registry.py`:

```python
SYMBOLS = {
    State.AVAILABLE: "✓",
    State.MISSING: "✗",
    State.PAID: "$",
    State.DISABLED: "⊘",
}

# Display order = pipeline stage order, so the table reads like a run.
GROUP_LABELS = [
    ("llm", "LLM (plan)"),
    ("images", "Images"),
    ("video", "Video"),
    ("voiceover", "Voiceover"),
    ("compose", "Compose"),
    ("assemble", "Assemble"),
]


def preflight() -> list[Capability]:
    """Every capability, in stage order."""
    return [
        *probe_llm(),
        *probe_images(),
        *probe_video(),
        *probe_voiceover(),
        *probe_compose(),
        *probe_assemble(),
    ]


def render_table(caps: list[Capability]) -> str:
    """Human-readable preflight table. The group label prints once per group."""
    lines: list[str] = []
    for group, label in GROUP_LABELS:
        rows = [c for c in caps if c.group == group]
        for i, cap in enumerate(rows):
            head = label if i == 0 else ""
            mark = SYMBOLS.get(cap.state, "?")
            lines.append(f"{head:<15} {mark} {cap.name:<18} {cap.detail}".rstrip())
            if cap.hint and cap.state in (State.MISSING, State.PAID):
                lines.append(f"{'':<15}   {'':<18} -> {cap.hint}")
    lines.append("")
    lines.append("Legend: ✓ available · ✗ unavailable · "
                 "$ paid, explicit opt-in only · ⊘ disabled by policy")
    lines.append("API-backed entries are 'configured', not verified — a revoked "
                 "key still reads as configured.")
    return "\n".join(lines)


def main() -> None:
    # Keys live in .env, not the shell environment — every stage CLI loads it
    # first (refine.py, voiceover.py, images/__main__.py). Without this,
    # preflight reports a correctly configured machine as broken.
    load_env()

    parser = argparse.ArgumentParser(
        description="Preflight: what works on this machine right now")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output")
    args = parser.parse_args()

    caps = preflight()
    if args.json:
        print(json.dumps([asdict(c) for c in caps], indent=2))
    else:
        print(render_table(caps))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_registry.py -v`
Expected: PASS — 21 passed

- [ ] **Step 5: Run the real thing and read the output**

Run: `uv run python -m pipeline.registry`
Expected: a table covering all six groups, reflecting this machine's actual state. Confirm the `⊘` video row appears and that no row claims `gpt-image-1` is available.

Run: `uv run python -m pipeline.registry --json | head -20`
Expected: valid JSON array.

- [ ] **Step 6: Add the Makefile target**

In `Makefile`, add a target using `$(VENV)` as its prerequisite, matching the
existing style at `migrate: $(VENV)` (`Makefile:44`):

```make
preflight: $(VENV)
	$(PY) -m pipeline.registry
```

`.PHONY` (`Makefile:6`) already lists `preflight`, so leave that line alone.

- [ ] **Step 7: Verify the target**

Run: `make preflight`
Expected: the same table as Step 5.

- [ ] **Step 8: Commit**

```bash
git add pipeline/registry.py tests/test_registry.py Makefile
git commit -m "feat(registry): preflight CLI with table and --json output

python -m pipeline.registry / make preflight. Always exits 0: the registry
reports, the caller decides whether a gap blocks the requested run."
```

---

## Task 4: AGENT_GUIDE.md, CLAUDE.md routing, .env.example

**Files:**
- Create: `AGENT_GUIDE.md`
- Modify: `CLAUDE.md`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `python -m pipeline.registry` from Task 3
- Produces: the contract that Task 5's director skills are referenced from

- [ ] **Step 1: Write `AGENT_GUIDE.md`**

Create `AGENT_GUIDE.md` at the repo root:

```markdown
# Agent Guide — Producing a Video

Read this before making, creating, or producing any video. It is a contract,
not documentation. For working *on* the codebase, see `CLAUDE.md`.

## Rule Zero — every video goes through the four stages

    python -m pipeline.refine "idea"     # stage 1 — shot plan
    python -m pipeline.images            # stage 2 — one image per scene
    python -m pipeline.voiceover         # stage 3 — narration + word timings
    python -m pipeline.assemble          # stage 4 — final.mp4

Do NOT write ad-hoc scripts that import pipeline internals, call provider APIs
directly, or skip a stage. The stages encode ordering, fallback, and money
rules that improvised code silently loses.

Each stage defaults to the most recently touched `output/*/` folder. Pass a
folder to target an older video.

## Mandatory preflight

Before any creative work:

    python -m pipeline.registry

This reports what actually works on this machine. Never start a run without
it — a missing libass means the final assemble step fails *after* every image
and voiceover has been generated and paid for.

Preflight reports **configuration, not liveness**. An entry marked
"configured" means the key is present, not that it works. Say so when you
report it, so a first-call auth failure is not a surprise.

## Announce before you spend

Before the first generation call, state:

- the stage and the command you will run,
- the backend and model,
- whether it is free or paid, and the estimated cost,
- whether it is one sample scene or the full run.

Wait for approval on anything paid. Free defaults (qwen-image, edge-tts,
gpt-4o-mini plans at ~$0.001) still get announced, but do not need approval.

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
- Do not add a paid backend to a run that was planned as free.

## When something breaks

Report in this shape, then **stop**:

1. What was attempted (the exact command).
2. What failed (the actual error, not a paraphrase).
3. Whether it is auth, provider access, a tool bug, or prompt/design quality.
4. What options exist.
5. Which one you recommend, and why.

Do not swap backends, retry against a paid provider, or write a workaround
script without approval. Progress is preserved in `state.json`; resume with
the same stage command.

## Stage map

| Stage | Command | Reads | Writes | Read first |
|---|---|---|---|---|
| 1 plan | `pipeline.refine` | the idea | `shot_plan.json` | `plan-director` skill |
| 2 images | `pipeline.images` | `shot_plan.json` | `images/scene_NN.png` | `images-director` skill |
| 3 voice | `pipeline.voiceover` | `shot_plan.json` | `audio/scene_NN.mp3` + `.words.json` | `voiceover-director` skill |
| 4 assemble | `pipeline.assemble` | all of the above | `final.mp4` | `assemble-director` skill |

Read the stage's director skill **before** running that stage. The directors
carry the failure modes that are invisible until the video is finished.
```

- [ ] **Step 2: Add the routing line to `CLAUDE.md`**

Insert immediately after the opening description paragraph in `CLAUDE.md`, before `## Commands`:

```markdown
> **Producing a video?** If the user asks you to make, create, or produce a
> video, read [`AGENT_GUIDE.md`](AGENT_GUIDE.md) before acting. This file
> covers working *on* the codebase; that one covers *running* it.
```

- [ ] **Step 3: Replace the Money-rules body with a pointer**

`CLAUDE.md` currently restates the money rules at line 31. Two copies drift.
Replace the body of that section (keep the heading) with:

```markdown
## Money rules

Full rules and the announce/approve protocol: [`AGENT_GUIDE.md`](AGENT_GUIDE.md).
Enforced in code, not just documented:

- `pipeline/video/__main__.py` is commented out — animation cannot run.
- `AUTO_EXCLUDE` in `pipeline/images/__init__.py` keeps paid `gpt-image-1` out
  of auto-pick and out of the fallback chain.

Both are load-bearing. Do not "clean them up".
```

Leave `## Hard-won gotchas` untouched — those apply when editing pipeline code,
not only when producing a video.

- [ ] **Step 4: Fix the stale test claim in `CLAUDE.md`**

Find:

```
No real test suite — just `tests/test_expand.py` (plain asserts for the
character-substitution logic, run `python -m tests.test_expand`).
```

Replace with:

```
Tests live in `tests/` (pytest) and `backend/apps/*/tests/` (Django). `make test`
runs the Django app tests plus `tests/test_pipeline_isolation.py`,
`tests/test_registry.py`, and `tests/test_expand.py` — a subset, not everything.
`uv run python -m pytest tests/` runs more of `tests/`, though
`tests/test_voiceover_helpers.py` is a Django `TestCase` that needs
`DJANGO_SETTINGS_MODULE` and currently runs under neither command. Verify pipeline
changes by running stages against a copy of `examples/the-sharing-berry/` with
`--backend placeholder` (free, no keys needed).
```

> Do not write "run everything with `make test`" — `make test` runs 2 of the 6
> pytest files in `tests/`. Verified: `uv run python -m pytest tests/` gives
> 42 passed / 7 errors, because `tests/test_voiceover_helpers.py` is a Django
> `TestCase` that pytest cannot configure and `manage.py test apps` does not
> discover. Widening `make test` is deliberately out of scope for this branch.

- [ ] **Step 5: Add the missing vars to `.env.example`**

Append to `.env.example` (values empty — this file is committed, real keys go in `.env`):

```bash
# --- Additional pipeline providers (all optional) ---
PEXELS_API_KEY=""          # stock-photo image backend
REPLICATE_API_TOKEN=""     # flux-schnell image backend (free tier, then paid)
ANTHROPIC_API_KEY=""       # with LLM_PROVIDER=anthropic
GOOGLE_API_KEY=""          # with LLM_PROVIDER=gemini
# VIDEO_STYLE=""           # style preset name, see pipeline/styles.py PRESETS
# DASHSCOPE_BASE_URL=""    # legacy alias for DASHSCOPE_API_URL
# CELERY_BROKER_URL=""     # redis for the web app AND pipeline.images concurrency limiting; defaults to redis://localhost:6379/0
```

- [ ] **Step 6: Verify preflight and the guide agree**

Run: `uv run python -m pipeline.registry`
Check that every env var the table names as missing exists in `.env.example`.
If preflight names one that is absent, add it in the same style.

- [ ] **Step 7: Commit**

```bash
git add AGENT_GUIDE.md CLAUDE.md .env.example
git commit -m "docs: add AGENT_GUIDE.md production contract

Promotes the money rules and review gates from prose in CLAUDE.md into a
contract the agent reads before producing a video. CLAUDE.md keeps the
code-level gotchas and now points at the guide for run-time rules, so there
is one source of truth. Also documents 7 env vars the code reads."
```

---

## Task 5: Stage-director skills

**Files:**
- Create: `.claude/skills/plan-director/SKILL.md`
- Create: `.claude/skills/images-director/SKILL.md`
- Create: `.claude/skills/voiceover-director/SKILL.md`
- Create: `.claude/skills/assemble-director/SKILL.md`

**Interfaces:**
- Consumes: `AGENT_GUIDE.md` from Task 4; the 5 existing skills (`shot-plan`, `image-backends`, `voiceover-tts`, `ffmpeg-assembly`, `remotion-compose`)
- Produces: nothing consumed by later tasks

Directors describe *running a stage*. The existing 5 skills describe *how a component works*. Directors link down; they never restate mechanics.

- [ ] **Step 1: Create `plan-director`**

```markdown
---
name: plan-director
description: Running stage 1 of a video production — turning an idea into shot_plan.json and holding the plan review gate. Use when producing a video and about to run pipeline.refine, when revising a plan, or when deciding whether a plan is good enough to generate images from. Triggers include make a video, produce a video, stage 1, refine, shot plan review, plan gate, revise plan, --change.
---

# Stage 1 — Plan

**Command:** `python -m pipeline.refine "idea"` (auto-polish and consistency
review run automatically — never add a manual polish call)
**Produces:** `output/<name>/shot_plan.json`
**Gate:** YES — show the plan and wait.

For the plan's structure, fields, and how to author them, read the
`shot-plan` skill. This file covers running the stage.

## Before running

Preflight must show an available LLM row. Announce the model and cost
(gpt-4o-mini plans are ~$0.001) before running.

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

Revise with `python -m pipeline.refine --change "..."`. Do not hand-edit
`shot_plan.json`: editing skips auto-polish and consistency review.

Advance to stage 2 only after explicit approval.
```

- [ ] **Step 2: Create `images-director`**

```markdown
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
scenes that were fine.

If Qwen keeps refusing an instruction (strong model priors), regenerate that
one scene with `--backend gpt-image-1`, which follows instructions much
better. That is a paid call: announce and get approval first.

## The gate

Show the images. Wait for approval before voiceover.
```

- [ ] **Step 3: Create `voiceover-director`**

```markdown
---
name: voiceover-director
description: Running stage 3 of a video production — generating narration audio and the word timings captions depend on. Use when producing a video and about to run pipeline.voiceover, when audio is missing for a scene, or when captions are mistimed. Triggers include stage 3, voiceover, narration, TTS, edge-tts, words.json, NoAudioReceived, caption timing, voice.
---

# Stage 3 — Voiceover

**Command:** `python -m pipeline.voiceover`
**Produces:** `audio/scene_NN.mp3` and `audio/scene_NN.words.json`
**Gate:** none — runs after image approval.

For voices, per-scene dialogue voices, and provider details, read the
`voiceover-tts` skill. This file covers running the stage.

## Before running

edge-tts is free and needs no key, but it **does** need a network. If
preflight showed it missing, fix that before starting — there is no fallback.

Default voice is `en-US-AndrewNeural`; override with `--voice` or
`NARRATOR_VOICE`.

## What "good" looks like

- **Every scene has both files.** A missing `.words.json` means captions for
  that scene will be absent or mistimed — the word timings come from
  `boundary="WordBoundary"` and nothing else regenerates them.
- **Scene durations come from these mp3s**, measured in `assemble.py`. They
  are never taken from the plan, so a too-long narration silently stretches
  that scene. Check for outliers before assembling.

## When it fails

`NoAudioReceived` is usually a transient network or a text edge case, not a
bug. Re-run the stage — existing files are skipped, so only the missing
scenes are retried. If one scene fails repeatedly, report it rather than
switching TTS providers.
```

- [ ] **Step 4: Create `assemble-director`**

```markdown
---
name: assemble-director
description: Running stage 4 of a video production — rendering the final mp4 from images, audio, captions and music. Use when producing a video and about to run pipeline.assemble, or when the final render fails or looks wrong. Triggers include stage 4, assemble, final.mp4, render, captions, subtitles, music, ffmpeg failed, libass.
---

# Stage 4 — Assemble

**Command:** `python -m pipeline.assemble [--music FILE]`
**Produces:** `output/<name>/final.mp4`
**Gate:** none — this is the deliverable.

For the ffmpeg filter graph, Ken Burns motion, drawtext, and music mixing,
read the `ffmpeg-assembly` skill. For title and quote cards, read
`remotion-compose`. This file covers running the stage.

## Before running

**Check that preflight reported libass available.** `assemble.py` verifies
that ffmpeg exists but not that it can render subtitles, so a plain Homebrew
ffmpeg on macOS fails at the very last step — after every image and voiceover
has already been generated and paid for.

If libass is missing: `brew install ffmpeg-full && brew link --overwrite
ffmpeg-full`. Do not work around it by disabling captions without asking.

Confirm every scene has an mp3 first. Scene durations are measured from
those files; a missing one changes the whole timeline.

## What "good" looks like

- Captions appear and track the narration.
- No scene sits visibly too long or too short against its narration.
- Music, if used, sits under the voice rather than competing with it.
- CC-BY tracks in `music/` require attribution — see
  `music/ATTRIBUTION.txt`.

## When it fails

ffmpeg errors are long; the useful part is the last few lines. Report the
actual error. Common causes, in order: missing libass, a scene missing its
mp3, and unescaped characters in drawtext text.
```

- [ ] **Step 5: Verify the skills load**

Run: `ls .claude/skills/`
Expected: the 4 new director directories alongside the 5 existing skills.

Check each frontmatter block parses — `name` and `description` on single
lines, opening and closing `---`, no tabs.

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/plan-director .claude/skills/images-director \
        .claude/skills/voiceover-director .claude/skills/assemble-director
git commit -m "feat(skills): add four stage-director skills

One per pipeline stage: what it produces, its review gate, what good looks
like, and the failure modes that stay invisible until the video is finished.
Directors link down into the existing component skills rather than restating
them."
```

---

## Task 6: End-to-end and behavioral verification

**Files:**
- No production files. This task verifies Tasks 1–5 and fixes what it finds.

**Interfaces:**
- Consumes: everything above
- Produces: a verified working phase 1

- [ ] **Step 1: Run the full test suite**

Run: `make test`
Expected: PASS — Django app tests, `test_pipeline_isolation.py`, `test_registry.py`, and `test_expand`.

- [ ] **Step 2: Run preflight on this machine and read every row**

Run: `make preflight`

Verify by inspection:
- the video row shows `⊘ ... DISABLED by policy`, even though `.env` has a `DASHSCOPE_API_KEY`
- `gpt-image-1` shows `$`, never `✓`
- every `✗` row carries an actionable hint
- the libass row matches reality (cross-check with `ffmpeg -filters | grep ' subtitles'`)

- [ ] **Step 3: Run the free end-to-end example**

Run: `make example`

This copies `examples/the-sharing-berry/` and runs stages 2–4 with
`--backend placeholder`. Free, no keys.
Expected: `output/the-sharing-berry/final.mp4` exists and plays.

If it fails, the failure is pre-existing and unrelated to this plan — record
it and continue; do not fix pipeline bugs inside this task.

Clean up: `make clean-example`

- [ ] **Step 4: Behavioral check — the part tests cannot cover**

Open a **fresh** Claude Code session in this repo (fresh matters: an existing
session has already read files and will not exercise the routing).

Say: `make me a short video about why the sky is blue`

Verify all four:

1. It read `AGENT_GUIDE.md` before acting (the `CLAUDE.md` routing line worked).
2. It ran `python -m pipeline.registry` before any generation.
3. It announced backend, model, and cost, and waited.
4. It stopped at Gate 1 and showed the plan.

- [ ] **Step 5: Fix whatever step 4 revealed**

A failure here is a **guide bug**, not an agent bug. The usual fixes:

- Routing missed → make the `CLAUDE.md` pointer more prominent or more imperative.
- Preflight skipped → move "Mandatory preflight" above "Rule Zero" in `AGENT_GUIDE.md`.
- Gate skipped → state the gate in the stage map row as well as in its own section.

Edit, then re-run step 4 in another fresh session. Expect two or three
iterations; this loop is manual and normal.

- [ ] **Step 6: Commit any guide fixes**

```bash
git add AGENT_GUIDE.md CLAUDE.md .claude/skills
git commit -m "docs: tighten agent guide after behavioral testing"
```

- [ ] **Step 7: Confirm the web app is untouched**

Run: `git diff main --stat -- backend/ webapp/ pipeline/schema.py pipeline/run.py`
Expected: **empty**. Any output here violates a global constraint and must be reverted.

- [ ] **Step 8: Open the PR**

```bash
git push -u origin feat/agentic-pipeline-interface
gh pr create --title "Phase 1: agentic pipeline interface" \
  --body "Implements docs/superpowers/specs/2026-08-12-agentic-pipeline-interface-design.md

Adds preflight (\`make preflight\`), an AGENT_GUIDE.md production contract, and
four stage-director skills, so the pipeline can be driven from Claude Code with
review gates at plan and images.

Reuses the existing stage CLIs — no new caller alongside the CLI and Celery
paths. The web app and pipeline core are unchanged.

MCP is deferred; rationale is recorded in the spec.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

## Success criteria

Verified in Task 6:

1. `python -m pipeline.registry` correctly reports all six capability groups, including a missing-libass machine. *(Step 2)*
2. A fresh Claude Code session given "make me a video about X" runs preflight, announces cost, and stops at Gate 1. *(Step 4)*
3. No unapproved paid call occurs. *(Step 4)*
4. `tests/test_registry.py` passes and the existing tests still pass. *(Step 1)*
5. The web app and Celery path are unaffected. *(Step 7)*
