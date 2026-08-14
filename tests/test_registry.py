"""Preflight regression tests.

The registry exists so a run fails in second one rather than at minute nine.
These tests pin the three behaviors that make it trustworthy: it never reports
the paid backend as auto-selectable, it never reports the animation stage as
runnable, and it detects a libass-less ffmpeg (which otherwise fails only at
the very last assemble step, after every asset is already paid for).
"""
import sys

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
    # `name` stays stably "plan model" whether the row is missing or available
    # (so --json consumers can key on it without branching on state); the
    # resolved model id lives in `detail` instead.
    monkeypatch.setattr(registry, "default_model", lambda: "gpt-4o-mini")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    cap = _by_name(registry.probe_llm(), "plan model")
    assert cap.state == State.AVAILABLE
    assert "gpt-4o-mini" in cap.detail
    assert "configured" in cap.detail


def test_images_paid_backend_never_available(monkeypatch):
    # Even with a working key, gpt-image-1 must read as PAID (explicit opt-in),
    # never AVAILABLE — otherwise an agent could treat it as a free default.
    import pipeline.images as images
    for p in images.PROVIDERS:
        monkeypatch.setattr(p, "available", lambda: True)
    cap = _by_name(registry.probe_images(), "gpt-image-1")
    assert cap.state == State.PAID


def test_images_paid_backend_unavailable_says_so(monkeypatch):
    # gpt-image-1 with no OPENAI_API_KEY is still PAID (never auto-picked),
    # but the detail must say the key is missing so an agent doesn't hand the
    # user a --backend command that's about to raise.
    import pipeline.images as images
    for p in images.PROVIDERS:
        monkeypatch.setattr(p, "available", lambda: False)
    cap = _by_name(registry.probe_images(), "gpt-image-1")
    assert cap.state == State.PAID
    assert "OPENAI_API_KEY" in cap.detail
    assert "not configured" in cap.detail


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


def test_compose_missing_npx(monkeypatch):
    # render_compositions() (pipeline/compose/__init__.py) invokes the CLI via
    # `npx`, not `node` directly — the probe must check the binary that's
    # actually required.
    monkeypatch.setattr(registry.shutil, "which", lambda name: None)
    cap = _by_name(registry.probe_compose(), "Remotion")
    assert cap.state == State.MISSING
    assert "npx" in cap.detail.lower()


def test_compose_missing_node_modules(monkeypatch, tmp_path):
    monkeypatch.setattr(registry.shutil, "which", lambda name: "/usr/bin/npx")
    monkeypatch.setattr(registry, "REMOTION_DIR", tmp_path)
    cap = _by_name(registry.probe_compose(), "Remotion")
    assert cap.state == State.MISSING
    assert "npm install" in cap.hint


def test_compose_ready(monkeypatch, tmp_path):
    (tmp_path / "node_modules").mkdir()
    monkeypatch.setattr(registry.shutil, "which", lambda name: "/usr/bin/npx")
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


def test_preflight_isolates_a_raising_probe(monkeypatch):
    # preflight() reports, it does not gate: one provider probe raising must
    # not crash the whole table. It should be reported as a single MISSING
    # row carrying the exception text, and every other group must still
    # appear.
    def boom():
        raise ValueError("boom: provider blew up")

    monkeypatch.setattr(registry, "probe_video", boom)
    caps = registry.preflight()

    groups = {c.group for c in caps}
    assert groups == {"llm", "images", "video", "voiceover", "compose", "assemble"}

    video_caps = [c for c in caps if c.group == "video"]
    assert len(video_caps) == 1
    assert video_caps[0].state == State.MISSING
    assert "boom: provider blew up" in video_caps[0].detail


def test_main_exits_zero_despite_a_raising_probe(monkeypatch, capsys):
    def boom():
        raise ValueError("boom: provider blew up")

    monkeypatch.setattr(registry, "probe_video", boom)
    monkeypatch.setattr(sys, "argv", ["registry"])
    registry.main()          # must not raise
    assert "boom: provider blew up" in capsys.readouterr().out


def test_main_loads_env_before_probing(monkeypatch, capsys):
    # Every other stage CLI loads .env at the top of main() so keys in .env
    # (the standard per CLAUDE.md) are available to probes. This regression
    # prevents a silent revert to the broken state where configured backends
    # incorrectly report as missing because .env was never loaded.
    load_env_called = []

    def load_env_recorder():
        load_env_called.append(True)

    monkeypatch.setattr(registry, "load_env", load_env_recorder)
    _stub_all_probes(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["registry"])
    registry.main()

    assert load_env_called, "main() must call load_env() before probing"


# --- configuration depth, metered backends, and table completeness ---
#
# `available()` checks only a backend's API key. Every one of these backends
# needs a model id too, and raises at generation time when it is unset — so a
# key-only setup used to print "configured" and then die on scene 1, which is
# the exact late failure this module exists to prevent.


def test_images_key_set_but_model_missing_reports_missing(monkeypatch):
    import pipeline.images as images
    for p in images.PROVIDERS:
        monkeypatch.setattr(p, "available", lambda: True)
    monkeypatch.delenv("QWEN_IMAGE_MODEL", raising=False)
    cap = _by_name(registry.probe_images(), "qwen-image")
    assert cap.state == State.MISSING
    assert "QWEN_IMAGE_MODEL" in cap.detail
    assert "QWEN_IMAGE_MODEL" in cap.hint


def test_images_fully_configured_backend_is_available(monkeypatch):
    import pipeline.images as images
    for p in images.PROVIDERS:
        monkeypatch.setattr(p, "available", lambda: True)
    # BOTH vars. probe_images checks the environment directly rather than
    # trusting available(), so setting only the model id left this passing
    # solely because the developer's .env supplied DASHSCOPE_API_KEY — it
    # failed the moment it ran on CI, where there is no .env.
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.setenv("QWEN_IMAGE_MODEL", "qwen-image-plus")
    cap = _by_name(registry.probe_images(), "qwen-image")
    assert cap.state == State.AVAILABLE
    # The Redis dependency is real but deliberately unprobed (no network), so
    # it has to be stated rather than silently assumed.
    assert "CELERY_BROKER_URL" in cap.detail


def test_flux_reports_metered_not_available(monkeypatch):
    # flux-schnell is NOT in AUTO_EXCLUDE, so it is auto-pickable and sits in
    # the per-scene fallback chain — but it bills past a free tier. Reporting
    # it as plain "available" lets a run announced as free spend money.
    import pipeline.images as images
    for p in images.PROVIDERS:
        monkeypatch.setattr(p, "available", lambda: True)
    # Both vars: probe_images now checks the environment directly rather than
    # trusting available(), so a monkeypatched available() alone no longer makes
    # a backend look configured.
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_test")
    monkeypatch.setenv("REPLICATE_IMAGE_MODEL", "black-forest-labs/flux-schnell")
    cap = _by_name(registry.probe_images(), "flux-schnell")
    assert cap.state == State.METERED
    assert cap.state != State.AVAILABLE
    assert "$" in cap.detail
    assert cap.hint, "a metered backend must carry a cost warning"


def test_paid_backend_missing_model_says_the_flag_would_fail(monkeypatch):
    import pipeline.images as images
    for p in images.PROVIDERS:
        monkeypatch.setattr(p, "available", lambda: True)
    monkeypatch.delenv("OPENAI_IMAGE_MODEL", raising=False)
    cap = _by_name(registry.probe_images(), "gpt-image-1")
    assert cap.state == State.PAID
    assert "OPENAI_IMAGE_MODEL" in cap.detail
    assert "would fail" in cap.detail


def test_video_row_reports_key_presence_for_operators(monkeypatch):
    # The CLI stage is disabled, but the web app instantiates WanProvider
    # directly (backend/apps/projects/utils.py), so DISABLED is not a
    # machine-wide guarantee. An operator needs to see the key state.
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-real-looking-key")
    cap = registry.probe_video()[0]
    assert cap.state == State.DISABLED
    assert "CLI" in cap.detail
    assert "DASHSCOPE_API_KEY is set" in cap.detail


def test_disabled_hints_are_rendered(monkeypatch):
    # The video row's hint is the money-rule warning. It used to be dropped
    # from the table and survive only in --json.
    caps = [Capability("video", "wan-i2v", State.DISABLED, "disabled",
                       hint="spends DashScope credit")]
    assert "spends DashScope credit" in registry.render_table(caps)


def test_render_table_shows_groups_missing_from_group_labels():
    # A capability absent from the table reads as "never probed", which is the
    # worst failure mode for a preflight tool.
    caps = [Capability("brand-new-group", "thing", State.MISSING, "nope",
                       hint="do something")]
    table = registry.render_table(caps)
    assert "thing" in table
    assert "brand-new-group" in table
