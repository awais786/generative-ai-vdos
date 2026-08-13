# CLAUDE.md

> **MANDATORY — producing a video?** If the user asks you to make, create, or
> produce a video, you MUST read [`AGENT_GUIDE.md`](AGENT_GUIDE.md) before taking
> any action, including before running any pipeline command. It contains the
> preflight step, the review gates, the money rules, and the full stage list —
> none of which are repeated in this file. Skipping it WILL cause you to miss
> stages and spend money without approval.
>
> This file covers working *on* the codebase. `AGENT_GUIDE.md` covers *running* it.

AI video pipeline: rough text idea → shot plan JSON → AI images → optional animation →
TTS voiceover → FFmpeg assembly → `output/<name>/final.mp4`. See README.md for the full
user guide; this file covers what an agent needs to work on the codebase safely.

## Skills (read the matching one before touching a stage)

Project skills in `.claude/skills/` carry the deep, per-stage how-to knowledge and gotchas.
This file is the safety overview; the skills are the manual. **If there's even a 1% chance a
skill applies to what you're doing, invoke it.**

| Skill | Use when working on |
|---|---|
| `shot-plan` | `shot_plan.json`, characters/placeholders, negatives, outfits, `animate`, compose scenes, style presets |
| `image-backends` | `pipeline/images/` — adding a provider, fallback/priority, character reference edits, qwen/gpt-image quirks |
| `voiceover-tts` | `pipeline/voiceover.py` — edge-tts, voices, WordBoundary timings, missing-audio/caption debugging |
| `remotion-compose` | the compose track — title/quote/lower-third/outro cards, templates, palettes, `remotion/src/` |
| `ffmpeg-assembly` | `pipeline/assemble.py` — Ken Burns, captions/subtitles, overlays, music mix, timing, failed renders |

Those cover *changing* a stage. The stage-director skills — `plan-director`,
`images-director`, `voiceover-director`, `compose-director`, `assemble-director`,
and `creative-intake` before them — cover *running* one; `AGENT_GUIDE.md` routes to those.

(The web app has its own skill rules — see "Webapp development rules" below.)

## Commands

```bash
uv sync                                    # install/update deps (creates .venv at repo root)
source .venv/bin/activate                  # activate venv (or prefix commands with `uv run`)
python -m pipeline.refine "idea"           # plan + auto-polish (stage 1, ~$0.001)
python -m pipeline.refine --change "..."   # revise latest plan
python -m pipeline.images                  # stage 2 (qwen; ~$0.025/image after the trial quota)
python -m pipeline.video                   # stage 2.5 — DISABLED by default (costs money) — uncomment pipeline/video/__main__.py to re-enable
python -m pipeline.voiceover               # stage 3 (free)
python -m pipeline.compose                 # stage 3.5 (free, Remotion; no-op if no compose scenes)
python -m pipeline.assemble [--music f]    # stage 4 (free, local ffmpeg)
python -m pipeline.auto "idea"             # all stages, gate pre-approved (= pipeline.run --approve)
```

All stage commands default to the most recently touched `output/*/` folder
(`latest_work_dir()` in `pipeline/run.py`); pass a folder to target an older video.
`python -m pipeline.run "topic" --approve --animate` is the one-shot path with
resumable `state.json`.

Pipeline tests live in `tests/` (7 modules — expand, styles, animate flag,
image provider selection, video batch, voiceover helpers, pipeline isolation);
run with `python -m pytest tests/` or `python -m tests.test_expand` for the
character-substitution module alone. Backend tests (22 modules covering the
state machine, storage, signed URLs, API isolation, and every Celery stage)
run with `(cd backend && python manage.py test apps)`. Verify pipeline changes against
`examples/the-sharing-berry/` with `--backend placeholder` (free, no keys needed).

## Money rules

These stay here in full, not behind a pointer: this file auto-loads and
`AGENT_GUIDE.md` does not, so an agent doing a codebase task sees only what is
written below.

- **Never run `pipeline.video` (Wan animation) without the user asking** — it spends
  the limited free credit (~1,650s per account, ~5s/scene). Same for adding paid
  backends to a run.
- **gpt-image-1 is never auto-selected** — requires explicit `--backend gpt-image-1`.
  Qwen is the default first-choice image backend, but it is no longer free
  (~$0.025/image after the trial quota) — announce its cost like any other.
- **`flux-schnell` bills past its free tier** (~$0.003/image) and *is* auto-pickable
  and reachable through the per-scene fallback chain — so a run announced as free
  can spend there if `REPLICATE_API_TOKEN` is set.
- Plans via `gpt-4o-mini` are effectively free (~$0.001). Images are NOT: qwen's
  free developer quota ended April 2026 and it now bills ~$0.025/image, above
  gpt-image-1. Announce the cost before generating; still,
  show the user the plan/images at review gates before generating downstream assets.
- The user reviews artifacts between stages by preference: plan → images → the rest.

Two of these are enforced in code, and both are load-bearing — do not "clean them up":
`pipeline/video/__main__.py` is commented out so the CLI animation stage cannot run,
and `AUTO_EXCLUDE` in `pipeline/images/__init__.py` keeps `gpt-image-1` out of
auto-pick and out of the fallback chain. The rest are honoured only by whoever reads
this. `python -m pipeline.registry` reports what is actually configured; the
announce/approve protocol is in [`AGENT_GUIDE.md`](AGENT_GUIDE.md).

## Architecture in 30 seconds

- `pipeline/schema.py` is the contract: `ShotPlan`/`Scene`/`Character`. Stages
  communicate ONLY via `shot_plan.json` + files in the work dir
  (`images/scene_NN.png`, `video/scene_NN.mp4`, `audio/scene_NN.mp3` + `.words.json`).
- Image/video backends are provider plugins: subclass the base in
  `pipeline/images/base.py` or `pipeline/video/base.py`, append an instance to
  `PROVIDERS` in the package `__init__.py`. Order = auto-pick priority; per-scene
  fallback chain ends at the always-available placeholder.
- Scene durations come from measuring the voiceover mp3s in `assemble.py` —
  never from the plan.
- `.env` at repo root auto-loads (`pipeline/env.py`); empty values are ignored.
  Keys: `OPENAI_API_KEY`, `DASHSCOPE_API_KEY` (+ optional `DASHSCOPE_API_URL`
  workspace endpoint), see `.env.example`. Never commit `.env`.

## Hard-won gotchas (do not re-litigate)

- **Character consistency is enforced by code, not the LLM.** LLMs cannot repeat
  descriptions verbatim across scenes — that's why `characters` + `{name}`
  placeholders + `ShotPlan.expand()` exist. Never put a character's look inline in a
  scene prompt; never put pose/emotion in a character description.
- **Character.negative is auto-merged** — bald character, white-haired character,
  clean-shaven character all need their `negative` field set; the pipeline merges it
  into every scene automatically. Never rely on `scene.negative_prompt` alone for
  persistent per-character traits.
- **global_negative goes on ShotPlan, not per-scene** — video-wide rules (no women
  in a male video, no extra limbs, no watermarks) belong in `global_negative`. It is
  merged into every scene in the video.
- **Image models draw negated words** ("no beard" → beard). Unwanted traits go in
  `scene.negative_prompt`, `Character.negative`, or `global_negative` as appropriate.
  If qwen still refuses (strong priors), regenerate that one scene with
  `--backend gpt-image-1` — it follows instructions much better.
- **Animation is disabled** (`pipeline/video/__main__.py` is commented out). Never
  uncomment without the user explicitly asking — it spends DashScope credit.
- **Auto-polish and consistency_review run automatically** on every new plan in both
  `refine.py` and `run.py`. Do not add manual `--polish` calls in scripts.
- **Provider order: Qwen first, then Flux, then Pexels, then placeholder;
  gpt-image-1 and gemini-image LAST.** The paid ones are reachable only via an
  explicit `--backend` (never `IMAGE_BACKEND`). **This order no longer tracks
  real cost** and is kept because changing pipeline defaults is a money-policy
  decision for the user, not a refactor: qwen's free developer quota ended
  April 2026 and it now bills ~$0.025/image, above gpt-image-1's ~$0.01-0.02,
  while Flux at ~$0.003 is the cheapest generator and sits second. Do not
  describe the auto-picked backend as free — quote the provider's `cost`
  string, which is the single source (see `pipeline/images/base.py`).
- Wan model/resolution/duration are **hardcoded constants** in `pipeline/video/wan.py`
  (wan2.2-i2v-flash, 720P, 5s) by user decision — don't make them env vars.
- macOS needs `ffmpeg-full` (plain Homebrew ffmpeg lacks libass → no `subtitles`
  filter). ffmpeg path args must be absolute (`.resolve()`) when `cwd=work_dir`.
- edge-tts needs `boundary="WordBoundary"` to emit word timestamps (captions
  depend on them).
- Subscribe/CTA scenes are only for listicle-style videos — story/dialogue videos
  end on the story's final beat (enforced in the system prompt).
- Browser automation of AI web UIs (AI Studio, Flow, etc.) was proposed and
  rejected — API-only integrations.

## Secrets — never commit keys (enforced)

- **Real keys live only in `.env`** (gitignored): `OPENAI_API_KEY`, `DASHSCOPE_API_KEY`,
  `DASHSCOPE_API_URL`, `LITELLM_API_KEY`, `GOOGLE_API_KEY`, and the web app's `COGNITO_*`.
  Never paste a real key into chat, code, docs, or a commit — only `.env`.
- **`.env.example` is the only committed env file** — keys present, values empty.
- A **pre-commit hook** (`scripts/git-hooks/pre-commit`, zero-deps) blocks commits that
  add secret-looking files (`.env`, `*.pem`, `*.key`, `id_rsa`, …) or content (PEM
  blocks, `sk-…`, `AKIA…`, `AIza…`, known `*_API_KEY=<real value>`). It scans only
  **staged additions**. Activate it once per clone:
  ```bash
  git config core.hooksPath scripts/git-hooks
  ```
- If it false-positives, fix the value/filename; `--no-verify` is a last resort, not a habit.

## Web app (Django + Next.js)

```bash
make migrate       # run Django DB migrations (run once after clone or new migration)
make backend       # Django dev server on :8000
make frontend      # Next.js dev server on :3000 (separate terminal)
make test          # Django test suite (discovers apps/*/tests/) + pipeline tests
```

Settings are split by environment (`backend/config/settings/`):
- `base.py` — shared config
- `development.py` — DEBUG=True, COGNITO validation, `CORS_ALLOWED_ORIGINS=localhost:3000`
- `production.py` — secure cookies, HSTS, HTTPS redirect
- `deployment.py` — production overrides loaded from env vars (DATABASE_URL, S3, etc.)
- `test.py` — dummy COGNITO values so tests run without real credentials

`manage.py` auto-selects `test` settings when running `python manage.py test`, `development` otherwise. Production requires `DJANGO_SETTINGS_MODULE=config.settings.production` set explicitly (wsgi/asgi do this).

### Backend layout

```
backend/
  config/settings/       # split settings (base / development / production / deployment / test)
  apps/
    accounts/            # Cognito OAuth: login → callback → session; UserProfile model
      cognito.py         # build_authorize_url, exchange_code, decode_id_token
      services.py        # CognitoService.get_or_create_profile(claims)
      serializers.py     # UserProfileSerializer
    projects/            # Project / Scene / JobLog / LLMModel models + REST API
      services.py        # ProjectService.create, budget enforcement, _eager_thread, dispatch helpers
      serializers.py     # ProjectSerializer, SceneSerializer, JobLogSerializer, LLMModelSerializer
      views.py           # ProjectViewSet, SceneViewSet, LLMModelViewSet (all scoped by session cognito_sub)
    health/              # GET /api/health/
    core/                # TimestampMixin (abstract base for all models); moderation helpers
    storage/             # StorageProvider facade (upload/url over FileSystem/S3 backends)
```

### Auth flow

```
GET  /api/auth/login      → redirect to Cognito hosted UI
GET  /api/auth/callback   → exchange code → decode id_token → get_or_create UserProfile
                            → store cognito_sub + tokens in session → redirect to /home
GET  /api/auth/me         → return UserProfile for session user (401 if not logged in)
GET|POST /api/auth/logout → django_logout + redirect to Cognito logout
```

### Frontend layout

```
webapp/
  middleware.ts              # fast cookie-presence check; unauthed → /login; authed on /login → /home
  app/
    layout.tsx               # HTML shell only (fonts, globals.css)
    page.tsx                 # / → redirect to /home
    login/
      page.tsx               # public login page (LoginScreen component)
    (home)/                  # route group — invisible to URL
      layout.tsx             # async Server Component: calls getUser(), redirects to /login on 401
      home/
        page.tsx             # /home — welcome banner, create video section, project list
  components/
    home/welcome.tsx         # async Server Component — calls getUser() (deduplicated via React.cache)
    header.tsx               # 'use client' — receives email/name as props from (home)/layout
    login-screen.tsx         # static login card with href to /api/auth/login
  lib/
    auth-server.ts           # getUser() wrapped in React.cache(); single fetch per request
```

**Auth is server-side.** `(home)/layout.tsx` calls `getUser()` on every navigation, which fetches
`http://localhost:8000/api/auth/me` forwarding the `sessionid` cookie. `React.cache()` deduplicates
within a single render pass (layout + page both calling `getUser()` = one network request).
No client-side `AuthGuard`, no `UserContext`, no `useUser()`.

### Webapp development rules

- **If you think there is even a 1% chance a skill might apply to what you are doing, you ABSOLUTELY MUST invoke the skill.**
- **If the user's prompts require you to change something in the backend, use the `django-patterns` skill, if it's available.**
- **If the user's prompts require you to change something in the frontend, use the `vercel-react-best-practices` and `frontend-design:frontend-design`
skills, if they're available.**

### Web app gotchas

- **UserProfile is the FK anchor** — `cognito_sub` (Cognito's immutable user ID) links Cognito identity to all Django data. Never use email as a key; it can change.
- **`decode_id_token` is unverified** — we trust the token because we fetched it server-side directly from Cognito's token endpoint over HTTPS. Full JWKS verification would be needed if clients ever send Bearer tokens directly.
- **`CognitoService.get_or_create_profile` also syncs** — if a user updates their email/name in Cognito, the next login updates the local `UserProfile`.
- **Tests use `config.settings.test`** — dummy COGNITO values are set there. Per-test Cognito overrides use `with self.settings(COGNITO=FAKE_COGNITO)`.
- **Tests are co-located** — `apps/accounts/tests/`, `apps/projects/tests/`, `apps/health/tests/`. Run all with `(cd backend && python manage.py test apps)`.
- **`FRONTEND_URL` env var** — set this to your frontend origin (default `http://localhost:3000`); the backend callback appends `/home`.
- **Logout accepts GET and POST** — GET so a browser link works directly; POST for programmatic calls.
- **`sessionid` cookie is opaque** — just a session key; actual user data (tokens, sub) lives in Django's session store server-side. Next.js server-side fetch to `/api/auth/me` is the only way to get user data.
- **`/api/*` rewrites are browser-only** — `next.config.mjs` rewrites proxy browser requests to Django. Server-side fetches in Server Components must use the full `http://localhost:8000` URL directly.

## Conventions

- Python 3.13+ (use `X | None` union syntax, `match` statements, etc. freely).
- Stage CLIs live in each module (`main()` + `__main__.py` for packages); keep new
  stages consistent with that pattern.
- `output/`, `music/`, `.env`, `.venv` are gitignored — never force-add them.
- CC-BY music in `music/` requires attribution (see `music/ATTRIBUTION.txt`).
