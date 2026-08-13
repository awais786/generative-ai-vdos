# Style Playbook — One Source for Every Visual Decision

**Date:** 2026-08-13
**Status:** Approved, ready for implementation planning

## Problem

A video's look is currently decided in four independent places, and nothing keeps
them in agreement:

| Decision | Where | Driven by |
|---|---|---|
| Image look | `pipeline/styles.py` `PRESETS` | `style_prefix` |
| Compose card colours | `pipeline/compose/__init__.py` `_palette_for` | `music_mood` |
| Captions | `pipeline/assemble.py:133` | hardcoded `FontSize=18,Bold=1,Outline=2,MarginV=40` |
| On-screen overlays | `pipeline/assemble.py:56` | hardcoded `fontsize=58, white, black@0.8 border` |

Both failure modes were reproduced while producing real videos:

- **Image ↔ card.** "Discovering The Alchemist" had `style_prefix: "cinematic
  photo, warm desert tones, soft golden hour light"` and `music_mood:
  "inspiring"`. The three generated scenes were warm gold; the closing quote card
  rendered dark purple (`bg1 #0f0b1e` → `bg2 #4a2f52`), because
  `_palette_for` looks the palette up by **music mood**. The soundtrack chose the
  paint.
- **Image ↔ image.** In "Why is the Sky Blue?", scene 0 came back a golden sunset
  with an uninvited person in frame while scene 1 was deep blue. `style_prefix` is
  a phrase the model re-interprets per scene, so neighbouring scenes drift.

## Goal

One style source. Images, compose cards, captions and overlays all derive their
look from it, so a video cannot silently change appearance partway through.

## Non-goals

- **User-authored style files.** OpenMontage's literal model is `styles/*.yaml`
  validated by a JSON Schema. That buys *authoring*, which is not the requirement
  here, and costs a new dependency (the project has none for YAML), a loader, a
  validator, and web-app selection UI. The design keeps the style object shaped so
  a YAML loader could be added in front of it later without changing consumers.
- **LLM-chosen palettes.** Letting the model pick colours per video is the
  opposite of a style guide: two videos in the same style would not match.
- **Typography systems, motion/pacing rules, chart palettes, quality rules.**
  All present in OpenMontage's schema, all dropped here. This repo discovers a
  single font at runtime (`_FONT`), has fixed Ken Burns timing, and renders no
  charts.

## Reference

OpenMontage (`/Users/awais.qureshi/Documents/devstack/OpenMontage`) solves this
with a *style playbook*: `styles/*.yaml` validated by
`schemas/styles/playbook.schema.json`. One document carries
`visual_language.color_palette` (concrete hex values), `typography`, `motion`,
`overlays`, `chart_palette`, and `asset_generation.consistency_anchors`. Every
renderer reads from it — image prompts via `image_prompt_prefix`, Remotion via
`_build_theme_from_playbook`, HTML via `hyperframes_style_bridge`.

Two of its ideas are load-bearing and are adopted here:

1. **Concrete values, not adjectives.** A hex code can be handed to both an image
   prompt and a CSS variable. "Warm desert tones" cannot.
2. **The renderer reads values, not names.** Its
   `_build_theme_from_playbook` docstring states the rule directly: *"Instead of
   passing a playbook name and hoping Remotion has a matching preset, we read the
   playbook YAML and extract concrete colors."* The current `_palette_for` does
   precisely what that rejects — looks a name up in a preset table the image side
   never sees.

Notably, OpenMontage keeps `music_mood` **inside** the playbook's `audio:` block,
alongside `voice_style` and `music_volume`. It is a consequence of the style, not
a driver of visuals.

## Findings that shaped the design

Established by reading the code, not assumed:

1. **`PRESETS` is already a proto-playbook.** `pipeline/styles.py` maps a name to
   `{style_prefix, global_negative, music_mood}`. The shape is right; it stops
   before colours. Extending it is smaller and more idiomatic than adding a
   parallel system.
2. **Enforcement already exists.** `styles.py inject_style_instruction()` builds
   an LLM instruction block that pins style fields to exact values ("must be
   exactly: …").
3. **Remotion already accepts a palette by value.** `_props_for`
   (`pipeline/compose/__init__.py:81,88`) passes `"palette": palette` as a prop.
   The card renders whatever Python sends — only the *choice* is wrong. No
   TypeScript change is needed.
4. **The duplication has already caused a bug.** `remotion/src/theme.ts:24`
   records that `DEFAULT_PALETTE` "was a hand-copied literal that had already
   drifted from `MOOD_PALETTES.inspiring`."
5. **No YAML dependency exists** in `pyproject.toml`.
6. **`expand()` reserves prompt budget** for `style_prefix`
   (`pipeline/schema.py:229`: `budget -= len(self.style_prefix) + 2`) so the
   3-plus-character compaction pass triggers at the right threshold.
7. **`ShotPlan` is the LLM's structured-output contract.** `_parse_with_llm`
   (`pipeline/script_agent.py:265`) passes `output_format=ShotPlan`, and both
   `polish_image_prompts` and `consistency_review` return a fresh plan parsed from
   the model. Any field added to `ShotPlan` is therefore a field the LLM is asked
   to produce, on all three round trips per run. This ruled out the obvious design
   of hanging style fields off the plan.

## Architecture

One source, resolved once, stored in the work dir.

```
pipeline/styles.py  PRESETS["cinematic"]          ← the style guide
        │
        │  resolve_style()  +  inject_style_instruction()   [both exist today]
        ▼
work_dir/style.json  {name, palette{}, consistency_anchors[], text{}}
                     ← resolved values, beside shot_plan.json
        │
        ├──> images     : style_prefix + consistency_anchors → every scene prompt
        ├──> compose    : palette → Remotion props (already wired)
        ├──> assemble   : text + palette → subtitles force_style
        └──> assemble   : text + palette → drawtext overlay
```

**The work dir stores resolved values, not a style name.** Consequences:

- A video re-renders identically even if `PRESETS` later changes.
- A user may hand-edit `style.json` for one video. Per `plan-director`, rendering
  hints are editable directly; only narrative content requires `--change`.
- `music_mood` remains a field but stops steering colour, matching OpenMontage's
  treatment of it as an audio property.

## The style object

Written to **`work_dir/style.json`**, a sidecar beside `shot_plan.json`.
`ShotPlan` is not modified.

```json
{
  "name": "cinematic",
  "palette": {"bg1": "…", "bg2": "…", "fg": "…", "accent": "…", "glow": "…"},
  "consistency_anchors": ["same colour grade across every scene", "…"],
  "text": {"caption_size": 18, "caption_outline": 2,
           "overlay_size": 58, "overlay_border": 3}
}
```

**Why a sidecar rather than fields on `ShotPlan`** (finding 7): `_parse_with_llm`
passes `output_format=ShotPlan`, so the plan schema *is* the LLM's
structured-output contract. Adding style fields there would make the model
generate hex codes on every generate, polish and review call — three round trips
per run — and any value it invented would have to be discarded. Keeping style out
of `ShotPlan` is the only way to make "the LLM never authors style values"
actually true.

The work dir already holds several artifact types side by side (`images/`,
`audio/`, `video/`, `shot_plan.json`); `style.json` is one more. The video remains
fully self-describing — across two files rather than one.

**Palette reuses `MOOD_PALETTES`' exact key names.** This keeps the Remotion props
contract unchanged and makes `theme.ts`'s table fallback-only, reducing the drift
hazard finding 4 documents.

**Colours live only in `palette`.** `text` carries sizes and border widths; the
colours it needs are read from `palette` (`fg` for caption and overlay text,
`bg1` for the overlay's border). Captions and overlays therefore cannot disagree
with the cards.

**`consistency_anchors`** are short positive invariants injected into every image
prompt — the counterpart to `global_negative`. Example for `cinematic`:
`["same colour grade across every scene", "same time of day and lighting
direction"]`.

**Honest limitation, raised in review.** The anchors are a weaker instrument than
the palette. The palette fixes image↔card drift *by value* — the card is painted
with the same hex code the images were graded toward, so it cannot disagree. The
anchors address image↔image drift with *more adjectives*, generated independently
per scene with no cross-scene conditioning. That is the same category of
instrument this spec criticises `style_prefix` for being; it is more insistent,
not different in kind. Expect it to reduce drift, not eliminate it.

The mechanism that genuinely pins scene-to-scene appearance is the existing
reference-image path (`character_refs()` → `provider.edit()`), which conditions
each scene on a rendered image rather than on words. It currently fires only for
characters, on providers implementing `edit()`. Extending it to a per-video
"look reference" is the real fix for image↔image drift and is deliberately out of
scope here — this spec's guaranteed win is image↔card↔caption↔overlay.

## Consumer changes

| File | Change |
|---|---|
| `pipeline/styles.py` | Add `palette` / `consistency_anchors` / `text` to each preset; add `load_style(work_dir)` and `save_style(work_dir, preset)` |
| `pipeline/refine.py` | After `refine_plan()` completes, `save_style(work_dir, resolved_preset)` |
| `pipeline/run.py` | Same, at the equivalent point in the one-shot path |
| `pipeline/images/__init__.py` | Load style; append `consistency_anchors` after `style_prefix` when building each scene prompt. `work_dir` must be threaded through `generate_images()` as well as `generate_scene_image()` — `generate_images()` is what every real run calls, so anchoring only the latter leaves the feature inert |
| `pipeline/compose/__init__.py` | `_palette_for` returns `style["palette"] or MOOD_PALETTES.get(mood, _DEFAULT_PALETTE)` |
| `pipeline/assemble.py` | `_subtitle_filter` and `_overlay_filter` take values from the style, keeping today's literals as defaults |

`pipeline/schema.py` is **not** modified.

### Write after refinement, not before

`refine_plan()` calls `polish_image_prompts()` and `consistency_review()`, each of
which returns a *fresh* `ShotPlan` parsed from LLM output. Anything written before
that sequence would be discarded. `save_style()` therefore runs after
`refine_plan()` returns. Because style lives in its own file this is only an
ordering preference rather than a correctness trap — but writing it first would
still leave a window where the style file describes a plan that no longer exists.

### Prompt budget

`expand(include_style_overhead=True)` reserves `len(style_prefix) + 2`
(`pipeline/schema.py:228`). Anchors are appended at the same call sites, so the
reservation must grow by their length. Since `ShotPlan` does not carry the
anchors, `expand()` gains an optional `extra_overhead: int = 0` parameter that the
image stage passes. Missing this makes 3-plus-character scenes stop compacting at
the correct threshold and silently truncate — a quality regression with no error.

### The LLM never authors style values

Because style is not part of `ShotPlan`, it never appears in the
structured-output schema, so the model is never asked for it on any of the three
LLM round trips. `inject_style_instruction()` is unchanged and continues to pin
the fields the LLM does control (`style_prefix`, `global_negative`,
`music_mood`).

> **Correction, added after implementation and a code review.** This section and
> the "`pipeline/schema.py` is **not** modified" line above no longer describe
> the code. A `palette` field *was* added to `ShotPlan`, and `style_for_plan()`
> persists the model's proposal when no preset is set — so on the default path
> (`pipeline.refine "idea"` with no `--style`) the model does author four hex
> values.
>
> The spec's reasoning still held for the part that mattered. Those invented
> colours were reaching `assemble.py` and filling every burned-in caption and
> overlay, where captions had previously been unconditionally white — one
> uncontrolled colour deciding the legibility of every video. That is now
> confined: `style_for_plan()` marks a model-authored style `source: "model"`,
> and `_burn_in_colour()` refuses any such palette, so burned-in text uses a
> preset's palette or white. The compose cards still use the proposal, which is
> the problem the sidecar was built to solve.

## Backward compatibility

Every new field is optional and defaults to `None`:

- Work dirs with no `style.json` fall back to `MOOD_PALETTES` and today's
  hardcoded caption/overlay literals — current behaviour exactly. Every existing
  `output/*/` folder continues to render, none of which has a `style.json`.
- Runs with no `--style` write no `style.json`.
- `MOOD_PALETTES` and `theme.ts` are retained as the fallback path, not deleted.

## Error handling

- A missing or unreadable `style.json` is not an error; consumers fall back.
- A preset missing any of the three new keys is valid; consumers fall back.
- A `palette` missing individual keys falls back per key, so a partial hand-edit
  cannot produce a black-on-black card.
- Anchors are appended after the scene description and counted against the
  prompt budget via `expand(extra_overhead=…)`, so character descriptions
  compact at the correct threshold instead of the prompt truncating. The shipped
  anchors are short (50–95 characters); no drop-if-too-long path is implemented,
  because a case where the anchors alone blow the budget would mean the scene
  description is already unusable.

## Testing

- `palette` from `style.json` reaches the Remotion props payload
- `consistency_anchors` appear in the expanded prompt for every image scene
- the budget reservation in `expand()` accounts for anchors
- captions and overlays use plan values, with today's literals as defaults
- a work dir with no `style.json` still renders via `MOOD_PALETTES` (backward compat)
- round trip: `--style cinematic` writes a `style.json` whose `palette` equals
  `PRESETS["cinematic"]["palette"]`
- `save_style()` runs after `refine_plan()`, not before
- a `palette` missing a key falls back for that key only

## Success criteria

1. A video generated with `--style cinematic` has compose cards, captions and
   overlays whose colours come from the same palette as its images.
2. Re-running the Alchemist plan produces a closing card in warm desert tones
   rather than purple.
3. Every existing `output/*/` folder renders unchanged, and viewing an existing
   plan never creates or overwrites its `style.json`.
4. No new dependency, no TypeScript change, no web-app change.
