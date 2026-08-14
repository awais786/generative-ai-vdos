---
name: scene-script
description: Writing the narration for each scene — length, the opening hook, pacing, and text that the TTS can actually speak. Use when writing or revising narration, when a finished video is much shorter than intended, when the voiceover mispronounces something, or when scenes feel rushed. Use before spending on images, since narration determines every scene's duration. Triggers include narration, script, scene text, voiceover text, video too short, sounds rushed, hook, opening line, pacing, TTS pronunciation.
---

# Writing a scene's narration

`narration` is the most consequential field in the plan and the easiest to
under-write. It sets the video's length — **scene durations are measured from
the voiceover mp3s at assembly, never from the plan** — it becomes the burned-in
captions verbatim, and it is the only thing a viewer actually hears.

`shot-plan` covers the plan's structure; `image-prompt` covers the picture.
This is about the words.

## Rule 1 — a scene is 12-20 words, not 10

Measured across 30 finished videos, 176 scenes:

| | words | spoken at ~150 wpm |
|---|---:|---|
| median | **10** | **4.0s** |
| shortest | 5 | 2.0s |
| longest | 24 | 9.6s |

The prompt asks for "roughly 4-8 seconds to speak aloud", and the median lands
**exactly on the floor**. Nearly every video is written at the thinnest end of
its own target, which is why videos finish around 28s when 60-90 was intended
and why `--seconds` felt unreliable.

**Aim for 12-20 words per scene.** Ten words is a caption; it is not a beat.

## Rule 2 — the first line is a hook, not a summary

The opening line is the only one that decides whether the rest is watched. The
corpus contains both kinds:

| | |
|---|---|
| **works** | *"Have you ever felt like you could get away with anything?"* |
| **works** | *"Did you know the sky isn't always blue?"* |
| weak | *"In every great classroom, wisdom thrives."* |
| weak | *"As the sun sets over the ocean, a man sits alone…"* |

The weak ones are *descriptions of a situation*. The strong ones put something
at stake in one sentence — a question, a claim that sounds wrong, a promise.
Scene-setting is what the image is for; do not spend the hook on it.

## Rule 3 — write for a voice, not a page

Every character reaches edge-tts and then, via word timings, the captions.

- **Spell out numbers.** *"over 70 of the top 100 crop species"* is read as bare
  digits and lands wrong; write *"seventy of the top hundred"*. Four scenes in
  the corpus have this.
- **Expand abbreviations.** "USA" → "the U S A" or "America".
- **Avoid `%`, `$`, `&`** — say "percent", "dollars", "and".
- **`...` and `—` do not create a pause.** Sixteen scenes use them expecting
  one. TTS mostly ignores them; the visible effect is a caption chunk that
  reads oddly. Write two sentences instead.
- **One idea per sentence.** Word timings chunk captions every four words, so a
  long clause becomes several caption cards with no natural break.

## Rule 4 — narration and picture must agree

The image model never sees the narration (`image-prompt` covers this from the
other side). If the narration says the crow is carrying meat, the prompt must
say so too. Read each pair back to back before generating.

## Rule 5 — end on the story's beat

Subscribe and call-to-action lines belong only in listicle-style videos. A story
or dialogue ends on its final beat, or on a `compose` card carrying the moral.
This is enforced in `script_agent`'s prompt; if a CTA appears in a story plan,
revise it out rather than leaving it.

## Before generating images

- [ ] every scene 12-20 words — not 8, not 30
- [ ] the first line is a hook, not scene-setting
- [ ] numbers, abbreviations and symbols written as spoken words
- [ ] no `...` or `—` standing in for a pause
- [ ] each narration matches its own `media_prompt`
- [ ] no CTA unless the video is a listicle

Revising is nearly free (`pipeline.refine <dir> --change "…"`, about $0.001).
Images are not. Every fix made here costs a fraction of one made after.
