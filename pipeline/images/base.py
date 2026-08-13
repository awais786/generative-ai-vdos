"""Image provider interface.

To add a backend: create a module with an ImageProvider subclass and append an
instance to PROVIDERS in __init__.py. List order = auto-pick priority; that
list is the ONLY thing __init__.py maintains by hand. Everything else — the
aliases, the cost line, whether it is paid, whether it can edit from a
reference — is declared on the class below and derived from it.

That is deliberate. Facts about a backend used to live in four parallel
structures in __init__.py, and two of the three defects found on 2026-08-13
were the result: available() drifted out of step with what generate() actually
needed, and AUTO_EXCLUDE sat outside the path that selected a backend. One
declaration, many derived views.
"""
import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.secure import SecureString


class ImageProvider(ABC):
    #: Canonical backend id, as used by --backend and in reports.
    name: str = ""

    #: Friendly names accepted by --backend / IMAGE_BACKEND, e.g. ("qwen",).
    aliases: tuple[str, ...] = ()

    #: EVERY environment variable generate() needs. This drives available(),
    #: the preflight hint and the requires text — so a backend that grows a
    #: new requirement declares it once and all three follow.
    env_required: tuple[str, ...] = ()

    #: Non-environment prerequisites, e.g. "pip install replicate". Prose only;
    #: a provider needing this must also override available() to check it.
    extra_requires: str = ""

    #: Which env var carries the model id, when the backend has one.
    model_env: str | None = None

    #: What a run costs the user, in the run header. Copy the figure from the
    #: provider module's own docstring — never estimate one.
    cost: str = "cost unknown"

    #: True for a backend that bills per image. Paid backends are excluded from
    #: auto-pick and from the fallback chain, and can only be chosen by an
    #: explicit --backend on the command line (money rule; see CLAUDE.md).
    paid: bool = False

    #: True when the class implements edit(). Character reference portraits —
    #: the mechanism that keeps a face consistent across scenes — only work on
    #: a backend that can edit from a reference image.
    can_edit: bool = False

    @property
    def requires(self) -> str:
        """Human-readable prerequisites, derived from the declarations above."""
        parts = [*self.env_required]
        if self.extra_requires:
            parts.append(self.extra_requires)
        return " + ".join(parts)

    def available(self) -> bool:
        """True when this backend is usable.

        The default checks that every var in env_required has a non-blank
        value, which is what makes availability and stated requirements the
        same fact. Override only for a non-environment prerequisite (an
        importable package, say) — and call super() so the env check still runs.
        """
        return all(os.environ.get(v, "").strip() for v in self.env_required)

    @abstractmethod
    def generate(self, prompt: str, query: str | None = None,
                 negative: str | None = None,
                 api_key: "SecureString | None" = None,
                 model: str | None = None,
                 on_preview_url=None) -> bytes:
        """Return a 1920x1080 PNG as bytes, or raise to let the fallback
        chain try the next provider. on_preview_url, if provided, is called
        with the provider's raw CDN URL before any download/conversion."""
