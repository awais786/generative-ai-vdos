---
name: image-prompt
description: Writing the media_prompt for a scene — naming the subject, keeping prompts consistent with their narration, and excluding what the story is not about. Use when authoring or revising scene image prompts, when a generated image contains something the story never mentioned, when a subject is missing from an image, or when reviewing a plan before spending on images. Triggers include media_prompt, image prompt, scene prompt, wrong image, extra person appeared, missing subject, establishing shot, global_negative, invented content.
---

# Writing a scene's image prompt

`media_prompt` is what actually reaches the image model. `narration` does not —
the model never sees it. Every fact the picture needs must be in the prompt
itself, and every prompt is generated independently of its neighbours.

Read `shot-plan` for the plan's structure and `image-backends` for provider
behaviour. This file is about the prompt text.

## Rule 1 — every prompt names its subject

**The single most common defect, and it is invisible until you look at the
image.** A prompt that describes only a setting will be filled with whatever
subject the model thinks belongs there.

**Observed, *The Thirsty Crow*, scene 0:**

```
narration    : "On a hot day, a thirsty crow searched and searched for water."
media_prompt : "wide establishing shot of a sunny landscape with dry trees and
                a bright blue sky, warm sunlight illuminating the scene,
                cheerful and inviting atmosphere"
```

No crow. The model was asked for a children's-storybook landscape, and
children's-storybook landscapes have a child standing in them — so it drew a
girl in a red coat. The opening frame of a fable about a bird had no bird and
one human.

Fixed by putting the subject in:

```
"wide establishing shot of {crow} perched on a bare branch in a hot, dry open
 landscape, beak slightly open, looking tired and thirsty, parched golden
 grass, dry leafless trees, harsh midday sun, no water anywhere in sight"
```

**Check every scene: who or what is this picture *of*?** If the answer isn't in
the prompt, the model will invent one. "Establishing shot", "wide shot" and
"close-up of the setting" are where this hides — they sound like they justify
an empty frame, and they don't.

## Rule 2 — the prompt must not contradict its narration

The two are written together but consumed separately, so they drift. Read each
pair back to back and ask whether a viewer hearing the narration would accept
the picture.

In the same video, scene 1's narration is *"He spotted a tall pitcher"* — the
crow is present — while the prompt is a close-up of a pitcher alone, indoors, in
the corner of a room. The story is outdoors and the crow is looking at it. Not
wrong enough to regenerate, but it is the same failure one notch quieter.

## Rule 3 — say what the story is *not* about

Diffusion models condition toward every token you give them, and toward
whatever usually accompanies those tokens. What the story excludes is never in
the prompt, so it must be in `global_negative`.

- **No people in the cast?** `"people, human, boy, girl, child, man, woman,
  person, hands"`. `script_agent`'s prompt now sets this for animal- and
  object-only casts — verify it did.
- The same reasoning generalises: no modern objects in a historical scene, no
  second animal in a solo-animal fable, no text or signage anywhere.

Ask of every plan: **what would be obviously wrong if it appeared?** That list
belongs in `global_negative`, and nothing else in the pipeline supplies it.

## Rule 4 — recurring subjects are `{placeholders}`, never re-described

Covered fully in `shot-plan`, restated because it is the other half of Rule 1:
if the subject appears in more than one scene, it must be a character with a
`{placeholder}`. Describing "a black crow" inline in three scenes produces three
different crows — the model has no memory between calls.

## Before you spend

Read the whole plan's prompts in one pass and check:

- [ ] every `media_prompt` names its subject
- [ ] recurring subjects use `{placeholders}`, not inline descriptions
- [ ] no prompt contradicts its own narration
- [ ] `global_negative` excludes what the story is not about
- [ ] no negated words inside a prompt ("no beard" draws a beard)

Each item costs seconds here and an image regeneration afterwards.
