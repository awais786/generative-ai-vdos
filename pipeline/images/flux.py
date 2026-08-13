"""Replicate image backend (~$0.003/image for Flux Schnell). Needs
REPLICATE_API_TOKEN, the replicate package, and the model id in .env
(REPLICATE_IMAGE_MODEL) — no model is hardcoded."""
import logging
import os
import urllib.request

from .base import ImageProvider

logger = logging.getLogger(__name__)


class FluxProvider(ImageProvider):
    name = "flux-schnell"
    aliases = ("flux", "replicate")
    # Both vars: _model() raises without REPLICATE_IMAGE_MODEL, and flux is
    # auto-pickable — so a token-only setup was selected and then failed on
    # every scene, falling through the chain one at a time (or dying outright
    # with --backend flux, where there is no fallback).
    env_required = ("REPLICATE_API_TOKEN", "REPLICATE_IMAGE_MODEL")
    extra_requires = "pip install replicate"
    cost = "free tier, then ~$0.003/image"

    def available(self) -> bool:
        # Overridden for the one non-environment prerequisite. super() still
        # does the env_required check, so the declaration stays authoritative.
        if not super().available():
            return False
        try:
            import replicate  # noqa: F401
        except ImportError:
            return False
        return True

    def generate(self, prompt: str, query: str | None = None,
                 negative: str | None = None, api_key=None,
                 model: str | None = None, on_preview_url=None) -> bytes:
        import replicate as replicate_pkg

        model = model or os.environ.get("REPLICATE_IMAGE_MODEL", "").strip()
        if not model:
            raise RuntimeError(
                "no Replicate image model set — put REPLICATE_IMAGE_MODEL in .env")
        client = replicate_pkg.Client(api_token=api_key.decrypt()) if api_key else replicate_pkg
        output = client.run(
            model,
            input={"prompt": prompt, "aspect_ratio": "16:9", "output_format": "png"},
        )
        url = str(output[0]) if isinstance(output, list) else str(output)
        if on_preview_url is not None:
            try:
                on_preview_url(url)
            except Exception as e:
                logger.warning("on_preview_url callback failed (ignored): %s", e)
        with urllib.request.urlopen(url, timeout=60) as resp:
            return resp.read()
