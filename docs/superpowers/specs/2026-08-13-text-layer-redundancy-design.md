# One Text Layer Per Phrase

**Date:** 2026-08-13
**Status:** Approved, ready for implementation planning

## Problem

Three renderers can put words on the same frame at the same moment:

| Layer | Renderer | Position | Source |
|---|---|---|---|
| Overlay | ffmpeg `drawtext` (`_overlay_filter`, `assemble.py:62`) | top | `Scene.on_screen_text` |
| Card | Remotion, rendered into `video/scene_NN.mp4` | full frame | `Scene.compose` |
| Subtitles | libass `subtitles` (`_subtitle_filter`, `assemble.py:154`) | bottom | the narration, via `.words.json` |

Nothing coordinates them. Because the subtitles *are* the narration, any overlay
or card that repeats a phrase from the narration prints the same words twice on
screen simultaneously — top and bottom, or centre and bottom.

Observed on a Dickinson poem test: a `quote` card showed the line while the
subtitles printed the same line underneath it.

## Findings

Measured across the 27 plans in `output/` (164 scenes):

**Scenes carrying both `compose` and `on_screen_text`: zero** across the 27
plans measured. The pairs that occur there are overlay-vs-subtitles (139 scenes)
and card-vs-subtitles (4 scenes).

> **Correction, added after implementation.** This finding was used to reject a
> "the card wins and the other layers stand down" rule as firing on nothing.
> It described the corpus accurately but did not generalise: the first plan
> generated after this work — `output/the-greedy-dog` — put
> `on_screen_text: 'A lesson learned.'` on its `quote` card scene, rendering
> bold sans above the card's Playfair. Whether the new `on_screen_text` field
> description made this more likely, or the old 27 plans simply never sampled
> it, is not established from one occurrence. Either way the case is real, so
> a card scene now suppresses the overlay unconditionally — see "the two call
> sites" below.

**Overlays repeat the narration constantly.** Of the 139 scenes with
`on_screen_text`, comparing its words against its own narration:

| Overlap | Scenes | Share |
|---|---:|---:|
| Words fully contained in the narration | 24 | 17% |
| Partial (40–90%) | 39 | 28% |
| Independent (<40%) | 76 | 55% |

**But repetition is not always a defect.** A word-containment rule suppresses 27
overlays, and the list is not uniform:

```
'ARGENTINA'        <- "Argentina — champions by destiny."
'Subscribe!'       <- "…Subscribe for more…"
'Timeless Wisdom'  <- "The professor shares timeless wisdom."
```

In the FIFA listicle the country name repeating the narration **is** the visual
design; `'Subscribe!'` is a deliberate call to action; only `'Timeless Wisdom'`
is lazy restatement. All three are structurally identical as strings. A string
comparison cannot distinguish a deliberate label from a lazy restatement, so any
rule aggressive enough to catch the third destroys the first two.

**Threshold tuning does not help.** Content-word containment at 70%, 80%, 90%
and 100% all suppress 27–28 scenes — a flat plateau. The distribution is
bimodal, so there is no threshold that separates labels from restatements.

**What actually predicts it is the video's format** — listicle overlays are
labels, story overlays are decoration — and that is not represented anywhere in
the data. `ShotPlan` has no format field, and `styles.py`'s `text` block carries
sizes only (`caption_size`, `overlay_size`), no policy.

**`on_screen_text` is under-specified.** Its entire guidance to the model is
`"Optional short overlay text (max ~6 words)."` (`schema.py:89-91`). Nothing
tells it the overlay should not echo the narration, which is why 45% of them do.

## Goal

Stop the same phrase rendering twice at once, without deleting the overlays that
are doing real work.

## Non-goals

- **A `format` field on `ShotPlan`.** It is the theoretically correct fix, but it
  is a new field the LLM must invent on all three round trips, and it leaves 27
  existing plans un-typed. Rejected as too expensive for the defect's size.
- **Changing how any renderer styles text.** Fonts, sizes, colours and positions
  are untouched. This design changes only *whether* each layer runs.
- **Suppressing on paraphrase.** `'Meet the Professor'` against *"Meet our
  professor, a fountain of knowledge"* is redundant to a human and is
  deliberately left alone — catching it requires judgement the assembler does
  not have.

## Architecture

One predicate, two call sites, one field-description change.

```
scene i
  ├─ on_screen_text  ──scene has a compose card?─────> drop the drawtext overlay
  │                  └─_restates(text, narration)?──> drop the drawtext overlay
  ├─ compose.heading ──_restates(head, narration)?──> drop the subtitles
  └─ narration ─────────────────────────────────────> subtitles (unchanged)
```

The winner differs by case because the layers differ in kind. Subtitles are
word-timed and carry accessibility, so against a redundant overlay they stay. A
card is the scene's entire visual, so it wins against redundant subtitles — and
against any overlay at all, redundant or not, since a bold drawtext line over a
designed composition competes with the card's own typography.

## Component: the predicate

In `pipeline/assemble.py`:

```
_restates(text, narration) -> bool
  normalize both: lowercase, non-alphanumerics -> spaces, collapse whitespace
  False if text is empty or narration is empty
  False if text has fewer than 3 words
  False if text contains "subscribe"
  True  if the normalized text is a contiguous phrase within the normalized narration
```

Every clause is deliberately conservative:

- **Contiguous phrase, not word overlap.** Only a verbatim lift fires. Paraphrase
  never does.
- **The 3-word floor** is what protects the 27 deliberate labels. `ARGENTINA`,
  `FRANCE`, `Body Heart` and `It Stops!` are all under it. This single clause is
  the difference between the rule that works and the rule that guts the corpus.
- **The `subscribe` exemption** covers CTA copy, which repeats the narration on
  purpose. It is the only content-based exception, and it exists because the
  corpus contains two such scenes that the phrase test otherwise catches.

Measured effect on the 27 existing plans: **5 overlays suppressed**, 27 labels
untouched, and **1 of the 4 compose scenes** drops its subtitles — the `quote`
card in `the-journey-of-santiago` scene 3, whose heading *"The real treasure was
the journey itself."* is spoken verbatim by the narration. That scene is the
card-vs-subtitles collision occurring in the existing corpus, independent of the
Dickinson test that prompted this work.

## Component: the two call sites

Both are in `assemble()`'s per-scene loop, which already computes `overlay` and
`subs` per scene and already has `plan.scenes[i]` in hand:

- Where `overlay` is built from `plan.scenes[i].on_screen_text`, pass an empty
  overlay when `_restates(on_screen_text, narration)`.
- Where `subs` is built, pass an empty subtitle filter when the scene has a
  `compose` and `_restates(compose.heading, narration)`.

No template special-casing is needed for the card case. A `lower_third` heading
is a name or label — under 3 words, or not a verbatim lift — so it self-excludes.
A `quote` heading is the spoken line, so it fires, which is the observed
collision.

## Component: the field description

`Scene.on_screen_text`'s description becomes:

```
Optional short overlay text (max ~6 words). Must add something the narration
does not say — a label, a name, a number, or a question. Never repeat a phrase
from the narration.
```

This is the durable half: it stops new redundant overlays from being written.
Placing it on the field rather than in `SYSTEM` puts it in the structured-output
contract the model already reads, at no prompt-budget cost on the polish and
consistency-review round trips.

## Error handling

`_restates` returns `False` for empty text, empty narration, and a `compose`
with no heading. Suppression can never raise: the worst case is today's
behaviour, both layers rendering.

## Testing

- **Predicate table.** `True`: `"Everyone has a wave coming"` against its
  narration. `False`: `"ARGENTINA"` (under the floor), `"Subscribe for more!"`
  (exempt), `"Meet the Professor"` (paraphrase, not a lift), `"Why is the Sky
  Blue?"` (adds `why`), empty text, empty narration.
- **Corpus regression.** Assert the suppression set over `output/*/shot_plan.json`
  is exactly the 5 expected scenes. A future loosening of the rule then shows up
  as a failing test rather than as 27 silently deleted labels. The test skips if
  `output/` is absent, so it does not fail on a fresh clone.
- **Call sites.** A scene with a redundant overlay produces a filter chain
  containing no `drawtext`; a scene with a redundant card heading produces one
  containing no `subtitles`; a scene with an independent overlay produces both.

## Success criteria

1. A `quote` card scene whose narration speaks the quote renders the card with
   no subtitles underneath it.
2. An overlay that lifts a phrase from its narration does not render.
3. `ARGENTINA`, `Subscribe!` and every other short label still renders.
4. New plans stop writing overlays that restate the narration.
