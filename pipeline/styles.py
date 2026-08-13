"""Curated style presets for visual consistency across videos."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    "cinematic": {
        "style_prefix": (
            "cinematic photo, muted colors, shallow depth of field, "
            "anamorphic lens flare, film grain"
        ),
        "global_negative": (
            "cartoon, anime, drawing, painting, oversaturated, "
            "text, watermark, blurry, extra limbs"
        ),
        "music_mood": "dramatic",
        "palette": {"bg1": "#0b0b12", "bg2": "#3a1f22", "fg": "#f4ead6",
                    "accent": "#e0714a", "glow": "rgba(224,113,74,0.24)"},
        "consistency_anchors": [
            "same colour grade across every scene",
            "same time of day and lighting direction",
        ],
        "text": {"caption_size": 18, "caption_outline": 2,
                 "overlay_size": 58, "overlay_border": 3},
    },
    "anime": {
        "style_prefix": (
            "anime illustration, vibrant cel-shading, bold outlines, "
            "detailed backgrounds, studio ghibli inspired"
        ),
        "global_negative": (
            "photorealistic, photo, 3d render, text, watermark, "
            "blurry, extra limbs, bad anatomy"
        ),
        "music_mood": "upbeat",
        "palette": {"bg1": "#101a2e", "bg2": "#2f4d7a", "fg": "#fdf6ec",
                    "accent": "#ffb84d", "glow": "rgba(255,184,77,0.26)"},
        "consistency_anchors": [
            "same cel-shading treatment in every scene",
            "same line weight and colour saturation",
        ],
        "text": {"caption_size": 19, "caption_outline": 3,
                 "overlay_size": 60, "overlay_border": 4},
    },
    "watercolor": {
        "style_prefix": (
            "watercolor painting, soft washes, visible brush strokes, "
            "muted pastel palette, textured paper"
        ),
        "global_negative": (
            "photo, photorealistic, sharp lines, digital art, "
            "text, watermark, blurry"
        ),
        "music_mood": "calm",
        "palette": {"bg1": "#2a2a33", "bg2": "#6b6478", "fg": "#fbf6ef",
                    "accent": "#e3a7a1", "glow": "rgba(227,167,161,0.22)"},
        "consistency_anchors": [
            "same pastel wash palette in every scene",
            "same paper texture and brush treatment",
        ],
        "text": {"caption_size": 18, "caption_outline": 2,
                 "overlay_size": 54, "overlay_border": 3},
    },
    "documentary": {
        "style_prefix": (
            "photojournalistic photo, natural lighting, candid composition, "
            "neutral color grade, 35mm lens"
        ),
        "global_negative": (
            "cartoon, painting, stylized, text, watermark, "
            "blurry, extra limbs, oversaturated"
        ),
        "music_mood": "inspiring",
        "palette": {"bg1": "#14161a", "bg2": "#39424d", "fg": "#f2f4f6",
                    "accent": "#7fa8c9", "glow": "rgba(127,168,201,0.20)"},
        "consistency_anchors": [
            "same neutral colour grade across every scene",
            "same natural lighting quality",
        ],
        "text": {"caption_size": 18, "caption_outline": 2,
                 "overlay_size": 52, "overlay_border": 3},
    },
    "storybook": {
        "style_prefix": (
            "children's storybook illustration, warm soft colors, "
            "whimsical details, hand-drawn feel, gentle lighting"
        ),
        "global_negative": (
            "photo, photorealistic, dark, scary, violent, "
            "text, watermark, blurry"
        ),
        "music_mood": "calm",
        # Sampled from what this preset's style_prefix actually renders: warm
        # yellows and golden sand (#fee373, #fbbd46). The previous values were a
        # dark plum picked by intuition, which put a purple card against bright
        # hand-drawn illustrations — the very mismatch the style sidecar exists
        # to prevent, reintroduced through bad preset data rather than bad wiring.
        "palette": {"bg1": "#f4e3c1", "bg2": "#e6c98f", "fg": "#3b2a1a",
                    "accent": "#b4622d", "glow": "rgba(180,98,45,0.24)"},
        "consistency_anchors": [
            "same warm illustrative palette in every scene",
            "same soft lighting and rounded shapes",
        ],
        "text": {"caption_size": 19, "caption_outline": 3,
                 "overlay_size": 58, "overlay_border": 3},
    },
    "noir": {
        "style_prefix": (
            "film noir, high contrast black and white, dramatic shadows, "
            "venetian blind lighting, rain-slicked streets"
        ),
        "global_negative": (
            "color, colorful, bright, cartoon, anime, "
            "text, watermark, blurry, extra limbs"
        ),
        "music_mood": "mysterious",
        "palette": {"bg1": "#08080a", "bg2": "#2b2b30", "fg": "#ededf0",
                    "accent": "#c0392b", "glow": "rgba(192,57,43,0.24)"},
        "consistency_anchors": [
            "same high-contrast black and white grade in every scene",
            "same hard directional key light",
        ],
        "text": {"caption_size": 18, "caption_outline": 3,
                 "overlay_size": 56, "overlay_border": 4},
    },
    "retro-pixel": {
        "style_prefix": (
            "16-bit pixel art, retro game aesthetic, limited color palette, "
            "dithering, CRT scanlines"
        ),
        "global_negative": (
            "photo, photorealistic, smooth gradients, 3d render, "
            "text, watermark, blurry"
        ),
        "music_mood": "upbeat",
        "palette": {"bg1": "#12102a", "bg2": "#3b2f6b", "fg": "#f7f5ff",
                    "accent": "#41e0a3", "glow": "rgba(65,224,163,0.26)"},
        "consistency_anchors": [
            "same limited pixel palette in every scene",
            "same pixel grid size and dithering",
        ],
        "text": {"caption_size": 20, "caption_outline": 3,
                 "overlay_size": 56, "overlay_border": 4},
    },
}


STYLE_FILE = "style.json"

# Keys copied into the sidecar. style_prefix / global_negative / music_mood are
# deliberately excluded: those already live in shot_plan.json, and duplicating
# them would create a second source that could disagree with the first.
_SIDECAR_KEYS = ("palette", "consistency_anchors", "text", "source")


def save_style(work_dir: Path, preset: dict | None) -> Path | None:
    """Write the resolved style to work_dir/style.json.

    Call this AFTER refine_plan() — polish and consistency review each return a
    fresh plan parsed from the LLM, so a style written earlier would describe a
    plan that no longer exists.

    Returns None (writing nothing) when there is no preset, or when the preset
    carries none of the sidecar keys — as with `custom:` styles, which are just a
    style_prefix.
    """
    if not preset:
        return None
    payload = {k: preset[k] for k in _SIDECAR_KEYS if preset.get(k)}
    if not payload:
        return None
    for name, candidate in PRESETS.items():
        if candidate is preset:
            payload["name"] = name
            break
    path = Path(work_dir) / STYLE_FILE
    path.write_text(json.dumps(payload, indent=2))
    return path


def load_style(work_dir: Path) -> dict:
    """Read work_dir/style.json, or {} when absent or unreadable.

    Never raises: every consumer must fall back to its previous hardcoded
    behaviour rather than failing a render over a style file.
    """
    path = Path(work_dir) / STYLE_FILE
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_PALETTE_REQUIRED = ("bg1", "bg2", "fg", "accent")


def validate_palette(raw: object) -> dict[str, str] | None:
    """A model-proposed palette, or None if it is not usable.

    Mirrors OpenMontage's playbook_generator, which jsonschema-validates a
    generated playbook before use: the model supplies the values, the validator
    guarantees the shape. A bad colour must never reach Remotion or libass,
    where it renders wrong rather than raising.

    `glow` is derived from `accent` rather than requested, so it cannot be
    malformed and the model has one fewer field to get wrong.
    """
    if not isinstance(raw, dict):
        return None
    out: dict[str, str] = {}
    for key in _PALETTE_REQUIRED:
        value = raw.get(key)
        if not isinstance(value, str) or not _HEX.match(value):
            return None
        out[key] = value.lower()
    r, g, b = (int(out["accent"][i:i + 2], 16) for i in (1, 3, 5))
    out["glow"] = f"rgba({r},{g},{b},0.24)"
    return out


def style_for_plan(preset: dict | None, proposed: object) -> dict | None:
    """The style to persist: a named preset always wins over the model.

    A preset is a promise that every video in that style matches; a per-video
    suggestion must not break it. With no preset, a valid proposal is better
    than the music_mood fallback, which is what the card would otherwise use.
    """
    if preset:
        if preset.get("palette"):
            return preset
        # A `custom:` style is only a style_prefix — it carries no palette, so
        # returning it here left save_style() with no sidecar keys to write and
        # the cards falling back to the music_mood table. That made
        # --style "custom:neon cyberpunk" produce WORSE card colours than
        # passing no style at all, while a valid model proposal sat unused.
        custom_palette = validate_palette(proposed)
        if not custom_palette:
            return preset
        return {**preset, "palette": custom_palette, "source": "model"}
    palette = validate_palette(proposed)
    if not palette:
        return None
    # source="model" marks a palette the LLM invented rather than one a preset
    # promised. The compose cards use it — that is the bug the sidecar exists to
    # fix — but burned-in captions and overlays do not: the style-playbook spec
    # is explicit that the LLM never authors style values, and an invented
    # colour on every default run would decide the legibility of every caption.
    return {"palette": palette, "consistency_anchors": [], "text": {},
            "source": "model"}


def resolve_style(raw: str | None) -> dict[str, Any] | None:
    """Resolve a CLI/env style value into a preset dict (or None)."""
    if raw is None:
        return None

    normalized = raw.strip().lower()

    if normalized == "list":
        _list_presets()
        sys.exit(0)

    if normalized.startswith("custom:"):
        return {
            "style_prefix": raw.strip()[len("custom:"):].strip(),
            "global_negative": None,
            "music_mood": None,
        }

    if normalized in PRESETS:
        return PRESETS[normalized]

    raise ValueError(
        f"Unknown style '{raw}'. Available: {', '.join(PRESETS)}"
    )


def _list_presets() -> None:
    for name, preset in PRESETS.items():
        print(f"  {name:<14} {preset['style_prefix']}")


def inject_style_instruction(preset: dict[str, Any]) -> str:
    """Build an LLM instruction block that constrains style fields."""
    lines = [
        "STYLE CONSTRAINT (mandatory — do not override):",
        f'- style_prefix must be exactly: "{preset["style_prefix"]}"',
    ]
    if preset.get("global_negative"):
        lines.append(
            f'- global_negative must be exactly: "{preset["global_negative"]}"'
        )
    if preset.get("music_mood"):
        lines.append(f'- music_mood must be exactly: "{preset["music_mood"]}"')
    lines.append(
        "\nREMINDER: Any visual element (object, person, animal, flag, vehicle) "
        "that appears in more than one scene MUST have a character entry with a "
        "{placeholder} in every image_prompt where it appears. This includes "
        "key props like food, treasures, or landmarks — not just people."
    )
    return "\n".join(lines)
