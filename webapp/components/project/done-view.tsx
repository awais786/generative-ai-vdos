'use client'

import { memo, useCallback, useEffect, useRef, useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { Project, Scene } from '@/lib/project-types'
import { Button } from '@/components/ui/button'
import VideoPlayer from './video-player'
import StatusPill from './status-pill'

interface Props {
  project: Project
  onUpdate: (updates: Partial<Project>) => void
}

const VOICES = [
  { value: 'en-US-AndrewNeural', label: 'Andrew (US Male)' },
  { value: 'en-US-RyanNeural', label: 'Ryan (GB Male)' },
  { value: 'en-US-AvaNeural', label: 'Ava (US Female)' },
]

// Presigned S3 URLs already contain '?' (new signature per request) so the browser
// never caches them across regens. Local-dev URLs have no '?' — append updated_at
// so the browser treats the re-generated image as a distinct resource.
function stableImageSrc(scene: Scene): string | undefined {
  if (!scene.media_path) return undefined
  if (scene.media_path.includes('?')) return scene.media_path
  return `${scene.media_path}?v=${encodeURIComponent(scene.updated_at ?? '')}`
}

const IMG_STATUS_COLOR: Record<string, string> = {
  PENDING: '#9aa3b2',
  RUNNING: '#f0a35e',
  DONE:    '#5cd6a4',
  FAILED:  '#f06a6a',
}

const TEXTAREA_CLASS =
  'w-full bg-[#171a21] text-[#e7e9ee] border border-[#2a2f3a] rounded-lg px-3 py-2 text-sm resize-y focus:outline-none focus:ring-1 focus:ring-[#6ea8fe]'

export default function DoneView({ project, onUpdate }: Props) {
  const router = useRouter()
  const [scenes, setScenes] = useState<Scene[]>(project.scenes)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [isRegenAll, startRegenAll] = useTransition()
  const [isRevoiceAll, startRevoiceAll] = useTransition()
  const [isDeleting, startDelete] = useTransition()

  function handleDelete() {
    startDelete(async () => {
      const res = await fetch(`/api/projects/${project.id}/`, { method: 'DELETE' })
      if (res.status === 204) router.push('/home')
    })
  }

  // stable refs so React.memo on DoneSceneCard doesn't re-render siblings
  const updateSceneStatus = useCallback(
    (index: number, image_status: Scene['image_status']) => {
      setScenes(prev =>
        prev.map(s => (s.index === index ? { ...s, image_status } : s)),
      )
    },
    [],
  )

  const updateScene = useCallback((updated: Scene) => {
    setScenes(prev => prev.map(s => s.index === updated.index ? updated : s))
  }, [])

  const setStale = useCallback(() => {
    onUpdate({ stale: true })
  }, [onUpdate])

  function handleRegenAll() {
    startRegenAll(async () => {
      await fetch(`/api/projects/${project.id}/regenerate-images/`, {
        method: 'POST',
      })
      setScenes(prev => prev.map(s => ({ ...s, image_status: 'RUNNING' as const })))
      onUpdate({ stale: true })
    })
  }

  function handleRevoiceAll() {
    startRevoiceAll(async () => {
      await fetch(`/api/projects/${project.id}/regenerate-voiceovers/`, {
        method: 'POST',
      })
      onUpdate({ stale: true })
    })
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <StatusPill status="DONE" />
        {confirmDelete ? (
          <div className="flex items-center gap-2">
            <span className="text-xs text-[#9aa3b2]">Delete this project?</span>
            <Button
              disabled={isDeleting}
              onClick={handleDelete}
              className="bg-[#f06a6a] text-white text-xs px-3 py-1.5 rounded-lg hover:bg-[#d95858] disabled:opacity-50"
            >
              {isDeleting ? 'Deleting…' : 'Yes, delete'}
            </Button>
            <Button
              onClick={() => setConfirmDelete(false)}
              className="bg-transparent border border-[#2a2f3a] text-[#e7e9ee] text-xs px-3 py-1.5 rounded-lg hover:bg-[#1e222b]"
            >
              Cancel
            </Button>
          </div>
        ) : (
          <Button
            onClick={() => setConfirmDelete(true)}
            className="bg-transparent border border-[#f06a6a]/40 text-[#f06a6a] text-xs px-3 py-1.5 rounded-lg hover:bg-[#f06a6a]/10"
          >
            Delete project
          </Button>
        )}
      </div>

      {/* Video hero */}
      <VideoPlayer
        projectId={project.id}
        stale={project.stale}
        onRebuild={(updated) => onUpdate(updated)}
      />

      {/* Scene strip header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-[10px] uppercase tracking-[0.2em] font-medium text-[#4a5568]">
          Scenes
        </p>
        <div className="flex items-center gap-2">
          <Button
            disabled={isRegenAll}
            onClick={handleRegenAll}
            className="bg-transparent border border-[#2a2f3a] text-[#e7e9ee] text-xs px-3 py-1.5 rounded-lg hover:bg-[#252a35] disabled:opacity-50"
          >
            {isRegenAll ? 'Queuing…' : 'Regenerate all images'}
          </Button>
          <Button
            disabled={isRevoiceAll}
            onClick={handleRevoiceAll}
            className="bg-transparent border border-[#2a2f3a] text-[#e7e9ee] text-xs px-3 py-1.5 rounded-lg hover:bg-[#252a35] disabled:opacity-50"
          >
            {isRevoiceAll ? 'Queuing…' : 'Regenerate all voiceovers'}
          </Button>
        </div>
      </div>

      {/* Expandable scene cards */}
      <div className="space-y-2">
        {scenes.map(scene => (
          <DoneSceneCard
            key={scene.id}
            scene={scene}
            projectId={project.id}
            defaultVoice={project.narrator_voice}
            onStatusChange={updateSceneStatus}
            onSceneUpdate={updateScene}
            onSetStale={setStale}
          />
        ))}
      </div>
    </div>
  )
}

// React.memo prevents sibling re-renders when one scene's status changes
const DoneSceneCard = memo(function DoneSceneCard({
  scene,
  projectId,
  defaultVoice,
  onStatusChange,
  onSceneUpdate,
  onSetStale,
}: {
  scene: Scene
  projectId: string
  defaultVoice: string
  onStatusChange: (index: number, status: Scene['image_status']) => void
  onSceneUpdate: (updated: Scene) => void
  onSetStale: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [mediaPrompt, setMediaPrompt] = useState(scene.media_prompt)
  const [narration, setNarration] = useState(scene.narration)
  const [voice, setVoice] = useState(defaultVoice)
  const [isRegenerating, startRegen] = useTransition()
  const [isRevoicing, startRevoice] = useTransition()
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  const imgColor = IMG_STATUS_COLOR[scene.image_status] ?? '#9aa3b2'

  function handleRegen() {
    startRegen(async () => {
      onStatusChange(scene.index, 'RUNNING')
      await fetch(`/api/projects/${projectId}/scenes/${scene.index}/regenerate/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: mediaPrompt }),
      })
      // Poll until the background task finishes so media_path updates without a reload.
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = setInterval(async () => {
        try {
          const res = await fetch(`/api/projects/${projectId}/scenes/${scene.index}/`)
          if (!res.ok) return
          const updated: Scene = await res.json()
          onStatusChange(scene.index, updated.image_status)
          if (updated.image_status === 'DONE' || updated.image_status === 'FAILED') {
            clearInterval(pollRef.current!)
            pollRef.current = null
            onSceneUpdate(updated)
            if (updated.image_status === 'DONE') onSetStale()
          }
        } catch { /* keep polling */ }
      }, 2000)
    })
  }

  function handleRevoice() {
    startRevoice(async () => {
      await fetch(`/api/projects/${projectId}/scenes/${scene.index}/revoice/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ narration, narrator_voice: voice }),
      })
      onSetStale()
    })
  }

  return (
    <div className="bg-[#1e222b] border border-[#2a2f3a] rounded-[10px] overflow-hidden">
      {/* Collapsed header row — always visible */}
      <button
        type="button"
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-[#252a35] transition-colors text-left"
      >
        {/* Thumbnail */}
        <div className="w-16 h-10 rounded bg-[#171a21] shrink-0 overflow-hidden flex items-center justify-center">
          {scene.media_path && scene.image_status === 'DONE' ? (
            <img
              src={stableImageSrc(scene)}
              alt=""
              className="w-full h-full object-cover"
            />
          ) : scene.image_status === 'RUNNING' ? (
            <div className="w-4 h-4 rounded-full border border-[#f0a35e] border-t-transparent animate-spin" />
          ) : (
            <span className="text-[#4a5568] text-[10px]">{scene.image_status.toLowerCase()}</span>
          )}
        </div>

        {/* Scene label */}
        <span className="text-xs font-mono text-[#9aa3b2] shrink-0">
          {String(scene.index + 1).padStart(2, '0')}
        </span>

        {/* Status dot */}
        <span
          className="w-1.5 h-1.5 rounded-full shrink-0"
          style={{ backgroundColor: imgColor }}
        />

        {/* Narration preview */}
        <span className="text-xs text-[#9aa3b2] truncate flex-1">
          {narration || scene.narration}
        </span>

        {/* Expand toggle */}
        <span className="text-[10px] text-[#4a5568] shrink-0 font-mono">
          {expanded ? '▴' : '▾'}
        </span>
      </button>

      {/* Expanded edit panel */}
      {expanded ? (
        <div className="border-t border-[#2a2f3a] relative overflow-hidden">
          {/* Ghost numeral — signature design element */}
          <span
            aria-hidden
            className="absolute right-3 top-0 text-[88px] font-bold leading-none text-[#2a2f3a] select-none pointer-events-none"
          >
            {String(scene.index + 1).padStart(2, '0')}
          </span>

          <div className="relative z-10 p-4 space-y-5">
            {/* Full image */}
            <div className="aspect-video bg-[#171a21] rounded-lg overflow-hidden flex items-center justify-center">
              {scene.media_path && scene.image_status === 'DONE' ? (
                <img
                  src={stableImageSrc(scene)}
                  alt={`Scene ${scene.index + 1}`}
                  className="w-full h-full object-cover"
                />
              ) : scene.image_status === 'RUNNING' ? (
                <div className="w-7 h-7 rounded-full border-2 border-[#f0a35e] border-t-transparent animate-spin" />
              ) : scene.image_status === 'FAILED' ? (
                <span className="text-[#f06a6a] text-2xl">✕</span>
              ) : (
                <span className="text-[#4a5568] text-xs">pending</span>
              )}
            </div>

            {/* Image prompt */}
            <div className="space-y-2">
              <label className="block text-xs text-[#9aa3b2]">Image prompt</label>
              <textarea
                value={mediaPrompt}
                onChange={e => setMediaPrompt(e.target.value)}
                rows={2}
                className={TEXTAREA_CLASS}
              />
              <Button
                disabled={isRegenerating}
                onClick={handleRegen}
                className="bg-transparent border border-[#2a2f3a] text-[#e7e9ee] text-xs px-3 py-2 rounded-lg hover:bg-[#252a35] disabled:opacity-50"
              >
                {isRegenerating ? 'Queuing…' : 'Regenerate image'}
              </Button>
            </div>

            {/* Narration + voice */}
            <div className="space-y-2">
              <label className="block text-xs text-[#9aa3b2]">Narration</label>
              <textarea
                value={narration}
                onChange={e => setNarration(e.target.value)}
                rows={2}
                className={TEXTAREA_CLASS}
              />
              <div className="flex items-center gap-2 flex-wrap">
                <select
                  value={voice}
                  onChange={e => setVoice(e.target.value)}
                  className="flex-1 min-w-[160px] bg-[#171a21] text-[#e7e9ee] border border-[#2a2f3a] rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-[#6ea8fe]"
                >
                  {VOICES.map(v => (
                    <option key={v.value} value={v.value}>
                      {v.label}
                    </option>
                  ))}
                </select>
                <Button
                  disabled={isRevoicing}
                  onClick={handleRevoice}
                  className="bg-transparent border border-[#2a2f3a] text-[#e7e9ee] text-xs px-3 py-2 rounded-lg hover:bg-[#252a35] disabled:opacity-50"
                >
                  {isRevoicing ? 'Queuing…' : 'Re-voice'}
                </Button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
})
