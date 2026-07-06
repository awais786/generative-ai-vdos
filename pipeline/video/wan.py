"""Wan image-to-video via Alibaba Model Studio (DashScope SDK).

Needs DASHSCOPE_API_KEY (and optionally DASHSCOPE_API_URL for a workspace
endpoint). New intl (Singapore) accounts get ~1650s of free video generation
credit for 90 days; after that roughly $0.10-0.25 per 5s clip.

Model/resolution/duration are fixed constants below — clips are capped at
5 seconds to keep credit use predictable while testing.
"""
import os
import time
import urllib.request
from pathlib import Path
from typing import Optional

from dashscope import VideoSynthesis

from ..env import dashscope_configured
from .base import VideoProvider

# Quality tiers — verify model IDs in your DashScope console if one errors.
QUALITY_MODELS = {
    "flash": "wan2.2-i2v-flash",   # default: fast, basic motion
    "turbo": "wan2.1-i2v-turbo",   # better prompt-following, ~same cost
    "plus":  "wan2.1-i2v-plus",    # best quality, slower
}
RESOLUTION = "720P"
MAX_DURATION = 5            # seconds — hard cap per clip


class WanProvider(VideoProvider):
    name = "wan-i2v"

    def __init__(self, quality: str = "flash") -> None:
        if quality not in QUALITY_MODELS:
            raise ValueError(f"wan quality must be flash|turbo|plus, got '{quality}'")
        self._model = QUALITY_MODELS[quality]
        self._quality = quality

    def available(self) -> bool:
        return bool(os.environ.get("DASHSCOPE_API_KEY"))

    def submit(self, prompt: str, image_path: Path, api_key=None) -> str:
        key = api_key.decrypt() if api_key else None
        img_url = "file://" + str(image_path)
        with dashscope_configured(base_url=getattr(api_key, "api_url", None)):
            rsp = VideoSynthesis.async_call(
                model=self._model,
                prompt=prompt,
                img_url=img_url,
                resolution=RESOLUTION,
                duration=MAX_DURATION,
                prompt_extend=True,
                watermark=False,
                api_key=key,
            )
        if rsp.status_code != 200:
            raise RuntimeError(f"wan submit failed [{rsp.code}]: {rsp.message}")
        return rsp.output.task_id

    def poll(self, task_id: str, api_key=None) -> Optional[str]:
        key = api_key.decrypt() if api_key else None
        with dashscope_configured(base_url=getattr(api_key, "api_url", None)):
            rsp = VideoSynthesis.fetch(task_id, api_key=key)
        if rsp.status_code != 200:
            raise RuntimeError(f"wan poll failed [{rsp.code}]: {rsp.message}")
        status = rsp.output.task_status
        if status == "SUCCEEDED":
            return rsp.output.video_url
        if status in ("FAILED", "CANCELED", "UNKNOWN"):
            raise RuntimeError(f"wan task {status}: {rsp.message}")
        return None  # PENDING / RUNNING

    def download(self, url: str, out_path: Path) -> None:
        urllib.request.urlretrieve(url, out_path)

    def generate(self, prompt: str, image_path: Path, out_path: Path, api_key=None) -> None:
        task_id = self.submit(prompt, image_path, api_key)
        deadline = time.time() + 15 * 60
        while time.time() < deadline:
            time.sleep(15)
            url = self.poll(task_id, api_key)
            if url:
                self.download(url, out_path)
                return
        raise RuntimeError(f"wan task timed out after 15 min (task_id={task_id})")
