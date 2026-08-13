"""The contract every image backend declares, and the registry derived from it.

Adding a backend used to mean editing five places in images/__init__.py --
PROVIDERS, ALIASES, AUTO_EXCLUDE, PROVIDER_COST, plus a hand-written
available(). Two of the three defects found on 2026-08-13 came from exactly
that: available() drifted out of step with what generate() needed (qwen), and
AUTO_EXCLUDE sat outside the selection path (IMAGE_BACKEND could route around
it). These tests hold the facts in one place.
"""
import os

import pytest

import pipeline.images as images
from pipeline.images.base import ImageProvider


def test_every_provider_declares_the_contract():
    for p in images.PROVIDERS:
        assert p.name, f"{type(p).__name__} has no name"
        assert isinstance(p.env_required, tuple), f"{p.name}: env_required must be a tuple"
        assert isinstance(p.aliases, tuple), f"{p.name}: aliases must be a tuple"
        assert p.cost, f"{p.name}: cost must be stated, not left blank"


def test_availability_is_derived_from_env_required(monkeypatch):
    """The qwen bug: available() checked one var while generate() needed two.
    Deriving it from the same declaration makes that unrepresentable."""

    class Two(ImageProvider):
        name = "two-vars"
        env_required = ("ALPHA_KEY", "BETA_MODEL")
        cost = "free"

        def generate(self, prompt, **kw):
            return b""

    p = Two()
    monkeypatch.delenv("ALPHA_KEY", raising=False)
    monkeypatch.delenv("BETA_MODEL", raising=False)
    assert p.available() is False

    monkeypatch.setenv("ALPHA_KEY", "x")
    assert p.available() is False, "one of two is not enough"

    monkeypatch.setenv("BETA_MODEL", "m")
    assert p.available() is True

    monkeypatch.setenv("BETA_MODEL", "   ")
    assert p.available() is False, "whitespace is not a value"


def test_a_provider_needing_nothing_is_always_available():
    placeholder = next(p for p in images.PROVIDERS if p.name == "placeholder")
    assert placeholder.env_required == ()
    assert placeholder.available() is True


def test_requires_text_is_derived_not_restated():
    """Prose and logic must not be two hand-maintained copies of one fact."""
    qwen = next(p for p in images.PROVIDERS if p.name == "qwen-image")
    assert "DASHSCOPE_API_KEY" in qwen.requires
    assert "QWEN_IMAGE_MODEL" in qwen.requires

    flux = next(p for p in images.PROVIDERS if p.name == "flux-schnell")
    assert "REPLICATE_API_TOKEN" in flux.requires
    assert "replicate" in flux.requires, "the non-env need must survive"


# --- the registry is derived, not maintained in parallel -------------------

def test_aliases_are_derived_from_providers():
    for p in images.PROVIDERS:
        for alias in p.aliases:
            assert images.ALIASES[alias] == p.name


def test_auto_exclude_is_derived_from_paid():
    assert images.AUTO_EXCLUDE == {p.name for p in images.PROVIDERS if p.paid}
    assert "gpt-image-1" in images.AUTO_EXCLUDE


def test_cost_table_is_derived_from_providers():
    for p in images.PROVIDERS:
        assert images.PROVIDER_COST[p.name] == p.cost


def test_paid_providers_say_so_in_their_cost_line():
    for p in images.PROVIDERS:
        if p.paid:
            assert "PAID" in p.cost.upper(), (
                f"{p.name} is paid; its cost line must make that obvious in the banner")


def test_can_edit_matches_the_actual_method():
    """character_refs() used hasattr(provider, 'edit'). A provider that claims
    can_edit without the method silently degrades character consistency."""
    for p in images.PROVIDERS:
        assert p.can_edit == hasattr(p, "edit"), (
            f"{p.name}: can_edit={p.can_edit} but hasattr(edit)={hasattr(p, 'edit')}")


def test_the_free_backends_come_before_the_paid_one():
    names = [p.name for p in images.PROVIDERS]
    paid = [i for i, p in enumerate(images.PROVIDERS) if p.paid]
    assert paid, "gpt-image-1 must be marked paid"
    assert max(i for i, p in enumerate(images.PROVIDERS) if not p.paid) < min(paid), (
        f"a paid backend must sort last in PROVIDERS; got {names}")
