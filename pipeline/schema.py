"""The shot plan — the contract every downstream stage consumes."""
import re
from typing import List, Literal, Optional

from pydantic import AliasChoices, BaseModel, Field, model_validator

MAX_ANIMATED_SCENES = 2  # hard cap — animating costs DashScope credit
MAX_PROMPT_CHARS = 1000


class Character(BaseModel):
    name: str = Field(description="Short lowercase placeholder id, e.g. 'thief' or 'mom'.")
    description: str = Field(
        description="Full visual description: age, hair, face, every clothing item "
        "with its color, e.g. 'a mid-30s man with short black hair and stubble, wearing "
        "a black zip-up hoodie, dark blue jeans and white sneakers'. This is the "
        "character's default look, used in every scene unless an outfit is selected."
    )
    outfits: Optional[dict[str, str]] = Field(
        default=None,
        description="Alternate complete looks for this character. Each value is a full "
        "visual description (identity + clothing), just like 'description'. Example: "
        "{\"superhero\": \"a 6-year-old boy with messy brown hair, round face, big hazel "
        "eyes, wearing a red Superman t-shirt and blue jeans\"}. When a scene selects an "
        "outfit by name, the pipeline uses that description instead of the default.",
    )
    negative: Optional[str] = Field(
        default=None,
        description="Traits this character must NEVER have in any scene. Merged automatically "
        "into the negative_prompt of every scene they appear in. Use for traits the image "
        "model keeps adding: e.g. 'hair, beard' for a bald character; "
        "'dark hair, black hair' for a white-haired character.",
    )
    is_inanimate: bool = Field(
        default=False,
        description="True for non-person, non-animal characters (props, food, landmarks, "
        "vehicles, treasures). Controls reference-image prompting: inanimate characters "
        "get product-style shots instead of portrait poses.",
    )

    def resolve_description(self, outfit_name: str | None = None) -> str:
        if not outfit_name or not self.outfits:
            return self.description
        return self.outfits.get(outfit_name, self.description)


class ComposeSpec(BaseModel):
    """A text/motion scene rendered by the Remotion composition track instead of
    image generation. Renders straight into the video/scene_NN.mp4 slot the FFmpeg
    assembler already prefers, so it needs no image and no animate credit."""

    template: Literal["title_card", "quote", "lower_third", "outro"] = Field(
        description="Which Remotion template renders this scene: "
        "'title_card' (an intro title with an optional supporting line), "
        "'quote' (a centered quotation with an optional attribution), "
        "'lower_third' (a lower-left name/label with an optional role line), or "
        "'outro' (a centered closing/CTA card with an optional supporting line)."
    )
    heading: str = Field(
        description="Main text: the title (title_card), the quote text (quote), "
        "the name/label (lower_third), or the closing line (outro)."
    )
    subheading: Optional[str] = Field(
        default=None,
        description="title_card / lower_third / outro: a short supporting line "
        "(a subtitle, a role, or a call to action). Ignored for quote.",
    )
    attribution: Optional[str] = Field(
        default=None,
        description="quote only: who said it, e.g. 'Rumi' (rendered as '— Rumi').",
    )


class Scene(BaseModel):
    narration: str = Field(description="Voiceover text for this scene, 1-3 sentences.")
    media_prompt: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("media_prompt", "image_prompt"),
        description="Visual description for image generation. Concrete and specific; "
        "no text rendering requests. The global style_prefix is prepended automatically. "
        "Omit when this scene is composition-driven (set `compose` instead).",
    )
    compose: Optional[ComposeSpec] = Field(
        default=None,
        description="Set this to render the scene as a text/motion card via Remotion "
        "(title card, quote) instead of a generated image. When set, media_prompt and "
        "animate are ignored for this scene.",
    )
    on_screen_text: Optional[str] = Field(
        default=None,
        description="Optional short overlay text (max ~6 words). Must add "
        "something the narration does not say — a label, a name, a number, or "
        "a question. Never repeat a phrase from the narration: the burned-in "
        "captions already show those words.",
    )
    voice: Optional[str] = Field(
        default=None,
        description="Optional edge-tts voice for this scene only (e.g. for dialogue: "
        "'ur-PK-UzmaNeural'). Default: the run-wide narrator voice.",
    )
    motion: Optional[str] = Field(
        default=None,
        description="Optional motion description for the animate stage, e.g. "
        "'the girl is talking, lips moving as she speaks, gesturing with her hands'. "
        "Default: gentle cinematic motion derived from media_prompt.",
    )
    animate: bool = Field(
        default=False,
        description="True only when real motion is essential — flags waving, characters "
        "fighting/dancing/running, animals in action, flowing water, crowd movement. "
        "False for text cards, still portraits, and wide shots where Ken Burns is enough. "
        "Animating costs DashScope credit; be selective.",
    )
    negative_prompt: Optional[str] = Field(
        default=None,
        description="Optional: things the image must NOT contain, e.g. 'beard, mustache'. "
        "Use for traits the model keeps adding; never phrase negatives in image_prompt.",
    )
    reference_image: Optional[str] = Field(
        default=None,
        description="Optional path to a local photo to build this scene on (a real "
        "building, person, product). The image model edits/composes from it instead of "
        "generating from scratch. Needs a backend with edit support (gpt-image-1).",
    )
    outfit: Optional[dict[str, str]] = Field(
        default=None,
        description="Optional per-scene outfit selection. Maps character name to outfit "
        "name defined in that character's outfits dict. Example: {\"boy\": \"superhero\"}. "
        "Characters not listed here use their default description.",
    )

    @model_validator(mode="after")
    def require_visual_source(self) -> "Scene":
        if not self.compose and not self.media_prompt:
            raise ValueError(
                "each scene needs a visual source: set media_prompt (image scene) "
                "or compose (title_card / quote card)"
            )
        if self.compose:
            # compose scenes have no source image to animate — enforce the "animate
            # is ignored" contract in code rather than relying on the LLM prompt.
            self.animate = False
        return self


class ShotPlan(BaseModel):
    title: str = Field(description="YouTube title, under 70 characters, curiosity-driven.")
    description: str = Field(description="YouTube description, 2-4 sentences plus hashtags.")
    tags: List[str] = Field(description="10-15 YouTube tags.")
    music_mood: str = Field(
        description="One word mood for background music: calm, upbeat, dramatic, mysterious, or inspiring."
    )
    style_prefix: str = Field(
        description="Global image style prepended to every scene's image prompt, "
        "e.g. 'cinematic photo, muted colors, shallow depth of field'."
    )
    characters: List[Character] = Field(
        default_factory=list,
        description="Recurring characters. In image_prompt and motion, reference them "
        "ONLY by placeholder, e.g. {thief} — the pipeline substitutes the full "
        "description into every scene, guaranteeing a consistent look.",
    )
    global_negative: Optional[str] = Field(
        default=None,
        description="Negative prompt applied to EVERY scene in the video regardless of "
        "which characters appear. Use for video-wide rules: e.g. "
        "'changing hairstyle, inconsistent clothing, different face, text, watermark, "
        "extra limbs, blurry'. Merged with per-character and per-scene negatives automatically.",
    )
    palette: Optional[dict[str, str]] = Field(
        default=None,
        description=(
            "Four hex colours matching style_prefix, for the text cards and "
            "captions so they match the generated images: bg1 (darkest "
            "background), bg2 (lighter background for a gradient), fg (text, "
            "high contrast against bg1), accent (a highlight drawn from the "
            "imagery). Format #rrggbb. Omit only if the style is purely "
            "photographic with no dominant colour."
        ),
    )
    scenes: List[Scene] = Field(
        description="2-12 scenes. Scene durations come from the voiceover audio.")

    @model_validator(mode="after")
    def cap_animated_scenes(self) -> "ShotPlan":
        animated = [i for i, s in enumerate(self.scenes) if s.animate]
        if len(animated) > MAX_ANIMATED_SCENES:
            for i in animated[MAX_ANIMATED_SCENES:]:
                self.scenes[i].animate = False
        return self

    def characters_in(self, text: str | None, *, by_position: bool = False) -> List[str]:
        """Names of characters referenced in text (via {placeholder} or bare name).

        Default order follows self.characters; with by_position=True, names are
        sorted by their first appearance position in text.
        """
        if not text:
            return []
        found: list[tuple[int, str]] = []
        for c in self.characters:
            pattern = r"\{" + re.escape(c.name) + r"\}|\b" + re.escape(c.name) + r"\b"
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                found.append((m.start(), c.name))
        if by_position:
            found.sort()
        return [name for _, name in found]

    def expand(
        self,
        text: str | None,
        max_chars: int = MAX_PROMPT_CHARS,
        scene_outfit: dict[str, str] | None = None,
        *,
        include_style_overhead: bool = False,
        extra_overhead: int = 0,
    ) -> str:
        """Replace character references with their full descriptions.

        Matches both {name} placeholders and bare names (word-boundary,
        case-insensitive) — LLMs frequently forget the braces.

        A character mentioned more than once in the same text gets its full
        description on the FIRST mention only; later mentions collapse to a
        short reference. Repeating a full description bloats the prompt and
        can make the image model render the same person twice.

        When 3+ characters appear and the fully-expanded text exceeds
        max_chars, a second compact pass runs: only the first two characters
        get full descriptions, the rest use short references.

        Set *include_style_overhead=True* only at call sites that prepend
        ``style_prefix`` to the result — this reserves the extra space in the
        budget so the compacting pass triggers at the right threshold. Callers
        that do not prepend style_prefix (motion prompts, refine display, …)
        should leave it False to avoid premature compaction.

        *extra_overhead* reserves space for anything else the caller appends
        that this plan cannot see — the style's consistency anchors live in
        work_dir/style.json, not on the ShotPlan.

        Returns "" for compose scenes (media_prompt/motion is None).
        """
        if not text:
            return ""
        scene_outfit = scene_outfit or {}
        budget = max_chars
        if include_style_overhead:
            # style_prefix is prepended by the caller; extra_overhead covers
            # anything else the caller appends (the style's consistency anchors,
            # which live in style.json rather than on the plan).
            budget -= len(self.style_prefix) + 2 + extra_overhead  # ", " separator
        result = self._expand_once(text, scene_outfit, compact_after=None)
        refs = self.characters_in(text, by_position=True)
        if len(refs) >= 3 and len(result) > budget:
            result = self._expand_once(text, scene_outfit, compact_after=refs[:2])
        return result

    def _expand_once(self, text: str, scene_outfit: dict[str, str],
                     compact_after: list[str] | None) -> str:
        """Single expansion pass. If compact_after is set, only those characters
        get full descriptions; the rest use short refs everywhere."""
        substituted = False
        for c in self.characters:
            desc = c.resolve_description(scene_outfit.get(c.name)).strip().rstrip(".")
            short = "the " + c.name.replace("_", " ")
            pattern = r"\{" + re.escape(c.name) + r"\}|\b" + re.escape(c.name) + r"\b"
            force_short = compact_after is not None and c.name not in compact_after
            seen = {"n": 0}

            def repl(m, desc=desc, short=short, seen=seen, force_short=force_short):
                seen["n"] += 1
                if force_short or seen["n"] > 1:
                    return short
                return desc

            new, n = re.subn(pattern, repl, text, flags=re.IGNORECASE)
            if n:
                substituted = True
                text = new
        if substituted:
            text = re.sub(r"\b(?:the|a|an) (a|an|the)\b", r"\1", text, flags=re.IGNORECASE)
        text = re.sub(r" {2,}", " ", text).strip()
        return text
