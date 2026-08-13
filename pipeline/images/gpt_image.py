"""OpenAI image backend (~$0.01-0.02/image at low quality). Needs OPENAI_API_KEY
and the model id in .env (OPENAI_IMAGE_MODEL) — no model is hardcoded."""
import base64
import io
import os
from pathlib import Path

from PIL import Image

from .base import ImageProvider
from .util import to_png_bytes


def _model() -> str:
    """Image model id — from .env (OPENAI_IMAGE_MODEL). No hardcoded default."""
    model = os.environ.get("OPENAI_IMAGE_MODEL", "").strip()
    if not model:
        raise RuntimeError("no OpenAI image model set — put OPENAI_IMAGE_MODEL in .env")
    return model


class GptImageProvider(ImageProvider):
    name = "gpt-image-1"
    aliases = ("openai", "gpt")
    # Both vars: _model() raises without OPENAI_IMAGE_MODEL, so --backend
    # gpt-image-1 on a key-only setup failed at generation time rather than at
    # selection time — after the plan had already been paid for.
    env_required = ("OPENAI_API_KEY", "OPENAI_IMAGE_MODEL")
    model_env = "OPENAI_IMAGE_MODEL"
    # NOT a fixed string: OPENAI_IMAGE_MODEL is configurable, and the rate
    # follows the model. A per-backend figure quoted the gpt-image-1 price
    # while a run generated on gpt-image-2 — the money guard was model-blind.
    # Every figure here is copied from a provider docstring; an unknown model
    # says so rather than guessing.
    _MODEL_COST = {
        # This module's docstring; generate() hardcodes quality="low".
        "gpt-image-1": "PAID ~$0.01-0.02/image",   # generate() hardcodes quality="low"
    }

    @property
    def cost(self) -> str:
        model = os.environ.get(self.model_env or "", "").strip()
        if not model:
            return "PAID — no model set"
        known = self._MODEL_COST.get(model)
        return f"{known} ({model})" if known else (
            f"PAID — rate unknown for {model}")
    paid = True
    can_edit = True

    def generate(self, prompt: str, query: str | None = None,
                 negative: str | None = None, api_key=None,
                 model: str | None = None, on_preview_url=None) -> bytes:
        from openai import OpenAI

        if negative:
            prompt = f"{prompt}. Do not include: {negative}."
        client = OpenAI(api_key=api_key.decrypt()) if api_key else OpenAI()
        result = client.images.generate(
            model=model or _model(), prompt=prompt, size="1536x1024", quality="low", n=1,
        )
        img = Image.open(io.BytesIO(base64.b64decode(result.data[0].b64_json))).convert("RGB")
        return to_png_bytes(img)

    def edit(self, prompt: str, reference,
             negative: str | None = None, api_key=None,
             model: str | None = None, on_preview_url=None) -> bytes:
        from openai import OpenAI

        if negative:
            prompt = f"{prompt}. Do not include: {negative}."
        refs = list(reference) if isinstance(reference, (list, tuple)) else [reference]
        client = OpenAI(api_key=api_key.decrypt()) if api_key else OpenAI()
        handles = []
        try:
            handles = [open(Path(r), "rb") for r in refs]
            result = client.images.edit(
                model=model or _model(),
                image=handles if len(handles) > 1 else handles[0],
                prompt=prompt, size="1536x1024", n=1,
            )
        finally:
            for h in handles:
                h.close()
        img = Image.open(io.BytesIO(base64.b64decode(result.data[0].b64_json))).convert("RGB")
        return to_png_bytes(img)
