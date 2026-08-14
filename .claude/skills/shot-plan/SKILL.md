---
name: shot-plan
description: Authoring and editing shot_plan.json — the contract every pipeline stage consumes. Use when writing or revising a shot plan, fixing character consistency or wrong-looking characters, choosing negative prompts, deciding which scenes to animate, adding compose (title/quote) scenes, or picking a style preset. Triggers include shot plan, shot_plan.json, scene, character, placeholder, negative prompt, global_negative, outfit, style_prefix, animate flag, media_prompt, image_prompt.
---

# Shot Plan — the pipeline contract

`pipeline/schema.py` defines `ShotPlan` / `Scene` / `Character` / `ComposeSpec`. Stages communicate ONLY via `output/<slug>/shot_plan.json` plus files in the work dir — edit the JSON, re-run a stage, done. The LLM produces plans via structured output (`client.chat.completions.parse(..., response_format=ShotPlan)`), so a hand-edited plan must still validate against the schema.

## Character consistency is enforced by code, not the LLM

LLMs cannot repeat a description verbatim across 12 scenes — that's why the placeholder system exists:

- Define each recurring character once in `characters`, with a **full visual description**: age, hair, face, every clothing item with its color.
- In `media_prompt` and `motion`, reference characters **only by placeholder**: `{thief}` (bare `thief` also matches — word-boundary, case-insensitive — because LLMs forget the braces).
- `ShotPlan.expand()` substitutes the description deterministically at image/animation time.

Hard rules (violating these is the #1 cause of inconsistent characters):

- **Never** inline a character's look in a scene prompt — always the placeholder.
- **Never** put pose/emotion in a character description (it leaks into every scene); pose/emotion belongs in the scene's `media_prompt`.

### How expand() behaves (so prompts don't bloat)

- A character mentioned more than once in the same text gets the full description on the **first** mention only; later mentions collapse to "the <name>". Repeating a full description can make the model render the same person twice.
- With 3+ characters and the expanded text over `MAX_PROMPT_CHARS = 1000`, a compact pass keeps full descriptions for only the first two characters (by appearance order).
- `generate_scene_image()` additionally appends identity anchors: 2-character scenes get "Characters present: <first clause of each description>" (prevents both characters defaulting to the same gender); 3+ get "The scene must include all: …".

## Negatives — three levels, one generic rule

Diffusion models condition **toward** every token in the prompt — "no beard" puts *beard* in the conditioning and draws one. True negatives go in the negative-prompt channel, which conditions *away* from tokens. Never phrase a negative inside `media_prompt`.

| Level | Field | Use for |
|---|---|---|
| Character | `Character.negative` | Traits this character must NEVER have; auto-merged into every scene they appear in. Bald → `"hair"`, white-haired → `"dark hair, black hair"`, clean-shaven → `"beard, mustache"`. |
| Video | `ShotPlan.global_negative` | Video-wide rules regardless of who's in frame: `"text, watermark, extra limbs, blurry"`, "no women in a male-cast video", etc. |
| Scene | `Scene.negative_prompt` | One-off fixes for a single scene. |

All three merge automatically (`global_negative` + per-character + per-scene). Don't rely on `scene.negative_prompt` for a persistent character trait — you'll miss scenes.

### The absent thing nobody excluded

The hardest negatives are for things the prompt never mentions. An image model
does not draw only what you asked for — it fills the frame with whatever
usually accompanies it, and it is very good at knowing what that is.

**Observed:** *The Thirsty Crow*, storybook preset, cast of one crow. Scene
prompt: a crow beside a pitcher in a sunny garden. Two of the four images came
back with **a red-haired boy watching the crow** — because children's-storybook
illustrations of animals are full of children, and nothing in the prompt said
otherwise. `global_negative` was the generic
`"changing hairstyle, inconsistent clothing, different face, extra limbs, blurry"`,
none of which excludes a person.

So: **when the cast has no people in it, say so.** Add
`"people, human, boy, girl, child, man, woman, person, hands"` to
`global_negative`. `script_agent`'s prompt now instructs the model to do this
for animal- and object-only casts, but check it — the same reasoning applies to
any category the story excludes: no cars in a medieval scene, no modern
buildings in a historical one, no second animal in a solo-animal fable.

Ask of every plan: *what is this story definitely NOT about?* That answer
belongs in `global_negative`, and nothing else in the pipeline will supply it.

If qwen still draws the unwanted trait (strong priors), regenerate just that scene with `--backend gpt-image-1` — it follows instructions much better (explicit opt-in only; money rule in CLAUDE.md).

## Scene fields worth knowing

- `media_prompt` (alias `image_prompt`): concrete, cinematographer-style visual description. No text-rendering requests — `style_prefix` is prepended automatically.
- `compose`: renders the scene as a Remotion text/motion card instead of a generated image (see the `remotion-compose` skill). Templates: `title_card`, `quote`, `lower_third`, `outro`. When set, `media_prompt` and `animate` are ignored. A validator requires every scene to have `media_prompt` OR `compose`.
- `animate: true`: only when real motion is essential (flags waving, fighting/dancing/running, flowing water, crowds). Costs DashScope credit; `MAX_ANIMATED_SCENES = 2` is a hard cap — a validator **silently unsets** the flag beyond the first two animated scenes, so ordering matters.
- `motion`: optional motion description for the animate stage; default is gentle cinematic motion derived from `media_prompt`. Character placeholders work here too.
- `voice`: per-scene edge-tts voice override (dialogue, other languages, e.g. `ur-PK-UzmaNeural`). Default: the run-wide narrator.
- `on_screen_text`: short overlay (~6 words max), drawn top-center by the assembler.
- `reference_image`: local photo to build the scene on — needs an edit-capable backend (gpt-image-1).
- `outfit`: per-scene map of character name → outfit name from that character's `outfits` dict (alternate complete looks, each a full description). Unlisted characters use their default look.
- `Character.is_inanimate: true` for props/food/landmarks/vehicles — switches the character reference shot from portrait pose to product-style.

## Plan-level fields

- `title` (<70 chars, curiosity-driven), `description`, `tags` — YouTube metadata.
- `music_mood`: one of calm / upbeat / dramatic / mysterious / inspiring — drives both `pick_music()` folder choice and the compose track's palette.
- `style_prefix`: global image style prepended to every scene prompt.
- `scenes`: 8–15; durations come from the voiceover audio, never from the plan.
- Subscribe/CTA scenes are only for listicle-style videos — story/dialogue videos end on the story's final beat.

## Style presets

`pipeline/styles.py` has curated `PRESETS` (cinematic, anime, watercolor, …) that set `style_prefix` + `global_negative` + `music_mood` as a coherent trio. Prefer a preset over inventing a style ad hoc; keep the three fields consistent if you customize.

## Revising a plan

`python -m pipeline.refine --change "..."` revises the latest plan (auto-polish and consistency_review run automatically on every new plan — never add manual `--polish` calls). After hand-editing the JSON, downstream stages pick it up as-is; only re-run stages whose inputs changed (e.g. edited one scene's `media_prompt` → regenerate that image, keep the rest).

## Writing the narration itself

This file covers the plan's *structure*. For the words — how long a scene should
be, what makes an opening line work, and what the TTS mangles — read the
`scene-script` skill. Measured across 30 videos, the median scene is 10 words
(4.0s spoken), the exact floor of the prompt's own 4-8s target, which is why
finished videos run far shorter than intended.
