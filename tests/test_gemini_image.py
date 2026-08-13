"""The Gemini ("nano banana") image backend.

Paid with no free tier and the most expensive backend in PROVIDERS, so the
money-rule tests here matter more than the call-shape ones: it must never be
reachable except by an explicit --backend.
"""
import base64
import sys
import types

import pytest

import pipeline.images as images
from pipeline.images import gemini_image


def _gemini():
    return next(p for p in images.PROVIDERS if p.name == "gemini-image")


# --- money rule ------------------------------------------------------------

def test_gemini_is_marked_paid_and_excluded_from_autopick():
    assert _gemini().paid is True
    assert "gemini-image" in images.AUTO_EXCLUDE


def test_autopick_never_returns_gemini(monkeypatch):
    for p in images.PROVIDERS:
        monkeypatch.setattr(p, "available", (lambda: True) if p.name == "gemini-image"
                            else (lambda: False))
    with pytest.raises(RuntimeError):
        images.get_provider(None)


def test_image_backend_env_cannot_select_gemini():
    """Same guard as gpt-image-1: .env alone must not authorise a paid backend."""
    with pytest.raises(RuntimeError, match="IMAGE_BACKEND"):
        images.resolve_backend_arg(None, "nano-banana")


def test_cost_line_states_a_real_figure_and_no_free_tier():
    cost = _gemini().cost
    assert "PAID" in cost
    assert "no free tier" in cost
    assert "0.10" in cost, "the per-image figure must be stated, not implied"


# --- availability ----------------------------------------------------------

def test_unavailable_without_the_sdk(monkeypatch):
    """The key alone is not enough — google-genai is an optional dependency.
    Setting the sys.modules entry to None makes the import raise, which is what
    a machine without the package does."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "google.genai", None)
    assert _gemini().available() is False


def test_available_with_both_the_key_and_the_sdk(monkeypatch):
    """Positive control for the test above: without it, 'unavailable' passes
    for any reason at all, including a typo in the provider's env_required."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.genai", types.ModuleType("google.genai"))
    assert _gemini().available() is True


def test_unavailable_without_the_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert _gemini().available() is False


def test_aliases_resolve():
    for alias in ("gemini", "nano-banana", "nanobanana"):
        assert images.ALIASES[alias] == "gemini-image"


# --- call shape ------------------------------------------------------------

class _Recorder:
    """Stands in for google.genai, capturing what the provider sends."""

    def __init__(self):
        self.calls = []

    def Client(self, api_key=None):  # noqa: N802 — mirrors the SDK's name
        self.api_key = api_key
        return self

    @property
    def interactions(self):
        return self

    def create(self, model=None, input=None, image_config=None):
        self.calls.append({"model": model, "input": input, "image_config": image_config})
        png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)  # not a real PNG; see _fake_open
        return types.SimpleNamespace(
            output_image=types.SimpleNamespace(data=base64.b64encode(png).decode()))


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(gemini_image, "_client", lambda api_key=None: rec)
    # to_png_bytes needs a real image; skip decoding the fake payload.
    monkeypatch.setattr(gemini_image, "to_png_bytes", lambda img: b"png")
    monkeypatch.setattr(gemini_image.Image, "open", lambda *_: types.SimpleNamespace(
        convert=lambda mode: None))
    return rec


def test_generate_sends_text_and_the_configured_size(recorder):
    _gemini().generate("a dog on a bridge")
    call = recorder.calls[0]
    assert call["input"] == [{"type": "text", "text": "a dog on a bridge"}]
    assert call["image_config"]["aspect_ratio"] == "16:9"
    assert call["image_config"]["image_size"] == "2K"
    assert call["model"] == "gemini-3.1-flash-image"


def test_negative_becomes_an_exclusion_instruction(recorder):
    """Image models draw negated nouns, so the negative is phrased as an
    instruction rather than pasted in as bare words (CLAUDE.md gotchas)."""
    _gemini().generate("a dog", negative="bone, drumstick")
    text = recorder.calls[0]["input"][0]["text"]
    assert text == "a dog. Do not include: bone, drumstick."


def test_model_override_is_honoured(recorder, monkeypatch):
    monkeypatch.setenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-lite-image")
    _gemini().generate("a dog")
    assert recorder.calls[0]["model"] == "gemini-3.1-flash-lite-image"


def test_edit_sends_the_text_then_every_reference(recorder, tmp_path):
    """Multi-reference editing is the whole reason to add this backend --
    character_refs() feeds portraits in to keep a face consistent."""
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"AAA")
    b.write_bytes(b"BBB")

    _gemini().edit("put them on a bridge", [a, b])
    parts = recorder.calls[0]["input"]
    assert parts[0] == {"type": "text", "text": "put them on a bridge"}
    assert [p["type"] for p in parts] == ["text", "image", "image"]
    assert base64.b64decode(parts[1]["data"]) == b"AAA"
    assert base64.b64decode(parts[2]["data"]) == b"BBB"
    assert all(p["mime_type"] == "image/png" for p in parts[1:])


def test_edit_accepts_a_single_reference(recorder, tmp_path):
    ref = tmp_path / "one.png"
    ref.write_bytes(b"ONE")
    _gemini().edit("scene", ref)
    parts = recorder.calls[0]["input"]
    assert [p["type"] for p in parts] == ["text", "image"]
