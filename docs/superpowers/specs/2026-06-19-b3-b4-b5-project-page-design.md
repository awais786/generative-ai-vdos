# B3 + B4 + B5 — Project Page Design

**Epic B — Web Application (Front-end) · tickets B3, B4, B5**
**Date:** 2026-06-19
**Lead:** Ali Tariq

---

## 1. Scope

Build the `/projects/[id]` page that handles every post-creation project state:

- **B3** — Plan review + revise (REVIEW state)
- **B4** — Generation progress via SSE (GENERATING state)
- **B5** — Asset editing panels (DONE state)

Backend API is assumed complete per the contracts in `docs/webapp-mvp-spec.md §5`. No backend changes.

Out of scope: B6 (Settings UI, Sprint 2+).

---

## 2. Architecture

### 2.1 Page entry point

`app/projects/[id]/page.tsx` — async server component.

Fetches `GET /api/projects/{id}/` at render time (forwarding `sessionid` cookie, same pattern as `lib/auth-server.ts`). Passes the initial snapshot to `<ProjectPage />` as a prop. Returns 404 if the fetch returns 404.

### 2.2 Client root

`components/project/project-page.tsx` — `'use client'`. Receives `initialProject: Project`. Owns the top-level `project` state and switches on `project.status`:

| Status | Component rendered |
|--------|-------------------|
| `DRAFT` / `PLANNING` | `<PlanningView>` |
| `REVIEW` | `<PlanEditor>` |
| `GENERATING` | `<GeneratingView>` |
| `DONE` | `<DoneView>` |
| `FAILED` | `<FailedView>` |

State transitions triggered by action responses update `project` locally (no full page reload).

### 2.3 SSE

`EventSource` is opened only during `GENERATING` state, inside `<GeneratingView>`. It connects to `/api/projects/{id}/events/` (proxied through Next.js).

Event shape (per spec §8):
```json
{ "type": "log", "stage": "images", "level": "info", "message": "...",
  "ts": "...", "project_status": "GENERATING",
  "scene_index": null, "image_status": null }
```

On each event:
- Append to log feed
- If `scene_index` present + `image_status` set: update that scene's status in local state
- If `project_status` is `DONE` or `FAILED`: close EventSource, flip `project.status` → re-renders to `DoneView` or `FailedView`

`EventSource` is closed in the `useEffect` cleanup to prevent leaks on unmount.

### 2.4 PLANNING polling

`<PlanningView>` polls `GET /api/projects/{id}/` every 2 s (via `setInterval`). When `status` becomes `REVIEW`, clears interval and updates parent `project` state. Used for both initial plan generation and refine waits.

---

## 3. Components

### 3.1 `PlanningView`

File: `components/project/planning-view.tsx`

Shows a centered spinner + "Generating plan…" label. Also shows any `JobLog` entries already in `initialProject.logs` (useful for late-joiners). Polls every 2 s to detect REVIEW transition.

### 3.2 `PlanEditor` (B3)

File: `components/project/plan-editor.tsx`

Renders when `status === 'REVIEW'`. Scene cards in this state are read from **`project.shot_plan`** (the JSON field) — no `Scene` rows exist until `approve` is called.

**Header row:** project title (read-only) + `[Approve]` button (accent, right-aligned) + `[Delete]` button (danger, right-aligned).

**Refine box:**
- `<textarea>` for natural-language instruction
- `[Refine]` button → `POST /api/projects/{id}/refine/` with `{instruction}`
- On 200/202: set project status to `PLANNING` locally (triggers `PlanningView` + polling)
- On non-200: inline error below the textarea

**Scene cards** (one per scene in `shot_plan.scenes`):
- Scene index badge (1-based)
- `media_prompt` — `<textarea>`, editable, `PATCH` fired on blur: `{ shot_plan: { ...currentShotPlan, scenes: [...withUpdatedScene] } }`
- `narration` — `<textarea>`, editable, same PATCH pattern
- On PATCH 409: inline error "Can only edit plan in REVIEW state."

**Approve flow:**
- `[Approve]` → `POST /api/projects/{id}/approve/`
- On 200/202: set `project.status = 'GENERATING'` locally

**Delete flow:**
- `[Delete]` → confirmation inline ("Are you sure?" + confirm/cancel) → `DELETE /api/projects/{id}/`
- On 204: `router.push('/home')`

### 3.3 `GeneratingView` (B4)

File: `components/project/generating-view.tsx`

**Log feed:** scrollable list of `{level, stage, message, ts}` entries. New entries appended via SSE. `level === 'error'` → red text, `level === 'warn'` → orange, else muted.

**Scene grid:** `<SceneGrid>` in read-only mode. Shows each scene with a status overlay (PENDING = dim, RUNNING = spinner, DONE = image thumbnail if `image_path` set, FAILED = red X). No action buttons.

### 3.4 `DoneView` (B5)

File: `components/project/done-view.tsx`

**Scene cards** (one per scene):
- Image thumbnail (`<img src={scene.image_path}>`) or placeholder if no path
- Status badge
- `media_prompt` — `<textarea>`, editable
- `[Regenerate image]` button → `POST /api/projects/{id}/scenes/{scene.index}/regenerate/` with `{prompt: editedMediaPrompt}`; optimistically sets that scene's `image_status = 'RUNNING'`; sets `project.stale = true`
- `narration` — `<textarea>`, editable
- Voice `<select>` (same options as ProjectForm)
- `[Re-voice]` button → `POST /api/projects/{id}/scenes/{scene.index}/revoice/` with `{narration, narrator_voice}`; sets `project.stale = true`

**Bulk action row:**
- `[Regenerate all images]` → `POST /api/projects/{id}/regenerate-images/`; sets all scenes `image_status = 'RUNNING'`; sets `project.stale = true`
- `[Regenerate all voiceovers]` → `POST /api/projects/{id}/regenerate-voiceovers/`; sets `project.stale = true`

**Video player:**
- `<video controls src="/api/projects/{id}/download/">` (streamed via Django proxy)
- `[Download]` link → same URL with `download` attribute
- `[Rebuild video]` button — highlighted (warn color) when `project.stale === true` — → `POST /api/projects/{id}/reassemble/`; clears `project.stale` locally

### 3.5 `FailedView`

File: `components/project/failed-view.tsx`

Shows `project.error` message in a danger-bordered card. `[Retry]` button → `POST /api/projects/{id}/approve/`; on 200/202 sets `project.status = 'GENERATING'`.

### 3.6 `SceneGrid` (shared)

File: `components/project/scene-grid.tsx`

Reusable grid of scene tiles. Props:
- `scenes: Scene[]`
- `mode: 'generating' | 'done'`

In `generating` mode: status overlays only, no action buttons.
In `done` mode: editable fields + action buttons (delegates to `DoneView` via callbacks).

### 3.7 `VideoPlayer`

File: `components/project/video-player.tsx`

Props: `projectId: string`, `stale: boolean`, `onRebuild: () => void`.

---

## 4. API contracts consumed

All paths are proxied through Next.js `/api/*` → `http://localhost:8000/api/*`.

| Method | Path | Body | Success |
|--------|------|------|---------|
| `GET` | `/api/projects/{id}/` | — | `200` full `Project` |
| `PATCH` | `/api/projects/{id}/` | partial `{shot_plan}` | `200` or `409` |
| `DELETE` | `/api/projects/{id}/` | — | `204` |
| `POST` | `/api/projects/{id}/approve/` | — | `200`/`202` |
| `POST` | `/api/projects/{id}/refine/` | `{instruction}` | `200`/`202` or `409` |
| `GET` | `/api/projects/{id}/events/` | — | SSE stream |
| `POST` | `/api/projects/{id}/scenes/{i}/regenerate/` | `{prompt?}` | `200`/`202` |
| `POST` | `/api/projects/{id}/regenerate-images/` | — | `200`/`202` |
| `POST` | `/api/projects/{id}/scenes/{i}/revoice/` | `{narration, narrator_voice}` | `200`/`202` |
| `POST` | `/api/projects/{id}/regenerate-voiceovers/` | — | `200`/`202` |
| `POST` | `/api/projects/{id}/reassemble/` | — | `200`/`202` |
| `GET` | `/api/projects/{id}/download/` | — | file stream |

`Project` type (from serializer). Note: `Scene` rows only exist after `approve` is called — `project.scenes` is `[]` during REVIEW. REVIEW state reads scene data from `project.shot_plan.scenes[]` instead.

```ts
// Django Scene objects — exist only after approve
interface Scene {
  id: number
  index: number
  narration: string       // assumed included by backend in final API
  media_prompt: string    // assumed included by backend in final API
  image_path: string
  image_status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED'
  image_provider: string
}

// Raw shot_plan scene (from the JSON field, used in REVIEW state)
interface ShotPlanScene {
  narration: string
  media_prompt: string
  on_screen_text?: string
  negative_prompt?: string
  [key: string]: unknown
}

interface ShotPlan {
  scenes: ShotPlanScene[]
  [key: string]: unknown
}

interface Project {
  id: string
  title: string
  prompt: string
  status: 'DRAFT' | 'PLANNING' | 'REVIEW' | 'GENERATING' | 'DONE' | 'FAILED'
  shot_plan: ShotPlan | null
  image_backend: string
  animate: boolean
  narrator_voice: string
  music: string
  error: string
  stale: boolean
  scenes: Scene[]          // [] until approve; populated for GENERATING/DONE
  created_at: string
  updated_at: string
}
```

---

## 5. Design tokens

Same palette as the rest of the webapp (inline hex, no CSS vars):

| Token | Value |
|-------|-------|
| `bg` | `#171a21` |
| `panel2` | `#1e222b` |
| `line` | `#2a2f3a` |
| `ink` | `#e7e9ee` |
| `muted` | `#9aa3b2` |
| `accent` | `#6ea8fe` |
| `accent2` | `#5cd6a4` |
| `warn` | `#f0a35e` |
| `danger` | `#f06a6a` |

---

## 6. File map

| File | Action |
|------|--------|
| `app/projects/[id]/page.tsx` | Create — server component entry |
| `components/project/project-page.tsx` | Create — client root, status switch |
| `components/project/planning-view.tsx` | Create — spinner + poll |
| `components/project/plan-editor.tsx` | Create — B3 REVIEW state |
| `components/project/generating-view.tsx` | Create — B4 SSE + log feed |
| `components/project/scene-grid.tsx` | Create — shared scene tiles |
| `components/project/done-view.tsx` | Create — B5 edit + rebuild |
| `components/project/video-player.tsx` | Create — video + download |
| `components/project/failed-view.tsx` | Create — error + retry |
| `lib/project-types.ts` | Create — shared TS types |

---

## 7. Acceptance criteria

- [ ] PLANNING state shows spinner; auto-advances to REVIEW without page reload when plan ready
- [ ] REVIEW: scene `media_prompt` + `narration` editable inline; PATCH fires on blur; 409 shown as inline error
- [ ] REVIEW: Refine box sends instruction, transitions to PLANNING, auto-advances back to REVIEW
- [ ] REVIEW: Approve button transitions to GENERATING
- [ ] REVIEW: Delete navigates to `/home`
- [ ] GENERATING: SSE log feed renders in real time; scene grid overlays reflect `image_status`
- [ ] GENERATING: terminal SSE event transitions to DONE or FAILED without reload
- [ ] DONE: `media_prompt` editable per scene; Regenerate sends edited prompt; scene flips to RUNNING
- [ ] DONE: `narration` + voice editable per scene; Re-voice sends both
- [ ] DONE: Regenerate all / Regenerate all voiceovers buttons work
- [ ] DONE: stale=true highlights Rebuild button in warn color; Rebuild clears stale locally
- [ ] DONE: Download link works; video player renders
- [ ] FAILED: error message shown; Retry transitions to GENERATING
- [ ] `gpt-image-1` never pre-selected in any voice/backend selector
- [ ] EventSource closed on unmount and on terminal status

---

## 8. Out of scope

- Real-time project list updates on `/home` (B4 spec mentions SSE drives list too — deferred)
- B6 Settings UI (Sprint 2+)
- Any backend implementation
