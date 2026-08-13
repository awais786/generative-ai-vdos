"""Qwen text-to-image via Alibaba Model Studio (DashScope SDK).

Uses the same DASHSCOPE_API_KEY (and optional DASHSCOPE_API_URL workspace
endpoint) as the Wan video backend. Model Studio's new-user free quota covers
the qwen-image models, so images are $0 while it lasts.
"""
import base64
import io
import os
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from PIL import Image
from dashscope import MultiModalConversation

import logging

from ..env import dashscope_configured
from .base import ImageProvider
from .util import to_png_bytes

logger = logging.getLogger(__name__)

SIZE = "1664*928"  # native 16:9; fit_cover upscales to 1920x1080
_CONCURRENT_LIMIT = 2
_SEM_KEY = "dashscope:image:concurrent"
_SEM_WAIT = 300

_acquire_lua = """
local n = redis.call('incr', KEYS[1])
redis.call('expire', KEYS[1], 600)
if n <= tonumber(ARGV[1]) then return 1 end
redis.call('decr', KEYS[1])
return 0
"""

_release_lua = """
local n = redis.call('get', KEYS[1])
if not n then return 0 end
n = redis.call('decr', KEYS[1])
if n <= 0 then redis.call('del', KEYS[1]) end
return n
"""


@contextmanager
def _concurrency_slot():
    import redis as redis_lib
    broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    try:
        r = redis_lib.from_url(broker_url)
        acquire = r.register_script(_acquire_lua)
        release = r.register_script(_release_lua)
    except Exception as exc:
        raise RuntimeError(
            "Failed to initialize DashScope concurrency slot redis client "
            f"(CELERY_BROKER_URL={broker_url!r})"
        ) from exc
    deadline = time.monotonic() + _SEM_WAIT
    acquired = False
    while time.monotonic() < deadline:
        if acquire(keys=[_SEM_KEY], args=[_CONCURRENT_LIMIT]):
            acquired = True
            break
        time.sleep(0.5)
    else:
        raise TimeoutError(
            f"Timed out after {_SEM_WAIT}s waiting for DashScope concurrency slot "
            f"(limit: {_CONCURRENT_LIMIT} concurrent requests)"
        )
    try:
        yield
    finally:
        if acquired:
            release(keys=[_SEM_KEY])


MAX_PROMPT = 1500  # warn before cutting; most models accept well beyond this
MAX_REFS = 3  # cap on reference images sent per edit

_BASE_NEGATIVE = ("text, words, captions, typography, letters, "
                  "watermark, logo, subtitles")


def _negative_prompt(extra: str | None = None) -> str:
    return f"{_BASE_NEGATIVE}, {extra}" if extra else _BASE_NEGATIVE


def _gen_model() -> str:
    """Text-to-image model id — from .env (QWEN_IMAGE_MODEL). No hardcoded
    default: the code is model-agnostic, so the id must be set explicitly.
    Read at call time because .env loads after this module is imported."""
    model = os.environ.get("QWEN_IMAGE_MODEL", "").strip()
    if not model:
        raise RuntimeError("no image model set — put QWEN_IMAGE_MODEL in .env")
    return model


def _edit_model() -> str:
    """Reference-edit model id — from .env (QWEN_EDIT_MODEL), falling back to
    QWEN_IMAGE_MODEL when the same model does both jobs."""
    model = (os.environ.get("QWEN_EDIT_MODEL", "").strip()
             or os.environ.get("QWEN_IMAGE_MODEL", "").strip())
    if not model:
        raise RuntimeError(
            "no edit model set — put QWEN_EDIT_MODEL (or QWEN_IMAGE_MODEL) in .env")
    return model


class QwenImageProvider(ImageProvider):
    name = "qwen-image"
    aliases = ("qwen", "dashscope")
    # Both, not the key alone: _gen_model() raises without QWEN_IMAGE_MODEL, and
    # this provider is first in PROVIDERS — so a key-only check would make
    # auto-pick choose a backend that then dies at generation time.
    env_required = ("DASHSCOPE_API_KEY", "QWEN_IMAGE_MODEL")
    model_env = "QWEN_IMAGE_MODEL"
    cost = "free while the Model Studio quota lasts"
    can_edit = True

    def _post(self, model: str, content: list,
              parameters: dict, api_key=None, on_preview_url=None) -> bytes:
        with _concurrency_slot():
            return self._post_inner(model, content, parameters, api_key,
                                    on_preview_url=on_preview_url)

    def _post_inner(self, model: str, content: list,
                    parameters: dict, api_key=None, on_preview_url=None) -> bytes:
        key = api_key.decrypt() if api_key else None
        with dashscope_configured(base_url=getattr(api_key, "api_url", None)):
            rsp = MultiModalConversation.call(
                model=model,
                messages=[{"role": "user", "content": content}],
                api_key=key,
                **parameters,
            )
        if rsp.status_code != 200:
            raise RuntimeError(f"qwen image failed [{rsp.code}]: {rsp.message}")
        image_url = rsp.output.choices[0].message.content[0]["image"]
        if on_preview_url is not None:
            try:
                on_preview_url(image_url)
            except Exception as e:
                logger.warning("on_preview_url callback failed (ignored): %s", e)
        with urllib.request.urlopen(image_url, timeout=60) as resp:
            img = Image.open(io.BytesIO(resp.read())).convert("RGB")
        return to_png_bytes(img)

    def generate(self, prompt: str, query: str | None = None,
                 negative: str | None = None, api_key=None,
                 model: str | None = None, on_preview_url=None) -> bytes:
        if len(prompt) > MAX_PROMPT:
            print(f"  images: WARNING prompt is {len(prompt)} chars, cutting to "
                  f"{MAX_PROMPT} — some detail at the end will be lost")
        return self._post(model or _gen_model(), [{"text": prompt[:MAX_PROMPT]}], {
            "size": SIZE,
            "n": 1,
            "prompt_extend": False,
            "watermark": False,
            "negative_prompt": _negative_prompt(negative),
        }, api_key=api_key, on_preview_url=on_preview_url)

    def edit(self, prompt: str, reference,
             negative: str | None = None, api_key=None,
             model: str | None = None, on_preview_url=None) -> bytes:
        refs = list(reference) if isinstance(reference, (list, tuple)) else [reference]
        content = [{"image": "data:image/png;base64,"
                    + base64.b64encode(Path(r).read_bytes()).decode()}
                   for r in refs[:MAX_REFS]]
        content.append({"text": prompt[:MAX_PROMPT]})
        return self._post(model or _edit_model(), content, {
            "n": 1,
            "prompt_extend": False,
            "watermark": False,
            "negative_prompt": _negative_prompt(negative),
        }, api_key=api_key, on_preview_url=on_preview_url)
