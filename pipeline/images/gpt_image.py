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
    env_required = ("OPENAI_API_KEY",)
    model_env = "OPENAI_IMAGE_MODEL"
    # From this module's docstring; generate() hardcodes quality="low".
    cost = "PAID ~$0.01-0.02/image"
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
