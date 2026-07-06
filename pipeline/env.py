"""Tiny .env loader — zero dependencies.

Looks for .env in the current directory, then next to the pipeline package
(project root). Real environment variables always win; empty values in the
file are ignored so placeholder lines like KEY="" don't shadow anything.
"""
import os
import threading
from contextlib import contextmanager
from pathlib import Path


def load_env() -> None:
    for candidate in (Path.cwd() / ".env",
                      Path(__file__).resolve().parent.parent / ".env"):
        if not candidate.is_file():
            continue
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if value[:1] in ('"', "'"):  # quoted: take up to the closing quote
                end = value.find(value[0], 1)
                value = value[1:end] if end != -1 else value[1:]
            else:  # unquoted: drop a trailing inline comment
                value = value.split(" #", 1)[0].split("\t#", 1)[0].strip()
            if key and value:
                os.environ.setdefault(key, value)
        return


def dashscope_base_url() -> str:
    """DashScope endpoint: workspace URL if configured, else the intl default."""
    url = (os.environ.get("DASHSCOPE_API_URL")
           or os.environ.get("DASHSCOPE_BASE_URL")
           or "https://dashscope-intl.aliyuncs.com/api/v1")
    return url.rstrip("/")


def configure_dashscope_sdk(base_url: str | None = None) -> None:
    """Apply API key and base URL to the dashscope SDK module globals.

    `base_url` overrides the env-derived default — used for a per-user
    DashScope workspace endpoint (UserAPIKey.api_url) when calling on a
    user's behalf.
    """
    import dashscope
    dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY") or ""
    dashscope.base_http_api_url = base_url or dashscope_base_url()


_dashscope_lock = threading.Lock()


@contextmanager
def dashscope_configured(base_url: str | None = None):
    """Configure the dashscope SDK globals and hold them stable for one call.

    dashscope.api_key / base_http_api_url are shared module state. With
    CELERY_TASK_ALWAYS_EAGER (dev + deployment settings) and gthread gunicorn
    workers, requests for different users' DashScope keys/workspace URLs can
    run on separate threads of the same process, so configure-then-call must
    be atomic or one request's globals can leak into another's in-flight call.
    """
    with _dashscope_lock:
        configure_dashscope_sdk(base_url)
        yield
