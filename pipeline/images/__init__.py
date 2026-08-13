"""Stage 2: one image per scene, via pluggable provider backends.

Adding a backend: write a module with an ImageProvider subclass (see base.py)
and append an instance to PROVIDERS below. List order = auto-pick priority.

Selection: an explicit backend name wins; otherwise the first available()
provider is used. If a provider fails on a scene (moderation block, no search
results, network error), the remaining available providers are tried in order,
ending at the always-available placeholder.
"""
from pathlib import Path

from ..schema import ShotPlan
from ..styles import load_style
from .base import ImageProvider
from .flux import FluxProvider
from .gpt_image import GptImageProvider
from .pexels import PexelsProvider
from .placeholder import PlaceholderProvider
from .qwen_image import QwenImageProvider

PROVIDERS: list[ImageProvider] = [
    QwenImageProvider(),  # free — always first; also does reference-image editing (consistent faces)
    FluxProvider(),       # free tier only — costs money after quota
    PexelsProvider(),
    PlaceholderProvider(),
    GptImageProvider(),   # paid — never auto-selected, use --backend gpt-image-1 explicitly
]


# Friendly flag values -> the real provider .name, so IMAGE_BACKEND can be set
# to "openai" or "free" instead of remembering exact backend ids.
ALIASES = {
    "openai": "gpt-image-1",
    "gpt": "gpt-image-1",
    "qwen": "qwen-image",
    "dashscope": "qwen-image",
    "flux": "flux-schnell",
    "replicate": "flux-schnell",
    "stock": "pexels",
}


# Paid backend that must never be auto-selected or reached via fallback — only
# via an explicit backend name (money rule). See CLAUDE.md "Money rules".
AUTO_EXCLUDE = {"gpt-image-1"}


def get_provider(name: str | None = None, api_key=None) -> ImageProvider:
    if not name:
        # Auto-pick: first available provider in priority order, skipping the paid
        # gpt-image-1. PlaceholderProvider is always available, so this terminates
        # (renders gradient placeholders when no image key is configured).
        for p in PROVIDERS:
            if p.name not in AUTO_EXCLUDE and p.available():
                return p
        raise RuntimeError(
            "no image backend available (placeholder should always be) — "
            "check pipeline/images/__init__.py PROVIDERS")
    name = ALIASES.get(name.strip().lower(), name)
    for p in PROVIDERS:
        if p.name == name:
            if not api_key and not p.available():
                need = f"set {p.requires} in .env" if p.requires else "missing API key or package"
                raise RuntimeError(f"image backend '{name}' is not configured — {need}")
            return p
    raise RuntimeError(
        f"unknown image backend '{name}' — choices: {', '.join(p.name for p in PROVIDERS)}")


def style_anchors(work_dir: Path | None) -> str:
    """The style's consistency anchors as one appendable phrase, "" when absent.

    Anchors are the positive counterpart to global_negative: invariants stated
    outright ("same colour grade in every scene") instead of left for the model
    to re-infer from style_prefix on each scene. They live in work_dir/style.json,
    so a work dir without one produces byte-identical prompts to before.
    """
    if not work_dir:
        return ""
    anchors = load_style(work_dir).get("consistency_anchors") or []
    return ", ".join(a for a in anchors if a)


def character_refs(plan: ShotPlan, provider: ImageProvider, out_dir: Path,
                   api_key=None, work_dir: Path | None = None) -> dict:
    """Render one clean reference portrait per character (once) so single-character
    scenes can be edited from them for a consistent face/clothing. Only meaningful
    for providers that can edit from a reference (qwen-image, gpt-image-1); returns
    {} otherwise. A character whose portrait fails is simply omitted — its scenes
    fall back to text-to-image.

    The portraits carry the style's consistency anchors too — they are what every
    character scene is edited from, so an un-anchored portrait would re-introduce
    the drift one level down."""
    if not (plan.characters and hasattr(provider, "edit")):
        return {}
    anchor_text = style_anchors(work_dir)
    anchor_suffix = f", {anchor_text}" if anchor_text else ""
    ref_dir = out_dir / "refs"
    ref_dir.mkdir(parents=True, exist_ok=True)
    refs = {}
    print("  images: building character reference portraits (for face consistency)")
    for c in plan.characters:
        p = ref_dir / f"{c.name}.png"
        if not p.is_file():
            desc = c.description.strip().rstrip(".")
            if c.is_inanimate:
                prompt = (f"{plan.style_prefix}, {desc}, "
                          f"plain neutral background, even lighting, "
                          f"centered product-style shot{anchor_suffix}")
            else:
                prompt = (f"{plan.style_prefix}, a character reference portrait of "
                          f"{desc}, neutral standing pose, "
                          f"plain neutral background, even lighting, "
                          f"full head and body visible{anchor_suffix}")
            try:
                data = provider.generate(prompt, negative=c.negative, api_key=api_key)
                p.write_bytes(data)
            except Exception as e:
                print(f"    ref {c.name}: failed ({e}) — scenes will text-to-image instead")
                continue
        refs[c.name] = p
    return refs


def generate_scene_image(
    plan: ShotPlan, index: int, primary: ImageProvider,
    fallback: bool = True, char_refs: dict | None = None,
    api_key=None, model: str | None = None,
    on_preview_url=None, work_dir: Path | None = None,
) -> tuple[bytes, ImageProvider]:
    """Generate one scene's image bytes. With fallback (auto-picked backend),
    failures fall through the remaining providers; an explicitly forced backend
    fails loudly.

    *work_dir* is the video folder (the parent of out_dir), read for
    style.json's consistency anchors; without it the prompt is unchanged."""
    scene = plan.scenes[index]
    anchor_text = style_anchors(work_dir)
    scene_prompt = plan.expand(
        scene.media_prompt, scene_outfit=scene.outfit, include_style_overhead=True,
        extra_overhead=len(anchor_text) + 2 if anchor_text else 0)
    chars_in_scene = plan.characters_in(scene.media_prompt)
    char_map = {character.name: character for character in plan.characters}

    if len(chars_in_scene) >= 3:
        short_names = [" ".join(char_map[n].description.split()[:4])
                       for n in chars_in_scene if n in char_map]
        scene_prompt += f". The scene must include all: {', '.join(short_names)}"
    elif len(chars_in_scene) >= 2:
        # Anchor gender/identity for 2-character scenes — prevents the image model
        # from defaulting both characters to the same gender.
        identity_anchors = [char_map[character_in_scene].description.split(".")[0].split(",")[0]
                            for character_in_scene in chars_in_scene if character_in_scene in char_map]
        if identity_anchors:
            scene_prompt += f". Characters present: {'; '.join(identity_anchors)}"

    prompt = f"{plan.style_prefix}, {scene_prompt}"
    if anchor_text:
        prompt = f"{prompt}, {anchor_text}"

    char_negatives = [
        c.negative for c in plan.characters
        if c.negative and c.name in chars_in_scene
    ]
    merged_negative = ", ".join(filter(None, [
        plan.global_negative,
        *char_negatives,
        scene.negative_prompt,
    ])) or None

    if char_refs and not scene.reference_image and hasattr(primary, "edit"):
        named = [n for n in plan.characters_in(scene.media_prompt) if n in char_refs]
        refs = [char_refs[n] for n in named][:3]
        if refs:
            if len(refs) == 1:
                n0 = named[0]
                char = next(c for c in plan.characters if c.name == n0)
                if char.is_inanimate:
                    edit_prompt = (prompt + " Keep the object's shape, color and "
                                   "details identical to the reference image.")
                else:
                    edit_prompt = (prompt + " Keep the person's face, hair and "
                                   "clothing identical to the reference image.")
            else:
                mapping = "; ".join(f"reference image {i + 1} is {{{n}}}"
                                    for i, n in enumerate(named[:3]))
                any_inanimate = any(
                    char_map[n].is_inanimate for n in named[:3] if n in char_map
                )
                if any_inanimate:
                    consistency = ("Keep each subject's appearance identical to "
                                   "their reference image.")
                else:
                    consistency = ("Keep each person's face, hair and clothing "
                                   "identical to their reference image.")
                edit_prompt = (prompt + f" Identity references — {mapping}. "
                               + consistency)
            try:
                return primary.edit(edit_prompt, refs, negative=merged_negative, api_key=api_key,
                                    model=model, on_preview_url=on_preview_url), primary
            except Exception as e:
                print(f"  images: scene {index + 1} reference edit failed ({e}); "
                      "falling back to text-to-image")

    if scene.reference_image:
        ref = Path(scene.reference_image)
        if not ref.is_file():
            raise RuntimeError(f"scene {index + 1}: reference_image not found: {ref}")
        editor = primary if hasattr(primary, "edit") else next(
            (p for p in PROVIDERS if hasattr(p, "edit")
             and p.name not in AUTO_EXCLUDE and p.available()), None)
        if editor is None:
            raise RuntimeError("reference_image needs a backend with edit support "
                               "(gpt-image-1 — set OPENAI_API_KEY)")
        return editor.edit(prompt, ref, negative=merged_negative, api_key=api_key,
                           model=model, on_preview_url=on_preview_url), editor

    chain = [primary]
    if fallback:
        # Never fall through to the paid gpt-image-1 (money rule); it is only
        # reachable when named explicitly as the primary (which disables fallback).
        chain += [p for p in PROVIDERS
                  if p is not primary and p.name not in AUTO_EXCLUDE and p.available()]
    last_error = None
    for provider in chain:
        try:
            data = provider.generate(prompt, query=scene_prompt, negative=merged_negative,
                                     api_key=api_key, model=model,
                                     on_preview_url=on_preview_url if provider is primary else None)
            return data, provider
        except Exception as e:
            last_error = e
            more = "; trying next" if provider is not chain[-1] else ""
            print(f"  images: scene {index + 1} via {provider.name} failed ({e}){more}")
    raise RuntimeError(f"image generation failed for scene {index + 1}: {last_error}")


def generate_images(plan: ShotPlan, out_dir: Path, backend: str | None = None,
                    work_dir: Path | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    primary = get_provider(backend)
    print(f"  images: backend = {primary.name}")
    if plan.characters:
        print("  images: character check (same description substituted in every scene):")
        for i, scene in enumerate(plan.scenes):
            if scene.compose:
                print(f"    scene {i}: (compose: {scene.compose.template}) — no image")
                continue
            chars = plan.characters_in(scene.media_prompt)
            print(f"    scene {i}: {', '.join(chars) if chars else '-'}")
    refs = character_refs(plan, primary, out_dir, work_dir=work_dir)
    paths = []
    for i in range(len(plan.scenes)):
        # Composition scenes are rendered by the compose stage (Remotion) straight
        # into video/scene_NN.mp4 — they have no generated image.
        if plan.scenes[i].compose:
            print(f"  images: scene {i + 1}/{len(plan.scenes)} skipped "
                  f"(compose: {plan.scenes[i].compose.template})")
            continue
        data, used = generate_scene_image(plan, i, primary,
                                          fallback=backend is None, char_refs=refs,
                                          work_dir=work_dir)
        path = out_dir / f"scene_{i:02d}.png"
        path.write_bytes(data)
        note = "" if used is primary else f" (fell back to {used.name})"
        print(f"  images: scene {i + 1}/{len(plan.scenes)}{note}")
        paths.append(path)
    return paths
