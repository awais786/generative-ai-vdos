# Web App — Lean MVP Spec

A thin web UI over the existing CLI pipeline. **Multi-user (AWS Cognito auth),
local media, no billing.** The goal is to drive the same prompt → plan → review →
generate flow from a browser instead of the terminal, with live progress — with each
user seeing only their own projects.

This supersedes `webapp-spec.md` (the full SaaS vision: Next.js, S3/CloudFront, RDS,
Stripe) **for what we build first**. That doc stays as the north star / upgrade path;
everything deferred here is captured in §10.

> **Decision log:** auth was initially out of scope ("single-user, no auth"), then
> changed to **multi-user accounts via AWS Cognito**. Media still lives on local disk
> (S3 deferred); billing still deferred. Frontend was originally Django templates + vanilla JS,
> then changed to **Next.js 14 (App Router)** — matching the full SaaS target from day one.

---

## 1. Scope

**In:**
- **Sign up / log in via AWS Cognito** (email+password and Google); each user sees and
  manages only their own projects.
- Submit an idea → get a shot plan (auto-polish + consistency review run automatically, same as the CLI).
- Review the plan in the browser and revise it **two ways**: (a) edit the plan fields
  directly, or (b) type a natural-language **refine instruction** ("make the mom
  younger", "add a scene at the harbor") that re-runs the LLM — the CLI's
  `refine --change`. Then approve.
- Generate assets (images → voiceover → FFmpeg assembly) with live progress.
- See **all scene images** in a gallery; **regenerate any single image, or all of
  them**, without redoing the rest of the pipeline.
- Watch/download the finished `final.mp4`.
- List past projects; open any to review or re-download.

**Out (for the MVP):**
- No billing/Stripe/quotas.
- No media in the cloud — `final.mp4`, images, audio stay on **local disk** (S3/CloudFront
  deferred). Auth is the one cloud dependency (AWS Cognito).
- Animation stays **off by default** (spends DashScope credit; opt-in only — see §7).

**Success criteria:** from a clean checkout (plus a configured Cognito user pool), a
developer can run four processes (Redis, Celery worker, Django API, Next.js dev server),
sign in, and produce the same `output/<owner>/<id>/final.mp4` the CLI produces — driven
entirely from the browser, with progress streamed live, isolated to the signed-in user.

---

## 2. Stack

| Layer        | Choice                                  | Notes |
|--------------|-----------------------------------------|-------|
| Backend lang | **Python 3.13** (repo standard)         | Django 5.2 + Celery + pipeline/ all share one uv-managed venv. |
| Frontend lang| **Node.js 20+ / TypeScript**            | Next.js 14 App Router. |
| API          | **Django 5.2** + **Django REST Framework** | Thin JSON API only — no Django templates. DRF serves `/api/`. |
| Auth         | **AWS Cognito** user pool               | Hosted UI / OAuth2; Django validates Cognito JWTs (JWKS). See §4a. |
| Async jobs   | **Celery 5.4** + **Redis**              | Redis is broker + result backend. |
| DB           | **SQLite**                              | Single file, zero setup. Holds projects + a thin user-profile row keyed by Cognito `sub`. |
| Frontend     | **Next.js 14** (App Router) + shadcn/ui + Tailwind | Proxies `/api/*` to Django via `next.config.js` rewrites. |
| Media        | Local filesystem, served by Django (dev) | Reuses the pipeline's `output/<owner>/<id>/` layout. |
| System dep   | `ffmpeg-full` (libass), edge-tts        | Same as the CLI today. |

**Python dependencies** — added as a `webapp` optional group in `pyproject.toml`
(`uv sync --extra webapp`): `Django>=5.2,<5.3`, `djangorestframework>=3.15`,
`celery>=5.4`, `redis>=5.0`, `python-jose[cryptography]` (Cognito JWT verification).

**Node dependencies** — `package.json` in `webapp/` (Next.js app root):
`next@14`, `react`, `react-dom`, `typescript`, `tailwindcss`, `shadcn/ui`.

---

## 3. Architecture

```
                  AWS Cognito (user pool, Hosted UI)
                        ▲ OAuth code ▼ JWT
Browser ──fetch──▶ Next.js 14 ──/api/* proxy──▶ Django DRF ──enqueue──▶ Redis ──▶ Celery worker
                   (App Router)                   │                                   │
                                                  │ reads/writes                      │ calls pipeline/ functions
                                                  │                                    ▼
                                                  └── SQLite (UserProfile/Project/ ◀── output/<owner>/<id>/ on disk
                                                        Scene/JobLog)                  (images, audio, final.mp4)
```

- **Next.js** serves all pages. All `/api/*` calls are proxied to Django via
  `next.config.js` rewrites — same origin for cookies, same routing shape as the
  full SaaS target (CloudFront routes `/api/*` to Django ALB).
- **Django** is a pure JSON API: Cognito OAuth callback, JWT verification, DB reads/writes,
  Celery enqueue, media serving. No templates.
- The **Celery worker** does all heavy lifting by calling the existing
  `pipeline/` modules as a **library** — no shelling out to `python -m pipeline.*`.
- Progress is persisted to `JobLog`; clients poll `GET /api/projects/{id}/logs/?after={pk}`
  (cursor-based) to tail events without a persistent connection.

**Reuse, don't rewrite:** the worker imports `pipeline.script_agent`, `pipeline.images`,
`pipeline.voiceover`, `pipeline.assemble`, `pipeline.schema`. The web layer adds
orchestration + persistence around them; the generation logic is unchanged. Provider
selection uses the **existing `.env` flags** (`LLM_PROVIDER`, `IMAGE_BACKEND`, etc.) —
explicit, no auto-detect.

---

## 4. Data models

Four tables. Identity comes from **AWS Cognito** (§4a); we store only a thin profile.

### UserProfile
A local mirror of the Cognito identity so projects have a stable FK and we can show a
name/email without calling Cognito on every request.
| Field | Type | Notes |
|-------|------|-------|
| `id` | int (pk) | |
| `cognito_sub` | char, unique, indexed | The Cognito user's `sub` claim — the real identity. |
| `email` | char | Mirrored from the token on first login. |
| `name` | char, blank | Display name. |
| `created_at` | datetime | First login (just-in-time provisioned). |

> On first authenticated request we **get-or-create** the profile from the verified
> JWT claims. (If using `mozilla-django-oidc`, this maps onto Django's `User` instead —
> either way it's keyed by `cognito_sub`.)

### Project
| Field          | Type                        | Notes |
|----------------|-----------------------------|-------|
| `id`           | UUID (pk)                   | Also the `output/<owner>/<id>/` folder name. |
| `owner`        | FK → UserProfile, indexed   | **Every project query filters by the signed-in user.** |
| `prompt`       | text                        | The raw idea the user typed. |
| `title`        | char, blank                 | Filled from the plan once generated. |
| `status`       | char (enum, see below)      | |
| `shot_plan`    | JSON, null                  | The full `ShotPlan` dict; editable during REVIEW. |
| `style`        | char (StylePreset enum)     | Visual style preset applied to image prompts. |
| `animate`      | bool, default False         | Opt-in animation; capped by `MAX_ANIMATED_SCENES`. |
| `narrator_voice`| char (NarratorVoice enum)  | edge-tts voice; default from `.env`. |
| `music`        | char (MusicMood enum), blank| Optional background music mood. |
| `plan_model`   | FK → LLMModel, null        | LLM used for the plan stage. |
| `image_model`  | FK → LLMModel, null        | Image backend used for generation. |
| `video_model`  | FK → LLMModel, null        | Video backend used for animation. |
| `final_video_path` | FileField, blank       | Stored final.mp4 via the configured storage backend. |
| `error`        | text, blank                 | Last failure message if `status=FAILED`. |
| `stale`        | bool, default False         | An image/voiceover changed since the last assemble — `final.mp4` is out of date until `reassemble/`. |
| `created_at` / `updated_at` | datetime       | |

### Scene
**Generation state only.** The plan content (narration, image_prompt, characters,
negatives) lives in `Project.shot_plan` — the single editable source of truth. A
Scene row exists per scene purely to track its media artifact, keyed by `index` into
the plan. This avoids a dual source of truth between the JSON and the rows.

| Field | Type | Notes |
|-------|------|-------|
| `project` | FK → Project | |
| `index` | int | Index into `shot_plan["scenes"]`; the scene's order. |
| `media_path` | FileField, blank | Image (PNG) or video (MP4) stored via configured storage backend. |
| `audio_path` | FileField, blank | Voiceover MP3. |
| `words_path` | FileField, blank | Word-boundary timestamps JSON for caption sync. |
| `media_status` | char (enum: PENDING/RUNNING/DONE/FAILED) | Tracks image/video generation. |
| `voice_status` | char (enum: PENDING/RUNNING/DONE/FAILED) | Tracks TTS generation. |
| `media_provider` | char, blank | Backend that produced the image/video (fallback chain may differ from request). |
| `preview_url` | char, blank | Ephemeral presigned URL cached for the frontend. |
| `animate` | bool, default False | Whether this scene should be animated to video. |
| `compose` | JSON, null | Remotion composition spec for text-card scenes. |
| `negative_prompt` | text, blank | Per-scene negative prompt merged with global/character negatives. |
| `on_screen_text` | char, blank | Text overlaid on the scene. |
| `voice` | char, blank | Per-scene voice override. |
| `media_prompt` | text, blank | Expanded image prompt after character substitution. |

> Rows are (re)created from `shot_plan` on **approve**, once the plan is final. Editing
> the plan during REVIEW touches only the JSON; no Scene rows exist yet (D1, §11).

### JobLog
| Field | Type | Notes |
|-------|------|-------|
| `project` | FK → Project | |
| `stage` | char | plan / images / voice / assemble. |
| `level` | char | info / warn / error. |
| `message` | text | Human-readable progress line. |
| `created_at` | datetime | |

**Project status enum:**
```
DRAFT → PLANNING → REVIEW → GENERATING ──(scenes exist)──→ IMAGE_REVIEW → VIDEO_GENERATING → DONE
                                       ↘ (no scenes)                                        ↗ FAILED
                                         DONE ←─────────────────────────────────────────────
```
- `GENERATING`: images are being produced
- `IMAGE_REVIEW`: user gate — voice + assembly held until `POST /approve-images/`
- `VIDEO_GENERATING`: video animation + voiceover + assembly running
- `FAILED` reachable from `PLANNING`, `GENERATING`, `IMAGE_REVIEW`, or `VIDEO_GENERATING`

### ERD

```
┌────────────────────────────┐
│ UserProfile                │  ← mirror of the AWS Cognito identity
│  id            int  (pk)   │
│  cognito_sub   char uniq   │
│  email / name  char        │
└────────────┬───────────────┘
             │ 1
             │ N  (owner)
┌────────────┴───────────────┐
│ Project                    │
│  id            uuid  (pk)  │
│  owner         fk →profile │  ← every query filtered by signed-in user
│  prompt        text        │
│  title         char        │
│  status        enum        │──── DRAFT→PLANNING→REVIEW→GENERATING→IMAGE_REVIEW→VIDEO_GENERATING→DONE (·→FAILED)
│  shot_plan     json  (null)│         ← single source of truth for plan content
│  style         char        │
│  animate       bool        │
│  narrator_voice char       │
│  music         char        │
│  plan_model    fk →LLMModel│
│  image_model   fk →LLMModel│
│  video_model   fk →LLMModel│
│  final_video_path FileField│
│  error         text        │
│  stale         bool        │         ← final.mp4 out of date vs current assets
│  created_at    datetime    │
│  updated_at    datetime    │
└────────────┬───────────────┘
             │ 1
       ┌─────┴───────┐
       │ N           │ N
┌──────┴──────────┐ ┌┴───────────────────┐
│ Scene           │ │ JobLog             │
│  project  fk    │ │  project  fk       │
│  index    int   │ │  stage    char     │
│  media_path     │ │  level    char     │
│  audio_path     │ │  message  text     │
│  words_path     │ │  created_at        │
│  media_status   │ └────────────────────┘
│  voice_status   │   append-only progress
│  media_provider │   (poll via /logs/)
│  preview_url    │
│  animate        │
└─────────────────┘
  media state only,
  index → shot_plan
  ["scenes"][index]
```

State transitions (who triggers them):

| From | Event | To |
|------|-------|----|
| — | `POST /projects/` | `PLANNING` |
| `PLANNING` | `run_plan_stage` succeeds | `REVIEW` |
| `PLANNING` | `run_plan_stage` raises | `FAILED` |
| `REVIEW` | `PATCH` (edit plan) | `REVIEW` (no transition) |
| `REVIEW` | `POST /approve/` | `GENERATING` |
| `GENERATING` | image chord completes (scenes exist) | `IMAGE_REVIEW` |
| `GENERATING` | assemble completes (no scenes) | `DONE` |
| `GENERATING` | any stage raises | `FAILED` |
| `IMAGE_REVIEW` | `POST /approve-images/` | `VIDEO_GENERATING` |
| `IMAGE_REVIEW` | any stage raises | `FAILED` |
| `VIDEO_GENERATING` | video + assemble completes | `DONE` |
| `VIDEO_GENERATING` | any stage raises | `FAILED` |
| `FAILED` | `POST /approve/` or `POST /retry/` | `GENERATING` |

---

## 4a. Authentication (AWS Cognito)

Identity is fully delegated to a **Cognito user pool** — Django never stores passwords.

**Flow (Authorization Code + Hosted UI, recommended):**
1. Unauthenticated request → redirect to the Cognito **Hosted UI** (`/login`) for the
   app client. Sign-up, email verification, password reset, and Google sign-in (a
   Cognito social IdP) are all handled there — *those screens are Cognito's*, so the
   mockup's login/signup pages are illustrative of the experience, not custom code.
2. Cognito redirects back to `/auth/callback?code=…`; Django exchanges the code for
   **ID + access + refresh tokens**.
3. Django stores the session (signed cookie) and **get-or-creates** the `UserProfile`
   from the verified ID-token claims (`sub`, `email`, `name`).
4. API calls are authorized by the session; DRF resolves `request.user` →
   `UserProfile`. Tokens are verified against the pool's **JWKS** (issuer + audience +
   expiry checked).

**Config (env, never committed):** `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID`,
`COGNITO_APP_CLIENT_SECRET`, `COGNITO_DOMAIN`, `COGNITO_REGION`, `OAUTH_REDIRECT_URI`.

**Endpoints:** `GET /auth/login` (→ Hosted UI), `GET /auth/callback` (code exchange),
`POST /auth/logout` (clear session + Cognito logout URL). `mozilla-django-oidc` can
provide all three; otherwise a thin custom view + `python-jose` for verification.

**Isolation:** every `/api/projects/...` view requires auth and filters
`owner=request.user`; a project belonging to another user returns **404** (not 403, so
ids aren't enumerable). Anonymous → **401**.

> **Local dev note:** Cognito is the one cloud dependency in the MVP. A dev still needs
> a (free-tier) user pool + app client configured; everything else runs locally.

---

## 5. API

DRF, JSON. **All endpoints below require an authenticated session** (§4a) and operate
only on the caller's own projects. Base path `/api/`.

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/projects/` | Create a project from `{prompt, image_model?, animate?, narrator_voice?}`; enqueues the plan task → `PLANNING`. |
| `GET`  | `/api/projects/` | List projects (id, title, status, created_at). |
| `GET`  | `/api/projects/{id}/` | Detail: project + scenes + recent JobLog. |
| `PATCH`| `/api/projects/{id}/` | Manually edit `shot_plan` (allowed only while `REVIEW`). |
| `POST` | `/api/projects/{id}/refine/` | Revise the plan via a natural-language instruction (LLM re-run); `REVIEW` only. |
| `DELETE`| `/api/projects/{id}/` | Delete row + `output/<owner>/<id>/` folder. |
| `POST` | `/api/projects/{id}/approve/` | Approve the plan → `GENERATING`; also retries a `FAILED` project. |
| `POST` | `/api/projects/{id}/retry/` | Retry a `FAILED` project from the first incomplete stage. |
| `POST` | `/api/projects/{id}/approve-images/` | Approve generated images → proceed to voice + assembly (`IMAGE_REVIEW` gate). |
| `POST` | `/api/projects/{id}/scenes/{index}/regenerate/` | Re-run one scene's image. |
| `POST` | `/api/projects/{id}/regenerate-images/` | Re-run **all** scene images. |
| `POST` | `/api/projects/{id}/scenes/{index}/revoice/` | Edit one scene's narration/voice and re-run its TTS. |
| `POST` | `/api/projects/{id}/regenerate-voiceovers/` | Re-run **all** scene voiceovers. |
| `POST` | `/api/projects/{id}/reassemble/` | Re-stitch `final.mp4` from current assets (clears `stale`). |
| `GET`  | `/api/projects/{id}/logs/?after={pk}` | Poll pipeline progress events (cursor-based). |
| `GET`  | `/api/projects/{id}/download/` | Serve `final.mp4` via storage backend. |
| `GET`  | `/api/projects/{id}/scenes/{index}/media-urls/` | Signed URL for scene image/video. |
| `GET`  | `/api/projects/{id}/scenes/{index}/audio-urls/` | Signed URL for scene audio. |
| `GET\|POST\|DELETE` | `/api/models/` | User-scoped LLM model registry (list / create / delete; no update). |

The review gate (`approve`) is the web equivalent of the CLI's plan→images review
gate. Generation never starts until the operator approves, matching the
review-first preference. (gpt-image-1 is never selected unless explicitly chosen;
Qwen free default — same money rules as the CLI.)

### Request / response shapes

**`POST /api/projects/`** — create + queue planning. Only `prompt` is required; the
rest fall back to the `.env` flags (D3).
```jsonc
// request
{ "prompt": "a lonely lighthouse keeper befriends a storm petrel",
  "image_model": "qwen-vl-max", // optional model_id; else global default
  "animate": false,              // optional; spends credit if true
  "narrator_voice": "en-US-AndrewNeural", // optional
  "music": "calm" }             // optional mood
// 201 response
{ "id": "9f1c…", "status": "PLANNING", "title": "",
  "created_at": "2026-06-14T10:00:00Z" }
```

**`GET /api/projects/{id}/`** — project detail; pair with `/logs/` polling for live updates.
```jsonc
{ "id": "9f1c…", "status": "REVIEW", "title": "The Keeper and the Petrel",
  "image_model": "qwen-vl-max", "animate": false,
  "shot_plan": { /* full ShotPlan dict — schema.py contract */ },
  "scenes": [
    { "index": 0, "media_status": "done",
      "media_path": "/media/…/images/scene_00.png", "media_provider": "qwen-image",
      "voice_status": "done" },
    { "index": 1, "media_status": "pending",
      "media_path": "", "media_provider": "",
      "voice_status": "pending" }
  ],
  "log": [ { "stage": "plan", "level": "info",
             "message": "consistency review passed",
             "created_at": "2026-06-14T10:00:42Z" } ],
  "error": "" }
```
Before approve, `scenes` is `[]` (no rows yet — D1); the plan is read from `shot_plan`.

**`PATCH /api/projects/{id}/`** — edit the plan while `REVIEW`. Body is a partial:
`{ "shot_plan": { … }, "image_model": "dall-e-3", "animate": true }`. Editing in any
other status → `409 Conflict`. Returns the updated detail object.

**`POST /api/projects/{id}/refine/`** — revise the plan with a natural-language
instruction. Wraps `script_agent.revise_shot_plan(plan, feedback)`. `REVIEW` only
(else `409`); enqueues `run_refine_stage` → status briefly `PLANNING`, back to
`REVIEW` with the updated `shot_plan`. Auto-polish + consistency review re-run, same
as a fresh plan.
```jsonc
// request
{ "instruction": "make the lighthouse keeper older and add a scene at the harbor" }
// 202
{ "status": "PLANNING" }
```
This is the LLM path; `PATCH` is the manual path. Both edit the same `shot_plan` and
are available throughout `REVIEW`.

**`POST /api/projects/{id}/approve/`** — no body. Builds `Scene` rows from the final
plan, enqueues the assets chord, → `GENERATING`. `202` with `{ "status": "GENERATING" }`.
Calling it from `REVIEW` or `FAILED` is valid (the latter is retry); any other
status → `409`.

**`POST /api/projects/{id}/scenes/{index}/regenerate/`** — re-run one image. Optional
`{ "image_model": "dall-e-3" }` to force a specific model for this scene only (explicit
opt-in to a paid model). `202`; the scene's `media_status` returns to `running`.
Poll `/logs/?after={pk}` for progress. Allowed in `REVIEW` and `DONE`.

**`POST /api/projects/{id}/regenerate-images/`** — re-run **all** scene images at once.
Optional `{ "image_model": "…" }` applies to every scene. Resets each scene's
`media_status` to `pending` and enqueues the image `group` only — voiceover is
untouched. `202`. Allowed in `DONE`/`FAILED`. Regenerating an image changes a source
asset, so it sets `stale=true`; `final.mp4` is unchanged until **`reassemble/`**.

**`POST /api/projects/{id}/scenes/{index}/revoice/`** — edit one scene's narration
and/or voice, then re-run its TTS. Updates `shot_plan["scenes"][index]` and re-runs
edge-tts for that scene only (regenerating the mp3 + word-timing json).
```jsonc
// request (both optional; omit narration to just change the voice)
{ "narration": "The keeper had not spoken to a soul in years.",
  "voice": "en-GB-RyanNeural" }
// 202
{ "status": "DONE", "stale": true }
```
Allowed in `DONE`/`FAILED`. Sets `stale=true` (scene durations come from the new
audio, so the video must be re-stitched). Editing narration *before* generation is
just a `PATCH` to the plan in `REVIEW` — no audio exists yet.

**`POST /api/projects/{id}/regenerate-voiceovers/`** — re-run **all** voiceovers.
Optional `{ "voice": "…" }` sets the narrator voice for every scene. `202`; sets
`stale=true`. Allowed in `DONE`/`FAILED`.

**`POST /api/projects/{id}/reassemble/`** — re-run only the FFmpeg assembly from the
current images + audio; refreshes `final.mp4` and clears `stale`. No body. `202`.
Allowed in `DONE`/`FAILED`.

**`GET /api/projects/{id}/logs/?after={pk}`** — cursor-based polling. Returns all
`JobLog` entries with `id > after` (omit `after` for the full history). Each entry:
```jsonc
{ "id": 42, "stage": "images", "level": "info",
  "message": "scene 3/12 done", "created_at": "2026-06-14T10:01:05Z" }
```
Poll this endpoint on a short interval; advance `after` to the last received `id`.
Stop polling when the project's `status` reaches a terminal value (`DONE`/`FAILED`).

**Errors** use DRF defaults: `401` (not signed in), `400` (validation), `404` (no such
project/scene **or not owned by the caller** — see §4a), `409` (action not allowed in
current status). Body: `{ "detail": "…" }`.

---

## 6. Celery tasks

Each task wraps an existing pipeline function and publishes progress.

| Task | Wraps | Emits |
|------|-------|-------|
| `run_plan_stage(project_id)` | `script_agent` (plan + auto-polish + consistency review) | `PLANNING` log lines; saves `shot_plan`; → `REVIEW`. |
| `run_refine_stage(project_id, instruction)` | `script_agent.revise_shot_plan(plan, instruction)` (+ re-run polish/review) | saves the revised `shot_plan`; → `REVIEW`. |
| `run_image_stage(project_id, scene_index)` | `pipeline.images.get_provider(...).generate(...)` | per-scene status; honors character refs / negatives via `ShotPlan.expand()`. |
| `run_voice_stage(project_id, scene_index=None)` | `pipeline.voiceover` | edge-tts + word timings; one scene when `scene_index` is set, else all. |
| `run_assemble_stage(project_id)` | `pipeline.assemble` | FFmpeg assembly → `final.mp4`; clears `stale`; → `DONE`. |

**Assets pipeline** (on approve): a Celery **chord** —
`group(run_image_stage for each scene) | run_voice_stage | run_assemble_stage`.
Images fan out in parallel; voice and assembly run once all images land.
(Animation, if enabled, inserts a capped video stage between images and voice — §7.)

**Regenerate / revoice / reassemble** reuse these same tasks with no chord tail:
one image → a single `run_image_stage`; all images → `group(run_image_stage …)`;
one/all voiceovers → `run_voice_stage(scene_index=…)` / `run_voice_stage()`;
re-stitch → `run_assemble_stage`. Each asset-changing task sets `stale=true`;
`run_assemble_stage` clears it. Iterating on visuals or audio never re-runs the LLM,
so it's cheap; the operator rebuilds the video once when satisfied.

All tasks wrap the body in try/except: on failure set `status=FAILED`, write an
error `JobLog`, publish a terminal SSE event. Scene durations come from measuring
the voiceover mp3s in `assemble`, **never** from the plan (existing invariant).

---

## 7. Animation (opt-in, money-gated)

- `animate` defaults to **False**. Mirrors the CLI: never animate without an
  explicit choice.
- When on, a `run_video_stage` runs between images and voice, capped at
  `MAX_ANIMATED_SCENES` (2) by the existing `ShotPlan` validator — the web layer does
  **not** raise that cap.
- Wan constants (model/resolution/duration) stay hardcoded in `pipeline/video/wan.py`.
- The UI must show a clear "this spends DashScope credit" warning before enabling.

---

## 8. Progress / cursor polling

- Worker writes a `JobLog` row for every significant event via `publish_event()`
  (`{stage, level, message}`). No Redis pub/sub channel is used.
- Clients poll `GET /api/projects/{id}/logs/?after={pk}` on a short interval
  (e.g. 2 s), advancing the cursor to the last received `id` after each response.
- A late-joining or refreshed client gets the full history by omitting `after` (or
  passing `after=0`), then tails from there.
- Stop polling when `GET /api/projects/{id}/` reports a terminal `status`
  (`DONE`/`FAILED`).

---

## 9. Frontend (Next.js 14 App Router)

Next.js 14 App Router, TypeScript, shadcn/ui + Tailwind. All pages are client-side or
server components as appropriate. A persistent header shows the signed-in user
(name/email) and a **Log out** action; unauthenticated visits redirect to the Cognito
Hosted UI (§4a). A visual reference for every screen lives in
[`mockup.html`](./mockup.html) (open in a browser).

### Routes

| Route | Purpose |
|-------|---------|
| `/` | Index — prompt box + project list |
| `/projects/[id]` | Project detail — adapts to current status |
| `/auth/callback` | Handled by Django; Next.js receives redirect after session is set |

### Pages

0. **Auth** — Cognito Hosted UI handles login/signup/verification. After Django's
   `/auth/callback` sets the session cookie, user lands on `/`.
1. **Index** (`/`): prompt textarea + options (image backend dropdown, animate toggle
   with credit warning, voice selector) → `POST /api/projects/` → redirect to
   `/projects/{id}`. Below: the signed-in user's projects with status badges.
2. **Project** (`/projects/[id]`): single route, view adapts to `status`:
   - **REVIEW** — shot plan displayed as editable cards, two revision paths side by side:
     - **Refine box** — text input + "Refine" button → `POST /api/projects/{id}/refine/`;
       spinner while `PLANNING`, plan updates via `/logs/` polling.
     - **Manual edit** — inline-editable fields → `PATCH /api/projects/{id}/`.
     Approve / Delete buttons.
   - **GENERATING** — live progress feed (polling `/logs/?after={pk}`); image gallery tiles
     fill in as each scene lands (PENDING → RUNNING → DONE).
   - **DONE / FAILED** — three edit-then-regenerate panels:
     - **Images** — scene image grid; per-image **Regenerate** + **Regenerate all**.
     - **Voiceover** — per-scene narration textarea + voice override + **Re-voice**;
       **Regenerate all voiceovers**.
     - **Video** — `<video>` player + Download. **Rebuild video** button highlighted
       when `stale=true`.
     Failed tiles show inline error + retry.

### Key components

- **`<ProjectForm />`** — prompt + options on index, calls `POST /api/projects/`.
- **`<PlanEditor />`** — scene cards with editable fields; Refine box + manual edit.
- **`<ProgressFeed />`** — polls `/logs/?after={pk}` on an interval; renders log + image gallery.
- **`<SceneGrid />`** — image tiles with status overlays and per-scene regenerate.
- **`<VideoPlayer />`** — `<video>` + download link + stale-aware Rebuild button.

### Auth / session

Next.js proxies all `/api/*` to Django (same origin). Django's session cookie is set
on the Next.js origin after the Cognito callback redirect, so `fetch('/api/...')`
carries it automatically. No tokens stored in JS.

---

## 10. What's deferred (and the upgrade path to `webapp-spec.md`)

| Deferred | Becomes (full spec) |
|----------|---------------------|
| Cognito auth, local profile mirror | Same Cognito pool + roles/quotas, API keys, org/teams. |
| SQLite | PostgreSQL / RDS. |
| Local disk `output/<owner>/<id>/` | S3 + CloudFront, presigned URLs (ACLs disabled — see `webapp-spec.md` §8). |
| Redis local | ElastiCache. |
| One worker on localhost | ECS services, autoscaling Celery workers. |
| No billing | Stripe, Plans, Subscriptions, quotas. |

The data models are a strict subset of the SaaS models (drop `User`/`Plan`/
`Subscription` FKs); the API paths align with `/api/v1/` so the lean endpoints can be
versioned in place later.

---

## 11. Decisions

These were open; now settled (explicit by preference — no defaults left implicit).

| # | Decision |
|---|----------|
| D1 | **Plan JSON is the single source of truth.** `Scene` rows hold image state only, (re)built from `shot_plan` on approve (§4). |
| D2 | **Progress uses cursor polling** (`/logs/?after={pk}`), not SSE or WebSockets — no persistent connection, trivially proxied, late-joiners get full history for free. |
| D3 | **`.env` is the default source of truth for providers/credentials.** The UI overrides per-project: `image_model`, `animate`, `narrator_voice`, `music`, **and (per §14) the LLM + image model chosen from the user's own model registry**. `.env` remains the fallback when no per-user model is selected. |
| D4 | **One Celery worker, default concurrency.** Image tasks fan out via the chord's `group`; if a free-tier backend (Qwen) rate-limits, lower worker concurrency rather than adding backpressure logic. |
| D5 | **Music: plan-driven mood first.** Reuse `music/` + its CC-BY attribution; a file picker comes later. |
| D6 | **Users bring their own models + API keys** (per §14), chosen over an admin-defined shared registry. Larger scope (encrypted key storage, per-request routing) — scheduled **Sprint 2+**, not the initial MVP slice. |

---

## 12. Run (when we build it)

**One-time:** create a Cognito **user pool** + **app client** (allow the
authorization-code flow, callback `http://127.0.0.1:8000/auth/callback`, enable Google
IdP if wanted), then add the `COGNITO_*` values to `.env`.

```bash
# Python deps (Django + Celery added as 'webapp' optional group)
uv sync --extra webapp

# Node deps (from webapp/ directory)
cd webapp && npm install

# Four processes (run each in its own terminal):
redis-server                              # broker + result backend
uv run celery -A webapp worker -l info   # generation worker
uv run python manage.py migrate && uv run python manage.py runserver  # Django API on :8000
cd webapp && npm run dev                 # Next.js on :3000 → http://localhost:3000
```

Next.js proxies `/api/*` to `http://localhost:8000` via `next.config.js` rewrites.
`.env` (the existing one) drives provider/flag config **and** the `COGNITO_*` settings
— never committed.

---

## 13. AI-First Execution Plan (epics → work items)

This section operationalises the spec above following Arbisoft's **ai-first-engineering**
skill: when agents generate much of the implementation, *planning quality and acceptance
criteria matter more than typing speed*. Every work item below therefore carries an
explicit **contract**, **measurable acceptance criteria**, **tests & edge cases**, and a
**review focus** — so "done" is verifiable and review targets system behaviour, not style.

**Global Definition of Ready (DoR)** — a ticket may start only when it has: a contract
(interface in/out), acceptance criteria, named test cases, and its `.env`/config inputs
listed. **Definition of Done (DoD)** — code + passing tests (incl. the edge cases named),
the acceptance criteria demonstrably met, no secrets added (pre-commit hook green), and a
review against the stated focus. Style is delegated to automation (formatter/linter), not
review.

Epics map 1:1 to the Plane modules in *Arbisoft Open Source Projects*:

| Epic (Plane module) | Lead | Spec refs |
|---------------------|------|-----------|
| **A. Authentication & Signup (Backend)** | Zahid | §2, §3, §4, §4a, §6 |
| **B. Web Application (Front-end)** | Ali Tariq | §5, §8, §9 |
| **C. Video Generation Pipeline** | Laraib | §5, §6, §7 |

Cross-cutting items (data models, async infra) sit in Epic A as the backend foundation
the other epics build on. Jawad floats across all three.

---

### Epic A — Authentication & Signup (Backend) · *lead: Zahid*

**A1. Backend scaffolding — Django 5.2 + DRF + Next.js skeleton**
- **Contract:** A `webapp/` Django 5.2 project + DRF; webapp deps added as a `webapp` optional group in `pyproject.toml` (`uv sync --extra webapp`).
- **Acceptance criteria:** `uv run python manage.py check` passes; `runserver` boots on :8000.
- **Tests & edge cases:** smoke test imports `pipeline.schema` from uv venv; missing `.env` → clear startup error; proxy correctly forwards cookies.
- **Review focus:** dependency isolation; proxy config; no accidental coupling into `pipeline/`.

**A2. Data models — UserProfile / Project / Scene / JobLog (§4)**
- **Contract:** Four models exactly per §4, with the `Project.status` enum
  `DRAFT→PLANNING→REVIEW→GENERATING→DONE (·→FAILED)` and `owner` FK indexed.
- **Acceptance criteria:** migrations apply on a clean SQLite file; `Project.shot_plan` is
  the single source of truth (no scene content duplicated in `Scene`); `Scene` rows hold
  image state only.
- **Tests & edge cases:** state-transition table (§4) enforced (illegal transition raises);
  deleting a Project cascades `Scene`/`JobLog`; `stale` defaults False.
- **Review focus:** data integrity, single-source-of-truth invariant (D1), index on `owner`.

**A3. AWS Cognito Hosted-UI OAuth (§4a)**
- **Contract:** `GET /auth/login` → Hosted UI; `GET /auth/callback?code=…` exchanges code for
  ID+access+refresh tokens; `POST /auth/logout` clears session + Cognito logout. Config from
  `COGNITO_*` env only.
- **Acceptance criteria:** a configured pool lets a user sign up (incl. Google IdP) and land
  on Home with a session cookie; Django stores **no** passwords.
- **Tests & edge cases:** invalid/expired `code` → 401; state/CSRF param verified; refresh
  flow on expired access token; missing `COGNITO_*` → explicit config error.
- **Review focus:** security assumptions — token exchange, session fixation, secrets only in `.env`.

**A4. JWT (JWKS) verification + just-in-time UserProfile (§4a)**
- **Contract:** Every authed request verifies the Cognito JWT against the pool's JWKS
  (issuer + audience + expiry); DRF resolves `request.user` → get-or-create `UserProfile`
  keyed by `cognito_sub`.
- **Acceptance criteria:** first login provisions a profile from verified claims; subsequent
  logins reuse it; tampered/expired tokens rejected.
- **Tests & edge cases:** wrong `aud`/`iss` → 401; expired token → 401; JWKS key rotation
  handled (refetch); duplicate concurrent first-login is idempotent (one profile).
- **Review focus:** correctness of signature/claim verification; no trust of unverified claims.

**A5. Per-user isolation (§4a)**
- **Contract:** Every `/api/projects/...` view filters `owner=request.user`; a foreign or
  missing id returns **404** (not 403, ids non-enumerable); anonymous → **401**.
- **Acceptance criteria:** user B cannot read, mutate, or download user A's project or media;
  media serving also enforces ownership.
- **Tests & edge cases:** cross-user GET/PATCH/DELETE/download all 404; anonymous → 401;
  direct media path traversal blocked.
- **Review focus:** authorization on **every** path incl. `/logs/` + media; behavioral regression
  tests for isolation.

**A6. Celery + Redis async infrastructure (§6)**
- **Contract:** Celery 5.4 + Redis as broker/result/pub-sub; tasks `run_plan_stage`,
  `run_refine_stage`, `run_image_stage`, `run_voice_stage`, `run_assemble_stage` wrap the
  existing `pipeline/` functions as a library (no shelling out).
- **Acceptance criteria:** approve enqueues the chord
  `group(images) | voice | assemble`; each task persists progress to `JobLog` via `publish_event()`.
- **Tests & edge cases:** any task raising sets `status=FAILED` + error `JobLog` entry;
  worker restart mid-job leaves consistent state; Qwen rate-limit lowers concurrency
  (D4), no backpressure code.
- **Review focus:** error handling, deployment safety, the FAILED-path contract.

---

### Epic B — Web Application (Front-end) · *lead: Ali Tariq*

**B1. App shell + auth-gated layout (§9)**
- **Contract:** Next.js 14 App Router; `next.config.js` rewrites `/api/*` → `http://localhost:8000`; persistent header shows signed-in user + Log out; unauthenticated visits redirect to Cognito Hosted UI. shadcn/ui + Tailwind set up.
- **Acceptance criteria:** matches `mockup.html`; anon → redirect to Cognito; signed-in → Home with identity shown; `/api/*` fetch reaches Django.
- **Tests & edge cases:** expired session mid-navigation → redirect, not a crash; logout clears Django session + Cognito; proxy correctly forwards cookies.
- **Review focus:** auth gating on every route; proxy config doesn't expose Django internals; no secrets in JS bundle.

**B2. Index — submit idea + project list (§5 `POST/GET /api/projects/`, §9.1)**
- **Contract:** `<ProjectForm />` component — prompt textarea + options (image backend, animate toggle **with credit warning**, voice) → `POST /api/projects/` → `router.push('/projects/{id}')`. Project list below using `GET /api/projects/`.
- **Acceptance criteria:** only `prompt` required (rest fall back to `.env`, D3); animate off by default with DashScope-credit warning; list shows only the signed-in user's projects.
- **Tests & edge cases:** empty prompt → inline validation (no request); list shows only the user's projects; gpt-image-1 never preselected.
- **Review focus:** money rules surfaced in UI (animate/gpt-image-1), correct default fallbacks.

**B3. Plan review + revise UI (§5 `PATCH`/`refine`, §9.2 REVIEW)**
- **Contract:** `<PlanEditor />` component on `/projects/[id]` (REVIEW state) — Refine box → `POST /api/projects/{id}/refine/` (LLM) and inline editable scene cards → `PATCH /api/projects/{id}/` — plus Approve / Delete buttons.
- **Acceptance criteria:** refine shows a spinner during `PLANNING` and updates plan via `/logs/` polling; manual edits persist on blur/save; editing outside REVIEW → 409 surfaced as a toast/error; approve disabled until plan exists.
- **Tests & edge cases:** concurrent refine + manual edit resolves to one source of truth; 409 handled gracefully.
- **Review focus:** review gate enforced (no generation pre-approve); single-source plan.

**B4. Generation screen + live progress via polling (§8, §9.2 GENERATING)**
- **Contract:** `<ProgressFeed />` component polls `GET /api/projects/{id}/logs/?after={pk}` every ~2 s, advancing the cursor on each response; renders log live and fills `<SceneGrid />` as scenes land (PENDING→RUNNING→DONE).
- **Acceptance criteria:** ≥1 log entry per stage rendered; refresh/late-join replays history by starting with `after=0`; polling stops on terminal project `status` (`DONE`/`FAILED`).
- **Tests & edge cases:** late-joiner/refresh shows correct state (full history replay); FAILED renders error + retry; no runaway polling after terminal status.
- **Review focus:** cursor-advance correctness; polling stops cleanly; no redundant re-renders on empty responses.

**B5. Asset editing panels — images / voiceover / video (§5 regenerate*/revoice/reassemble, §9.2 DONE)**
- **Contract:** Three shadcn/ui panels on the DONE project page: `<SceneGrid />` (per-image **Regenerate** + **Regenerate all**), per-scene narration/voice textarea (**Re-voice** + **Regenerate all voiceovers**), and `<VideoPlayer />` with Download + **Rebuild video** (highlighted when `stale=true`).
- **Acceptance criteria:** regenerating image/voiceover sets `stale=true` and Rebuild button highlights; `reassemble/` clears `stale`; iterating never re-runs the LLM.
- **Tests & edge cases:** force gpt-image-1 on a single scene is explicit-only; stale indicator accurate after partial regen; failed tile shows inline error + retry.
- **Review focus:** stale/`final.mp4` consistency; money rules (explicit paid backend) in UI.

---

### Epic C — Video Generation Pipeline · *lead: Laraib*

> The engine already exists in `pipeline/`. These items wrap/verify it behind the web tasks
> (§6) and the spec's API — *reuse, don't rewrite* (§3). Each item's contract is the Celery
> task + the `pipeline/` function it wraps.

**C1. Plan stage — `run_plan_stage` (§6)**
- **Contract:** Wraps `script_agent` (plan + **auto-polish + consistency review**, run
  automatically); saves `shot_plan`; `PLANNING → REVIEW`.
- **Acceptance criteria:** a prompt yields a valid `ShotPlan` (schema.py); polish + review run
  without manual flags; subscribe/CTA scenes only for listicle-style (story videos end on the
  final beat).
- **Tests & edge cases:** LLM/JSON-shape failure → FAILED + error log; character looks never
  inlined per scene (consistency enforced by code, not the LLM).
- **Review focus:** schema-contract conformance; existing consistency invariants preserved.

**C2. Refine stage — `run_refine_stage` (§5 refine, §6)**
- **Contract:** Wraps `script_agent.revise_shot_plan(plan, instruction)` (+ re-run
  polish/review); REVIEW-only; saves revised `shot_plan`, back to REVIEW.
- **Acceptance criteria:** a natural-language instruction measurably changes the plan; polish +
  review re-run as for a fresh plan.
- **Tests & edge cases:** refine outside REVIEW → 409; empty/garbage instruction → no
  destructive change; idempotent re-runs.
- **Review focus:** plan integrity across edits; no character-consistency regressions.

**C3. Image stage — `run_image_stage` (§6, money rules)**
- **Contract:** Wraps `images.get_provider(...).generate(...)` per scene; honors character
  refs/negatives via `ShotPlan.expand()`; provider order Qwen(free)→Flux→Pexels→placeholder,
  **gpt-image-1 only on explicit opt-in**.
- **Acceptance criteria:** per-scene status streamed; fallback chain ends at placeholder;
  `global_negative` + `Character.negative` merged into every scene.
- **Tests & edge cases:** Qwen rate-limit falls back, not crashes; gpt-image-1 never
  auto-selected; negatives respected (no drawn "negated" traits).
- **Review focus:** money rules (no surprise paid calls); character-consistency code path.

**C4. Voiceover stage — `run_voice_stage` (§6)**
- **Contract:** Wraps `pipeline.voiceover` (edge-tts, `boundary="WordBoundary"`); one scene
  when `scene_index` set, else all; emits mp3 + `.words.json`.
- **Acceptance criteria:** word-timing JSON present for captions; re-voice updates
  `shot_plan` + that scene's audio only and sets `stale=true`.
- **Tests & edge cases:** missing word timings → caught (captions depend on them); voice
  override applies; all-vs-single scope correct.
- **Review focus:** caption-timing contract; stale propagation.

**C5. Assembly stage — `run_assemble_stage` + download (§5 download/reassemble, §6)**
- **Contract:** Wraps `pipeline.assemble` (FFmpeg, absolute `.resolve()` paths,
  `ffmpeg-full`); scene durations **measured from the mp3s**, never the plan; clears `stale`;
  `GENERATING → DONE`. `GET /download/` serves the owner's `final.mp4`.
- **Acceptance criteria:** `final.mp4` matches what the CLI produces from the same inputs;
  `reassemble/` refreshes the video and clears `stale`.
- **Tests & edge cases:** missing libass/`ffmpeg-full` → actionable error; download enforces
  ownership (404 otherwise); durations come from audio.
- **Review focus:** the duration invariant; deployment dep (`ffmpeg-full`); media authz.

**C6. Animation stage (opt-in, money-gated) — `run_video_stage` (§7)**
- **Contract:** Only when `animate=true`; inserts between images and voice; capped at
  `MAX_ANIMATED_SCENES` (2) by the existing `ShotPlan` validator; Wan constants stay hardcoded
  in `pipeline/video/wan.py`.
- **Acceptance criteria:** off by default; the web layer never raises the cap; UI credit
  warning shown before enabling.
- **Tests & edge cases:** cap enforced (3rd scene rejected); animation disabled path is the
  default; never enabled implicitly.
- **Review focus:** money rules (DashScope credit) — the highest-risk item; explicit opt-in only.

---

## 14. User-defined models & credentials (BYO-key) — *Sprint 2+*

Each user registers their **own** LLM + image models and their **own** API keys; their
projects run on the models they chose, billed to their keys. This extends D3 (env was the
only credential source) and is a deliberate step toward the SaaS vision in `webapp-spec.md`.
**Scope warning:** this is larger and more security-sensitive than the rest of the MVP —
hence D6 schedules it for Sprint 2+, after the foundation + auth + engine slice land.

The engine already supports per-call model selection (`script_agent` takes `model=`;
routing is by prefix — `gpt-*`→OpenAI, `claude-*`→Anthropic, else→LiteLLM proxy; image
backends are plugins). The new work is **persistence (encrypted keys), per-request routing
of credentials, and UI** — not new generation logic.

### 14.1 Data models (per user, extend §4)

**UserCredential** — a provider API key the user owns.
| Field | Type | Notes |
|-------|------|-------|
| `id` | int (pk) | |
| `owner` | FK → UserProfile, indexed | Every query filtered by signed-in user. |
| `provider` | char (enum: openai/anthropic/litellm/dashscope/…) | Routes to the right SDK/endpoint. |
| `label` | char | User-facing name ("my OpenAI key"). |
| `key_encrypted` | bytes | **Encrypted at rest** (Fernet/KMS). Never stored plaintext. |
| `created_at` | datetime | |

**UserModel** — a model the user can pick for a project.
| Field | Type | Notes |
|-------|------|-------|
| `id` | int (pk) | |
| `owner` | FK → UserProfile, indexed | |
| `kind` | char (enum: `llm` / `image`) | Which dropdown it appears in. |
| `label` | char | Display name. |
| `model_id` | char | e.g. `gpt-4o-mini`, `claude-haiku-4-5`, an image backend id. |
| `credential` | FK → UserCredential, null | null → use the server's `.env` key (shared default). |
| `costs_money` | bool | Drives the UI cost warning + explicit opt-in. |
| `is_default` | bool | The user's default for that `kind`. |

**Project** gains `llm_model` and `image_model` (FK → UserModel, **nullable**). Null falls
back to the `.env` defaults (existing behaviour), so projects keep working with no registry.

### 14.2 API (extends §5)

- `GET/POST/PATCH/DELETE /api/credentials/` — manage the caller's keys. **Responses never
  include the key**; writes are accept-only (no read-back), UI shows masked `••••1234`.
- `GET/POST/PATCH/DELETE /api/models/` — manage the caller's `UserModel` registry.
- `POST /api/projects/` and `/refine/` accept optional `llm_model` / `image_model` ids,
  validated to belong to the caller (else 404, per §4a).

### 14.3 Routing

The Celery worker resolves `(model_id, decrypted key, endpoint)` **at call time** and passes
them into `script_agent` / the image provider per request — never via global env mutation
(workers are shared across users). Decryption happens only inside the worker process.

### 14.4 Security (non-negotiable)

- **Keys encrypted at rest**; the encryption key comes from env/KMS and is **never** in the
  repo (the pre-commit hook still guards commits).
- **API never returns raw keys**; UI input is masked and update-only.
- **Keys never reach `JobLog` or any log**; provider error messages are redacted before
  persistence.
- **Per-user isolation** (§4a) covers credentials + models — cross-user access returns 404.

### 14.5 Money rules

- BYO-key means **the user pays for their own usage** — but `costs_money` models still warn
  in the UI before selection.
- Shared/default models (no credential FK) keep the existing rules: qwen / gpt-4o-mini
  default; gpt-image-1 explicit-only; animation off by default.

### 14.6 AI-first work items (BYO-key — Sprint 2+)

**A7. Per-user credential vault (encrypted at rest)** · *Epic A · Zahid*
- **Contract:** `UserCredential` model + `/api/credentials/` CRUD; keys encrypted (Fernet/KMS)
  on write, decrypted only in the worker; API/UI never expose plaintext.
- **Acceptance criteria:** a stored key round-trips through a real provider call; `GET` returns
  only masked metadata; rotating a key re-encrypts; deleting cascades to dependent `UserModel`s.
- **Tests & edge cases:** key never appears in any response/log/JobLog; cross-user access → 404;
  missing encryption key → startup error, not plaintext fallback.
- **Review focus:** secret handling, encryption at rest, isolation — the highest-risk item.

**A8. Model registry CRUD (`UserModel`)** · *Epic A · Zahid*
- **Contract:** `UserModel` model + `/api/models/` CRUD; `kind` ∈ {llm,image}; optional
  `credential` FK; `costs_money` + `is_default` flags.
- **Acceptance criteria:** a user can register/list/edit/delete models; defaults resolve per
  kind; a model with no credential falls back to `.env`.
- **Tests & edge cases:** invalid `model_id` rejected; cross-user 404; deleting a credential
  nulls or blocks its models predictably.
- **Review focus:** validation, data integrity, fallback-to-env correctness.

**C7. Per-request model + credential routing** · *Epic C · Laraib*
- **Contract:** `run_plan_stage`/`run_refine_stage`/`run_image_stage` accept a resolved
  `(model_id, key, endpoint)` and pass it through; no global env mutation per request.
- **Acceptance criteria:** two concurrent projects using different users' models/keys never
  cross-contaminate; null model → `.env` default path unchanged.
- **Tests & edge cases:** concurrent requests isolate credentials; bad key → FAILED + redacted
  error (no key leak); prefix routing (gpt-*/claude-*/else) honored.
- **Review focus:** concurrency isolation, no key leakage, backward-compatible default path.

**B6. Settings UI — manage models & keys + per-project selection** · *Epic B · Ali Tariq*
- **Contract:** Next.js `/settings` page with shadcn/ui forms — add/edit/delete credentials (masked input) and models; `<ProjectForm />` and plan review show LLM + image dropdowns from the user's registry.
- **Acceptance criteria:** keys shown masked, never pre-filled in inputs; `costs_money` models show a warning before selection; selecting a model persists to the project; empty registry falls back to `.env` defaults silently.
- **Tests & edge cases:** masked key never in DOM/source; cost warning required before a paid model is chosen; dropdowns scoped to the signed-in user.
- **Review focus:** no client-side key exposure; money-rule warnings; isolation.
