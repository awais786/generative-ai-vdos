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

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .env import load_env
from .images import AUTO_EXCLUDE, PROVIDERS as IMAGE_PROVIDERS
from .script_agent import default_model
from .video import PROVIDERS as VIDEO_PROVIDERS


class State:
    """Capability states. Plain strings so `--json` output stays readable."""
    AVAILABLE = "available"
    MISSING = "missing"
    PAID = "paid"            # usable, but only via an explicit opt-in flag
    METERED = "metered"      # auto-pickable, but costs money past a free tier
    DISABLED = "disabled"    # turned off by policy, regardless of config


# Env vars a backend needs *in addition to* its API key. `available()` checks
# only the key, so a backend can report configured and still fail on the first
# call — exactly the late failure this module exists to prevent. Each of these
# raises at generation time when unset (e.g. qwen_image._gen_model()).
EXTRA_REQUIRED_ENV = {
    "qwen-image": ("QWEN_IMAGE_MODEL",),
    "gpt-image-1": ("OPENAI_IMAGE_MODEL",),
    "flux-schnell": ("REPLICATE_IMAGE_MODEL",),
}

# Backends that are auto-pickable AND reachable through the per-scene fallback
# chain, but bill past a free tier. A run announced as free can quietly spend
# here, so they get their own state rather than a bare "configured".
METERED_BACKENDS = {"flux-schnell": "free tier, then ~$0.003/image"}

# Requirements that are not env vars and that this module deliberately does not
# probe (no network calls). Surfaced in `detail` so the agent can pass the
# caveat on rather than discovering it mid-run.
RUNTIME_CAVEATS = {
    "qwen-image": "also needs Redis reachable at CELERY_BROKER_URL "
                  "(default redis://localhost:6379/0) for concurrency limiting",
}


def _missing_extra_env(name: str) -> list[str]:
    """Env vars this backend needs beyond its key, that are currently unset."""
    return [v for v in EXTRA_REQUIRED_ENV.get(name, ()) if not os.environ.get(v, "").strip()]


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
    remediation message otherwise. Reuse it rather than restating them.

    `name` is stably "plan model" in both the missing and available rows —
    the resolved model id goes in `detail` — so `--json` consumers can key on
    `name` without branching on state."""
    try:
        model = default_model()
    except RuntimeError as exc:
        return [Capability("llm", "plan model", State.MISSING, str(exc),
                           hint="set LLM_PROVIDER and its API key in .env")]
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    return [Capability("llm", "plan model", State.AVAILABLE,
                       f"{model} (configured via LLM_PROVIDER={provider})")]


def probe_images() -> list[Capability]:
    """One row per image backend, in PROVIDERS order (= auto-pick priority).

    A backend counts as configured only when its key AND every extra env var
    it needs are set — `available()` checks the key alone, which is why a
    key-only setup used to report configured and then die on scene 1."""
    caps: list[Capability] = []
    for provider in IMAGE_PROVIDERS:
        name = provider.name
        need = provider.requires or "credentials"
        missing_extra = _missing_extra_env(name)
        caveat = RUNTIME_CAVEATS.get(name, "")

        if name in AUTO_EXCLUDE:
            if not provider.available():
                gap = f"{need} not set"
            elif missing_extra:
                gap = f"{', '.join(missing_extra)} not set"
            else:
                gap = ""
            detail = "paid — never auto-picked"
            if gap:
                detail += (f"; also not configured ({gap}, "
                           f"so --backend {name} would fail)")
                hint = f"set {gap.replace(' not set', '')} in .env before --backend {name}"
            else:
                hint = f"use --backend {name} to opt in explicitly"
            caps.append(Capability("images", name, State.PAID, detail, hint=hint))
            continue

        # The specific gap is checked FIRST. available() now folds the extra
        # vars into its own answer (qwen needs QWEN_IMAGE_MODEL as well as the
        # key), so testing availability first made this branch unreachable and
        # told a user with DASHSCOPE_API_KEY already set to go and set it.
        if missing_extra:
            joined = ", ".join(missing_extra)
            caps.append(Capability(
                "images", name, State.MISSING,
                f"{joined} not set — the API key is present, but generation would fail",
                hint=f"set {joined} in .env"))
            continue

        if not provider.available():
            caps.append(Capability("images", name, State.MISSING,
                                   f"{need} not set", hint=f"set {need} in .env"))
            continue

        state = State.METERED if name in METERED_BACKENDS else State.AVAILABLE
        detail = METERED_BACKENDS.get(name, "configured")
        if caveat:
            detail = f"{detail}; {caveat}"
        hint = ("auto-pickable and reachable via the fallback chain — a run "
                "announced as free can spend here") if state == State.METERED else ""
        caps.append(Capability("images", name, state, detail, hint=hint))
    return caps


def probe_video() -> list[Capability]:
    """Animation is disabled *for the CLI* — pipeline/video/__main__.py is
    commented out because a run spends limited DashScope credit.

    This is not a machine-wide guarantee. The web app calls Wan directly
    (backend/apps/projects/utils.py imports WanProvider and instantiates it in
    animate_scene), so on a deployment host a Celery worker can animate while
    this row says DISABLED. Report the key's presence too, since that is the
    fact an operator actually needs."""
    key_set = bool(os.environ.get("DASHSCOPE_API_KEY", "").strip())
    credit = ("DASHSCOPE_API_KEY is set — the web app's Celery worker can still "
              "animate" if key_set else "DASHSCOPE_API_KEY not set")
    return [Capability("video", provider.name, State.DISABLED,
                       f"DISABLED for the CLI by policy (money rule); {credit}",
                       hint="re-enabling the CLI stage spends DashScope credit "
                            "and requires explicit user approval")
            for provider in VIDEO_PROVIDERS]


REMOTION_DIR = Path(__file__).resolve().parent.parent / "remotion"


def _ffmpeg_hint() -> str:
    """Platform-correct remediation, matching the Makefile `ffmpeg` target."""
    if sys.platform == "darwin":
        return ("brew install ffmpeg-full && brew link --overwrite ffmpeg-full "
                "(plain Homebrew ffmpeg has no libass)")
    if sys.platform == "win32":
        # Windows fell through to the Linux branch and was told to run apt-get.
        # The gyan.org build ships libass, which the burned-in captions need.
        return "winget install Gyan.FFmpeg (that build includes libass)"
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
    """Remotion renders the $0 text/motion cards. `render_compositions`
    (`pipeline/compose/__init__.py`) invokes the CLI via `npx`, not `node`
    directly, so that's the binary that must be on PATH."""
    if shutil.which("npx") is None:
        return [Capability("compose", "Remotion", State.MISSING,
                           "npx not on PATH", hint="install Node 18+ (npx ships with it)")]
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


SYMBOLS = {
    State.AVAILABLE: "✓",
    State.MISSING: "✗",
    State.PAID: "$",
    State.METERED: "~",
    State.DISABLED: "⊘",
}

# States whose hint is remediation or a money warning the reader must see.
# DISABLED belongs here: its hint is the money-rule warning, and omitting it
# left the one such string in the table visible only in --json.
HINT_STATES = (State.MISSING, State.PAID, State.METERED, State.DISABLED)

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
    """Every capability, in stage order.

    Each probe is called under its own try/except: `probe_llm` catches only
    `RuntimeError` internally, and every current `available()` is
    exception-free, so nothing raises today — but preflight reports, it does
    not gate, and one future provider that raises must not turn the whole
    table into an unhandled traceback. A probe that blows up is reported as a
    single MISSING row carrying the exception text instead.

    The probe list is built fresh on every call (rather than cached at import
    time) so tests can `monkeypatch.setattr(registry, "probe_x", ...)` the way
    the existing suite already does — a module-level tuple built once at
    import time would capture the original function objects and ignore the
    monkeypatch. The group name is paired explicitly rather than derived from
    `probe.__name__`, so a monkeypatched replacement (whatever it's named)
    still reports under the right group on failure."""
    probes = (
        ("llm", probe_llm),
        ("images", probe_images),
        ("video", probe_video),
        ("voiceover", probe_voiceover),
        ("compose", probe_compose),
        ("assemble", probe_assemble),
    )
    caps: list[Capability] = []
    for group, probe in probes:
        try:
            caps.extend(probe())
        except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
            caps.append(Capability(group, group, State.MISSING,
                                   f"probe raised {exc.__class__.__name__}: {exc}"))
    return caps


def render_table(caps: list[Capability]) -> str:
    """Human-readable preflight table. The group label prints once per group.

    Every capability is rendered. Groups are shown in GROUP_LABELS order, then
    any group not in that list is appended under its raw name — a capability
    silently missing from the table would read as "not probed at all", which is
    the worst possible failure for a preflight tool."""
    known = [g for g, _ in GROUP_LABELS]
    extra = [g for g in dict.fromkeys(c.group for c in caps) if g not in known]
    ordered = GROUP_LABELS + [(g, g) for g in extra]

    lines: list[str] = []
    for group, label in ordered:
        rows = [c for c in caps if c.group == group]
        for i, cap in enumerate(rows):
            head = label if i == 0 else ""
            mark = SYMBOLS.get(cap.state, "?")
            lines.append(f"{head:<15} {mark} {cap.name:<18} {cap.detail}".rstrip())
            if cap.hint and cap.state in HINT_STATES:
                lines.append(f"{'':<15}   {'':<18} -> {cap.hint}")
    lines.append("")
    lines.append("Legend: ✓ available · ✗ unavailable · "
                 "$ paid, explicit opt-in only · ~ free tier then paid, "
                 "auto-pickable · ⊘ disabled by policy")
    lines.append("API-backed entries are 'configured', not verified — a revoked "
                 "key still reads as configured, and nothing here is probed over "
                 "the network.")
    return "\n".join(lines)


def main() -> None:
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
