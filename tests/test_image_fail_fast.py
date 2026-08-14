"""A run with no image backend must fail, not draw gradients.

PlaceholderProvider.available() is unconditionally True, so auto-pick returned
it whenever nothing else was configured — and the run completed as a full video
of gradient frames with no error, discovered on playback after the plan was
paid for and every downstream stage had run.

placeholder is now explicit-only, exactly as gpt-image-1 is, for the opposite
reason: AUTO_EXCLUDE means "too expensive to choose silently", explicit_only
means "too useless to choose silently".
"""
import pytest

import pipeline.images as images


def _only_placeholder(monkeypatch):
    """No real backend configured — the state a fresh clone is in."""
    for p in images.PROVIDERS:
        monkeypatch.setattr(p, "available", (lambda: True) if p.name == "placeholder"
                            else (lambda: False))


def test_autopick_refuses_to_return_placeholder(monkeypatch):
    _only_placeholder(monkeypatch)
    with pytest.raises(RuntimeError) as exc:
        images.get_provider(None)
    msg = str(exc.value)
    assert "no image backend" in msg.lower()


def test_the_failure_names_what_to_set(monkeypatch):
    """A bare 'not configured' costs a round trip. Name the vars and the tool
    that reports them."""
    _only_placeholder(monkeypatch)
    with pytest.raises(RuntimeError) as exc:
        images.get_provider(None)
    msg = str(exc.value)
    assert "DASHSCOPE_API_KEY" in msg and "QWEN_IMAGE_MODEL" in msg
    assert "OPENAI_API_KEY" in msg
    assert "pipeline.registry" in msg, "point at preflight"


def test_placeholder_is_still_selectable_explicitly(monkeypatch):
    """make example and free offline testing depend on this."""
    _only_placeholder(monkeypatch)
    assert images.get_provider("placeholder").name == "placeholder"


def test_placeholder_is_never_in_the_fallback_chain(monkeypatch):
    """A scene failing on a real provider must not quietly become a gradient in
    an otherwise real video — that looks like output, so nobody investigates."""
    assert "placeholder" in images.NEVER_AUTO


def test_placeholder_is_not_treated_as_paid():
    """AUTO_EXCLUDE drives the PAID row in preflight and the IMAGE_BACKEND
    money guard. placeholder belongs in neither."""
    assert "placeholder" not in images.AUTO_EXCLUDE
    assert images.resolve_backend_arg(None, "placeholder") == "placeholder"


def test_a_real_backend_is_still_auto_picked(monkeypatch):
    """Positive control: the change must not break normal auto-pick."""
    for p in images.PROVIDERS:
        monkeypatch.setattr(p, "available", (lambda: True) if p.name in ("qwen-image", "placeholder")
                            else (lambda: False))
    assert images.get_provider(None).name == "qwen-image"
