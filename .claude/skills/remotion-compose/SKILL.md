---
name: remotion-compose
description: The Remotion composition track (pipeline/compose/ + remotion/) — $0 text/motion cards rendered into the video slot the assembler prefers. Use when working on title cards, quote cards, lower thirds, outros, adding a new compose template, editing palettes/themes/fonts, or debugging the compose stage. Triggers include compose, Remotion, title_card, quote, lower_third, outro, template, MOOD_PALETTES, theme.ts, Root.tsx, npm run studio, composition.
---

# Remotion Compose Track (Stage 2.75)

Text/motion scenes — title cards, quotes, lower thirds, outros — rendered with React/Remotion instead of AI image generation. A compose scene renders straight into `output/<slug>/video/scene_NN.mp4`, **the same slot the FFmpeg assembler already prefers over a Ken Burns still**, so nothing downstream changes. Cost: $0 (local headless render). No image is generated and no animate credit is spent for these scenes.

## Pipeline position

```
plan → images → animate → voice → compose → assemble
```

It runs **after** voice on purpose: each card is sized to its narration mp3 (`ffprobe` duration + `BREATH = 0.3` — the same breath constant as `assemble.py`; keep them in sync). Scenes with no audio yet use `_DEFAULT_SECONDS` per template (title_card 4s, quote 6s, lower_third 4s, outro 4s).

- The `images` stage **skips** compose scenes entirely.
- Re-render a plan's compose scenes: `python -m pipeline.compose output/<slug>`.

## Declaring a compose scene

In `shot_plan.json`, set `compose` instead of `media_prompt` (`ComposeSpec` in `pipeline/schema.py`; a validator enforces exactly this either/or):

```json
{ "narration": "The two selves.",
  "compose": { "template": "title_card", "heading": "The Two Selves",
               "subheading": "a meditation on change" } }

{ "narration": "Yesterday I was clever...",
  "compose": { "template": "quote",
               "heading": "Yesterday I was clever, so I wanted to change the world.",
               "attribution": "Rumi" } }
```

| `template` | Fields | Composition id | Use for |
|---|---|---|---|
| `title_card` | `heading`, `subheading?` | `TitleCard` | Opening title |
| `quote` | `heading` (the quote), `attribution?` | `Quote` | Memorable line |
| `lower_third` | `heading` (name), `subheading?` (role) | `LowerThird` | Introduce a person/place/term |
| `outro` | `heading`, `subheading?` (CTA) | `Outro` | Closing card |

`attribution` is auto-prefixed with an em dash ("— Rumi") if missing. `subheading` is ignored for `quote`.

## Theming — the sync trap

Palettes are keyed by the plan's `music_mood` (calm / upbeat / dramatic / mysterious / inspiring; unknown moods fall back to inspiring). **`MOOD_PALETTES` is duplicated in two places and MUST stay in sync:**

- `pipeline/compose/__init__.py` (Python — passed as render props)
- `remotion/src/theme.ts` (TypeScript — studio preview defaults)

Each palette: `bg1`, `bg2`, `fg`, `accent`, `glow`. Editing a color or adding a mood means editing both files.

Typography is **Playfair Display**, baked deterministically via `@remotion/google-fonts` in `remotion/src/fonts.ts` — no render-time font flash. Output is 1920x1080 @ 30fps to match the assembler (`FPS = 30` in both `compose/__init__.py` and `assemble.py`).

## Adding a new template — checklist

1. **Schema**: add the template name to the allowed set in `ComposeSpec.check_template` (`pipeline/schema.py`) and document it in the `template` field description (the LLM reads these descriptions when planning).
2. **Component**: create `remotion/src/<Name>.tsx` (copy the closest existing card; they take `heading` / `subheading` / `palette` / `durationInFrames` props).
3. **Register**: add a `<Composition id="<Name>" ...>` in `remotion/src/Root.tsx`.
4. **Bridge**: in `pipeline/compose/__init__.py`, add entries to `_COMPOSITION_ID`, `_DEFAULT_SECONDS`, and a branch in `_props_for()` mapping spec fields → props.
5. **Docs**: extend the table in `remotion/README.md`.
6. **Verify**: `cd remotion && npm run studio` to preview live, then `python -m pipeline.compose output/<slug>` on a plan using the new template and confirm `video/scene_NN.mp4` appears and assembles.

## Setup & dev

```bash
cd remotion && npm install        # once (Node.js >= 18; FFmpeg already a pipeline dep)
npm run studio                    # live-preview/edit templates
```

For deep Remotion framework questions (hooks, springs, sequences, render CLI), that's generic Remotion knowledge — this skill covers how the track integrates with THIS pipeline.
