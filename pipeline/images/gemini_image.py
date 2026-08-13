"""Google Gemini image backend — "nano banana" (PAID, no free tier).

Priced per generated image, by resolution, from ai.google.dev/gemini-api/docs/pricing
(checked 2026-08-13):

    gemini-3.1-flash-image        0.5K $0.045 | 1K $0.067 | 2K $0.101 | 4K $0.151
    gemini-3.1-flash-lite-image   1K   $0.0336  (1K only)

This backend renders at 2K/16:9, which downsamples cleanly to the pipeline's
1920x1080 — 1K/16:9 is 1024x576 and would need upscaling to fill the frame.
So the figure that applies is $0.101/image on the default model. That is
5-10x gpt-image-1's low-quality rate, which is why `paid` is set and this
backend is never auto-picked.

What it buys: strong subject consistency across images and multi-reference
editing, which is exactly what character reference portraits depend on — see
character_refs() in __init__.py. Only qwen-image and gpt-image-1 could do that
before; this is the third.

Needs GOOGLE_API_KEY (the same variable the Gemini LLM path already uses) and
`pip install google-genai`. The model id is overridable with GEMINI_IMAGE_MODEL.
"""
import base64
import io
import os
from pathlib import Path

from PIL import Image

from .base import ImageProvider
from .util import to_png_bytes

#: 2K/16:9 downsamples cleanly to 1920x1080; see the module docstring on cost.
_ASPECT_RATIO = "16:9"
_IMAGE_SIZE = "2K"

#: Overridable, but defaulted: unlike OPENAI_IMAGE_MODEL there is a sensible
#: default here, and requiring the id would make the backend unusable out of
#: the box for no benefit.
_DEFAULT_MODEL = "gemini-3.1-flash-image"


def _model() -> str:
    return os.environ.get("GEMINI_IMAGE_MODEL", "").strip() or _DEFAULT_MODEL


def _client(api_key=None):
    from google import genai

    key = api_key.decrypt() if api_key else os.environ.get("GOOGLE_API_KEY", "")
    return genai.Client(api_key=key)


def _image_part(path) -> dict:
    return {
        "type": "image",
        "data": base64.b64encode(Path(path).read_bytes()).decode("utf-8"),
        "mime_type": "image/png",
    }


def _render(parts, api_key, model) -> bytes:
    interaction = _client(api_key).interactions.create(
        model=model or _model(),
        input=parts,
        image_config={"aspect_ratio": _ASPECT_RATIO, "image_size": _IMAGE_SIZE},
    )
    raw = base64.b64decode(interaction.output_image.data)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    return to_png_bytes(img)


class GeminiImageProvider(ImageProvider):
    name = "gemini-image"
    aliases = ("gemini", "nano-banana", "nanobanana")
    env_required = ("GOOGLE_API_KEY",)
    extra_requires = "pip install google-genai"
    model_env = "GEMINI_IMAGE_MODEL"
    # From this module's docstring: 2K on the default model. Never estimated.
    cost = "PAID ~$0.10/image at 2K (no free tier)"
    paid = True
    can_edit = True

    def available(self) -> bool:
        # Overridden for the one non-environment prerequisite. super() still
        # does the env_required check, so the declaration stays authoritative.
        if not super().available():
            return False
        try:
            from google import genai  # noqa: F401
        except ImportError:
            return False
        return True

    def generate(self, prompt: str, query: str | None = None,
                 negative: str | None = None, api_key=None,
                 model: str | None = None, on_preview_url=None) -> bytes:
        # No negative-prompt parameter in this API, so it goes in the prompt.
        # Phrased as an exclusion instruction rather than bare words, because
        # image models draw negated nouns (CLAUDE.md, "hard-won gotchas").
        if negative:
            prompt = f"{prompt}. Do not include: {negative}."
        return _render([{"type": "text", "text": prompt}], api_key, model)

    def edit(self, prompt: str, reference,
             negative: str | None = None, api_key=None,
             model: str | None = None, on_preview_url=None) -> bytes:
        if negative:
            prompt = f"{prompt}. Do not include: {negative}."
        refs = list(reference) if isinstance(reference, (list, tuple)) else [reference]
        parts = [{"type": "text", "text": prompt}, *(_image_part(r) for r in refs)]
        return _render(parts, api_key, model)
