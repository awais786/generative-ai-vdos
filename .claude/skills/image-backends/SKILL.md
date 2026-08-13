---
name: image-backends
description: The image provider plugin system (pipeline/images/) — adding a backend, provider priority and fallback, character reference portraits, and per-provider quirks. Use when adding or modifying an image provider, debugging why a scene image failed or fell back, working with character face consistency via reference edits, or integrating a new image API. Triggers include image backend, provider, PROVIDERS, ImageProvider, fallback, qwen, flux, pexels, gpt-image-1, placeholder, character reference, edit, IMAGE_BACKEND.
---

# Image Backends (Stage 2)

One image per scene via pluggable providers. Everything lives in `pipeline/images/`: `base.py` (the contract), `__init__.py` (selection + fallback + character refs), one module per provider.

## The provider contract

```python
class MyProvider(ImageProvider):
    name = "my-backend"          # what --backend / IMAGE_BACKEND matches
    requires = "MY_API_KEY"      # named in error messages when unconfigured

    def available(self) -> bool: ...   # credentials/deps present?
    def generate(self, prompt, query=None, negative=None, api_key=None,
                 model=None, on_preview_url=None) -> bytes: ...
```

- `generate()` returns a **1920x1080 PNG as bytes**, or **raises** to let the fallback chain try the next provider. Don't return placeholders on failure — raising IS the protocol.
- `query` is a short search string (used by stock-photo backends like Pexels); text-to-image backends ignore it.
- `on_preview_url`, if given, is called with the provider's raw CDN URL before download/conversion (the web app streams previews with it).
- Optionally implement `edit(prompt, refs, ...)` — presence of the method (checked via `hasattr`) opts the provider into reference-image workflows.

## Priority, aliases, money rule

`PROVIDERS` in `__init__.py` — **list order = auto-pick priority**:

```
QwenImageProvider()   # free — always first; also does reference-image editing
FluxProvider()        # free tier only
PexelsProvider()      # stock photos
PlaceholderProvider() # always available — gradient placeholders, terminates the chain
GptImageProvider()    # paid — NEVER auto-selected
```

- `ALIASES` maps friendly names (`openai`, `qwen`, `flux`, `stock`, …) to real provider ids for `--backend` / `IMAGE_BACKEND`.
- `AUTO_EXCLUDE = {"gpt-image-1"}`: the paid backend is **never auto-picked and never reachable via fallback** — only as an explicitly named backend. This is a money rule (CLAUDE.md); do not weaken it when touching selection code.

## Selection & fallback semantics

- **Auto** (no backend named): first `available()` provider not in `AUTO_EXCLUDE`. Per-scene failures (moderation block, no search results, network error) fall through the remaining available providers, ending at the always-available placeholder.
- **Explicit** (`--backend name`): fallback is disabled — failures are loud. An unconfigured explicit backend errors immediately with its `requires` hint.

The chain terminates because `PlaceholderProvider.available()` is always true — keep it in the list.

## Character consistency via reference edits

For providers with `edit()` (qwen-image, gpt-image-1), `character_refs()` renders **one clean reference portrait per character** into `output/<slug>/refs/<name>.png` (once; cached by file existence — delete the file to re-roll a character's look). Then single- and multi-character scenes are *edited from* those refs with "keep face/hair/clothing identical to the reference" instructions instead of generated from scratch.

Details that matter:

- `is_inanimate` characters get product-style ref shots (plain background, centered) instead of portrait poses.
- Multi-ref scenes map "reference image N is {name}" and cap at 3 refs.
- A failed ref portrait just omits that character — their scenes fall back to text-to-image. A failed edit falls back to text-to-image for that scene. Both are fail-soft by design.
- `scene.reference_image` (a user-supplied photo) needs an edit-capable backend; if the primary lacks `edit()`, the first available provider with it is used.

## Per-provider quirks

- **qwen-image** (`qwen_image.py`): generates 1664x928, then `fit_cover()` crops to exactly 1920x1080. `prompt_extend: false` is deliberate — DashScope's prompt rewriter kept adding rendered captions to images. Response URLs are temporary (24h) — always download immediately. Needs `DASHSCOPE_API_KEY` (+ optional `DASHSCOPE_API_URL` workspace endpoint).
- **gpt-image-1**: best instruction-following — the escape hatch when qwen ignores a negative. Explicit opt-in only.
- **placeholder**: renders labeled gradient frames locally; the free no-keys test path.

## Adding a new backend — checklist

1. Create `pipeline/images/<name>.py` with an `ImageProvider` subclass (contract above). Read keys from env (auto-loaded from `.env` via `pipeline/env.py`; empty values are ignored).
2. Return exactly 1920x1080 — reuse `fit_cover()` from `pipeline/images/util.py` if the API's native size differs.
3. Append an instance to `PROVIDERS` in `__init__.py` at the right priority slot (free before paid; **paid backends also go in `AUTO_EXCLUDE`** and sit last).
4. Add friendly names to `ALIASES` if the obvious user word differs from `name`.
5. Add the key to `.env.example` (key present, value empty — never commit a real key; the pre-commit hook will block it).
6. Test without spending: run stages against a copy of `examples/the-sharing-berry/` with `--backend placeholder`, then one real scene with `--backend <name>`.

The video providers (`pipeline/video/`) follow the same pattern with their own `base.py` — same checklist applies. Wan's model/resolution/duration are hardcoded constants (`wan2.2-i2v-flash`, 720P, 5s) by user decision; don't make them env vars.
