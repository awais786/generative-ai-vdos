"""Formatting primitives for the run header each stage prints before it works.

Every stage states three things up front: what it will use, where that came from,
and whether it costs money. The web app captures stage stdout verbatim as job
logs, so a line here is always short, single-line plain text — no ANSI colour,
no box drawing.

    plan      gpt-4o-mini            via LLM_PROVIDER=openai, paid ~$0.001/plan
    images    qwen-image             DASHSCOPE_API_KEY, free, 8 scenes
              -> flux-schnell skipped (needs REPLICATE_API_TOKEN)
    warning   no music/inspiring/ folder — picked a random track instead

Each stage builds its own lines next to the knowledge they describe:
`script_agent.plan_report`, `images.selection_report`, `voiceover.voice_report`,
`assemble.music_report`.
"""

LABEL_W = 9    # width of the stage-name column
VALUE_W = 22   # width of the chosen-thing column
MAX_LINE = 120  # hard cap on any emitted line — job logs, not a terminal


def fit(text: str, limit: int = MAX_LINE) -> str:
    """Force one line inside the budget. Callers put authored text first and
    variable-length material (an API error, a path) last, so what gets cut is
    the least important half."""
    text = text.replace("\r", " ").replace("\n", " ")  # never span two log lines
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def row(label: str, value: str, note: str = "") -> str:
    """A stage's headline choice: `<label> <value>  <where it came from + cost>`."""
    if not note:
        return fit(f"{label:<{LABEL_W}} {value}".rstrip())
    return fit(f"{label:<{LABEL_W}} {value:<{VALUE_W}} {note}".rstrip())


def note_line(text: str) -> str:
    """A detail hanging under the previous row (a skipped backend, a fallback)."""
    return fit(f"{'':<{LABEL_W}} -> {text}")


def short_path(path: object, limit: int = 48) -> str:
    """Shorten a path from the LEFT, so the identifying tail survives:
    `.../pytest-90/run-1/music/inspiring`. Plain `fit()` would cut the tail,
    which is the only part that names the thing."""
    text = str(path)
    return text if len(text) <= limit else "..." + text[-(limit - 3):]


def plural(n: int, noun: str) -> str:
    """`3 scenes` / `1 scene` — headers state counts, and '1 scenes' reads badly."""
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def brief(err: object, limit: int = 90) -> str:
    """Collapse an exception (often multi-line) into one short log-safe string."""
    text = " ".join(str(err).split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def warning(text: str) -> str:
    """A stage-level warning. Labelled so it is greppable in captured job logs."""
    return fit(f"{'warning':<{LABEL_W}} {text}")
