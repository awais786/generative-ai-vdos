"""Regression tests for image backend auto-pick — the documented "first
available backend" behavior, with gpt-image-1 kept out of auto-selection
(money rule)."""
import pytest

import pipeline.images as images


def test_get_provider_none_autopicks_first_available(monkeypatch):
    # Force every provider but placeholder unavailable so the assertion doesn't
    # depend on which API keys happen to be set in the ambient environment.
    for p in images.PROVIDERS:
        monkeypatch.setattr(p, "available", (lambda: True) if p.name == "placeholder"
                            else (lambda: False))
    assert images.get_provider(None).name == "placeholder"


def test_get_provider_none_never_autopicks_gpt_image(monkeypatch):
    # Even if gpt-image-1 were the only "available" backend, auto-pick must skip
    # it and raise rather than silently spend money.
    for p in images.PROVIDERS:
        monkeypatch.setattr(p, "available", (lambda: True) if p.name == "gpt-image-1"
                            else (lambda: False))
    with pytest.raises(RuntimeError):
        images.get_provider(None)


def test_explicit_gpt_image_still_selectable(monkeypatch):
    # The paid backend remains reachable when named explicitly.
    for p in images.PROVIDERS:
        if p.name == "gpt-image-1":
            monkeypatch.setattr(p, "available", lambda: True)
    assert images.get_provider("gpt-image-1").name == "gpt-image-1"
    assert images.get_provider("openai").name == "gpt-image-1"  # alias


# --- available() must agree with what generate() actually needs -------------

def _qwen():
    return next(p for p in images.PROVIDERS if p.name == "qwen-image")


def test_qwen_not_available_without_model_id(monkeypatch):
    """available() reported True on the API key alone, but generate() raises
    'no image model set' without QWEN_IMAGE_MODEL. Qwen is first in PROVIDERS,
    so auto-pick chose it and the run died at generation time -- after the plan
    was already paid for. Preflight checked both vars and disagreed."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.delenv("QWEN_IMAGE_MODEL", raising=False)
    assert _qwen().available() is False


def test_qwen_available_with_key_and_model(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.setenv("QWEN_IMAGE_MODEL", "qwen-image")
    assert _qwen().available() is True


# --- IMAGE_BACKEND must not reach a paid backend ---------------------------

def test_env_image_backend_cannot_select_paid_backend():
    """CLAUDE.md: gpt-image-1 "requires explicit --backend gpt-image-1". A
    forced backend bypasses AUTO_EXCLUDE, and --backend defaulted to
    IMAGE_BACKEND -- so IMAGE_BACKEND=openai in .env spent money on every bare
    `python -m pipeline.images` with nothing typed on the command line."""
    with pytest.raises(RuntimeError, match="IMAGE_BACKEND"):
        images.resolve_backend_arg(None, "openai")


def test_cli_backend_may_select_paid_backend():
    # The documented opt-in path stays open.
    assert images.resolve_backend_arg("gpt-image-1", None) == "gpt-image-1"
    assert images.resolve_backend_arg("openai", "qwen") == "openai"


def test_env_image_backend_still_selects_free_backends():
    assert images.resolve_backend_arg(None, "qwen") == "qwen"
    assert images.resolve_backend_arg(None, None) is None


# --- the cost banner must count every billed image -------------------------

def test_selection_report_counts_reference_portraits(monkeypatch):
    """The banner said "7 scenes" while the run generated 11 images -- the 4
    character reference portraits are billed too, so the stated cost was ~60%
    low."""
    # gpt-image-1's cost line names the configured model, so pin it: another
    # test clearing OPENAI_IMAGE_MODEL would otherwise change this one's output.
    monkeypatch.setenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
    primary = next(p for p in images.PROVIDERS if p.name == "gpt-image-1")
    line = images.selection_report(primary, forced=True, scenes=7, refs=4)[0]
    assert "11 images" in line


def test_selection_report_without_refs_is_unchanged():
    primary = next(p for p in images.PROVIDERS if p.name == "placeholder")
    line = images.selection_report(primary, forced=True, scenes=7, refs=0)[0]
    assert "7 scenes" in line
    assert "images" not in line.split("placeholder")[-1]
