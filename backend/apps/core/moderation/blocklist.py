import re

# Obvious vulgar terms — fast local pass before optional API moderation.
_BLOCKED_TERMS = (
    "fuck", "fucking", "fucker", "motherfucker",
    "shit", "shitty", "bullshit",
    "bitch", "bastard",
    "asshole", "dickhead",
    "cunt",
    "pussy", "dick", "cock",
    "whore", "slut",
    "nigger", "nigga", "faggot", "retard",
    "porn", "hentai", "xxx",
)

_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in _BLOCKED_TERMS) + r")\b",
    re.IGNORECASE,
)


def contains_blocked_term(text: str) -> bool:
    return bool(_PATTERN.search(text))
