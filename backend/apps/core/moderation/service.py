import logging
import os

from django.conf import settings

from .blocklist import contains_blocked_term
from .exceptions import ContentPolicyViolation

logger = logging.getLogger(__name__)


def content_moderation_enabled() -> bool:
    return bool(getattr(settings, "CONTENT_MODERATION_ENABLED", False))


def check_text(text: str | None, *, context: str = "") -> None:
    """Raise ContentPolicyViolation when moderation is enabled and text is disallowed."""
    if not content_moderation_enabled():
        return

    normalized = (text or "").strip()
    if not normalized:
        return

    if contains_blocked_term(normalized):
        logger.info("Content blocked by local filter%s", f" ({context})" if context else "")
        raise ContentPolicyViolation()

    if _openai_flags(normalized):
        logger.info("Content blocked by OpenAI moderation%s", f" ({context})" if context else "")
        raise ContentPolicyViolation()


def check_texts(*texts: str | None, context: str = "") -> None:
    """Check multiple strings; raises on the first violation."""
    for text in texts:
        check_text(text, context=context)


def _openai_flags(text: str) -> bool:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return False

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai package unavailable — skipping API moderation")
        return False

    client = OpenAI(api_key=api_key)
    response = client.moderations.create(
        input=text,
        model="omni-moderation-latest",
    )
    return any(result.flagged for result in response.results)
