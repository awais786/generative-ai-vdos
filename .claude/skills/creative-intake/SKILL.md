---
name: creative-intake
description: Gathering what a video actually needs before generating a plan — purpose, audience, length, tone, and must-include content. Use when the user asks for a video with a bare topic and no brief, before running pipeline.refine. Triggers include make a video, create a video, video about, I want a video, produce a video, before planning, vague brief.
---

# Creative Intake

Do not start production on a vague brief. "Make me a video about X" does not say
who it is for, how long it should be, or what it should feel like — so the model
guesses, and the guess is only visible once seven scenes exist.

Ask first. It costs one exchange and changes the whole output.

## The five questions

Ask **one at a time**, starting with the biggest gap. Never present them as a
survey.

| Question | What it changes |
|---|---|
| **Purpose** — educate, sell, inspire, entertain? | the narration's register |
| **Audience** — who watches this? | vocabulary, and what can be assumed |
| **Length and platform** — how long, and where does it live? | `--seconds` |
| **Tone** — what should it feel like? | `--style <preset>` |
| **Must-include** — any fact, name, or quote that has to appear? | the brief |

Stop when you have enough to write a brief. You do not need all five.

## Skip what the user already told you

A detailed brief is summarised back in one sentence, not interrogated. If
someone says *"a 30-second cinematic Instagram clip about our new coffee
roaster"*, that is length, platform, tone and subject already answered — ask
only about audience and must-include, or just proceed.

Intake exists for vague input. It is not a toll booth on every request.

## Tone maps to a style preset

Pass `--style` so the video does not default to the model's house style. Every
existing plan in `output/` chose some variant of "cinematic photo, warm colors";
the presets below are the way out of that.

| The user says | Preset |
|---|---|
| tense, noir, crime, high contrast | `noir` |
| gentle, childlike, bedtime, whimsical | `storybook` |
| factual, journalistic, real-world | `documentary` |
| soft, painterly, dreamy | `watercolor` |
| anime, manga, cel-shaded | `anime` |
| retro, 8-bit, pixel, arcade | `retro-pixel` |
| cinematic, filmic, moody (the default register) | `cinematic` |

If nothing fits, pass no `--style` — the model writes its own `style_prefix`,
which is today's behaviour.

## Length maps to `--seconds`

The scene count is derived from it: roughly one scene per six seconds, clamped
to 2–12. The stage prints the resolved count before generating, so a mistyped
value is visible immediately rather than after seven images exist.

| The user says | Pass |
|---|---|
| a short/social clip, a Reel, a TikTok | `--seconds 15` to `--seconds 30` |
| a normal explainer | `--seconds 45` |
| a longer piece | `--seconds 60` or more |

Without `--seconds` the model targets its own idea of length, which across 26
finished videos landed at a median of 28 seconds regardless of intent.

## Then run the stage

Compose a **prose brief** — a short paragraph carrying the answers, not a
bulleted form — and hand it to stage 1:

    python -m pipeline.refine "<brief>" --style <preset> --seconds <n>

A worked example. The user said "a video about our coffee roaster", then
answered: to sell, for cafe owners, 30 seconds on Instagram, warm and
craft-focused, must mention single-origin Ethiopian beans.

    python -m pipeline.refine "A 30-second Instagram video selling our new
    coffee roaster to independent cafe owners. Warm, craft-focused tone —
    close-up texture, hands, steam. Must mention single-origin Ethiopian
    beans. End on the roaster itself, no subscribe CTA." \
      --style cinematic --seconds 30

Then continue with the plan stage's own review gate — showing the plan and
waiting for approval before generating images. Intake does not replace that
gate; it makes the plan worth reviewing.
