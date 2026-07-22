'use client'

import { memo, useCallback, useEffect, useRef, useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { Project, Scene } from '@/lib/project-types'
import { Button } from '@/components/ui/button'
import StatusPill from './status-pill'

interface Props {
  project: Project
  onUpdate: (updates: Partial<Project>) => void
}

function stableMediaSrc(scene: Scene): string | undefined {
  if (!scene.media_path) return undefined
  if (scene.media_path.includes('?')) return scene.media_path
  return `${scene.media_path}?v=${encodeURIComponent(scene.updated_at ?? '')}`
}

function isVideo(path: string): boolean {
  return path.split('?')[0].endsWith('.mp4')
}

const IMG_STATUS_COLOR: Record<string, string> = {
  PENDING: '#9aa3b2',
  RUNNING: '#f0a35e',
  DONE:    '#5cd6a4',
  FAILED:  '#f06a6a',
}

const TEXTAREA_CLASS =
  'w-full bg-[#171a21] text-[#e7e9ee] border border-[#2a2f3a] rounded-lg px-3 py-2 text-sm resize-y focus:outline-none focus:ring-1 focus:ring-[#6ea8fe]'

export default function ImageReviewView({ project, onUpdate }: Props) {
  const router = useRouter()
  const [scenes, setScenes] = useState<Scene[]>(project.scenes)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [isApproving, startApprove] = useTransition()
  const [isDeleting, startDelete] = useTransition()

  const allDone = scenes.every(s => s.media_status === 'DONE')

  function handleDelete() {
    startDelete(async () => {
      const res = await fetch(`/api/projects/${project.id}/`, { method: 'DELETE' })
      if (res.status === 204) { router.refresh(); router.push('/home') }
    })
  }

  function handleApprove() {
    startApprove(async () => {
      const res = await fetch(`/api/projects/${project.id}/approve-images/`, {
        method: 'POST',
      })
      if (res.ok) {
        const updated: Project = await res.json()
        onUpdate(updated)
      }
    })
  }

  const updateSceneStatus = useCallback(
    (index: number, media_status: Scene['media_status']) => {
      setScenes(prev =>
        prev.map(s => (s.index === index ? { ...s, media_status } : s)),
      )
    },
    [],
  )

  const updateScene = useCallback((updated: Scene) => {
    setScenes(prev => prev.map(s => s.index === updated.index ? updated : s))
  }, [])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <StatusPill status="IMAGE_REVIEW" />
        <div className="flex items-center gap-2">
          <Button
            disabled={!allDone || isApproving}
            onClick={handleApprove}
            title={!allDone ? 'Regenerate failed scenes first' : undefined}
            className="bg-[#5cd6a4] text-[#0d1117] font-medium text-xs px-3 py-1.5 rounded-lg hover:bg-[#4bc494] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {isApproving ? 'Approving…' : 'Approve all & generate voiceover'}
          </Button>
          {confirmDelete ? (
            <>
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
            </>
          ) : (
            <Button
              onClick={() => setConfirmDelete(true)}
              className="bg-transparent border border-[#f06a6a]/40 text-[#f06a6a] text-xs px-3 py-1.5 rounded-lg hover:bg-[#f06a6a]/10"
            >
              Delete project
            </Button>
          )}
        </div>
      </div>

      {/* Eyebrow */}
      <div>
        <p className="text-[10px] uppercase tracking-[0.2em] font-medium text-[#4a5568]">
          Review your scenes
        </p>
        <p className="text-xs text-[#9aa3b2] mt-1">
          Regenerate any scene before approving
        </p>
      </div>

      {/* Scene cards */}
      <div className="space-y-2">
        {scenes.map(scene => (
          <ReviewSceneCard
            key={scene.id}
            scene={scene}
            projectId={project.id}
            onStatusChange={updateSceneStatus}
            onSceneUpdate={updateScene}
          />
        ))}
      </div>
    </div>
  )
}

const ReviewSceneCard = memo(function ReviewSceneCard({
  scene,
  projectId,
  onStatusChange,
  onSceneUpdate,
}: {
  scene: Scene
  projectId: string
  onStatusChange: (index: number, status: Scene['media_status']) => void
  onSceneUpdate: (updated: Scene) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [mediaPrompt, setMediaPrompt] = useState(scene.media_prompt)
  const [regenError, setRegenError] = useState<string | null>(null)
  const [isRegenerating, startRegen] = useTransition()
  const mediaPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => () => {
    if (mediaPollRef.current) clearInterval(mediaPollRef.current)
  }, [])

  const imgColor = IMG_STATUS_COLOR[scene.media_status] ?? '#9aa3b2'

  function handleRegen() {
    setRegenError(null)
    startRegen(async () => {
      const res = await fetch(`/api/projects/${projectId}/scenes/${scene.index}/regenerate/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: mediaPrompt }),
      })
      if (!res.ok) {
        if (res.status === 429) {
          const body = await res.json().catch(() => ({}))
          setRegenError(
            body.code === 'budget_exceeded'
              ? 'Daily generation limit reached. Resets at 00:00 UTC.'
              : `Rate limit hit — try again in ${res.headers.get('Retry-After') ?? 'a moment'}.`
          )
        }
        return
      }
      onStatusChange(scene.index, 'RUNNING')
      if (mediaPollRef.current) clearInterval(mediaPollRef.current)
      mediaPollRef.current = setInterval(async () => {
        try {
          const r = await fetch(`/api/projects/${projectId}/scenes/${scene.index}/`)
          if (!r.ok) return
          const updated: Scene = await r.json()
          onStatusChange(scene.index, updated.media_status)
          if (updated.media_status === 'DONE' || updated.media_status === 'FAILED') {
            clearInterval(mediaPollRef.current!)
            mediaPollRef.current = null
            onSceneUpdate(updated)
          }
        } catch { /* keep polling */ }
      }, 2000)
    })
  }

  return (
    <div className="bg-[#1e222b] border border-[#2a2f3a] rounded-[10px] overflow-hidden">
      {/* Collapsed header */}
      <button
        type="button"
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-[#252a35] transition-colors text-left"
      >
        <div className="w-16 h-10 rounded bg-[#171a21] shrink-0 overflow-hidden flex items-center justify-center">
          {scene.media_path && scene.media_status === 'DONE' ? (
            isVideo(scene.media_path) ? (
              <div className="relative w-full h-full">
                <video
                  src={stableMediaSrc(scene)}
                  playsInline
                  className="w-full h-full object-cover"
                />
                <div className="absolute inset-0 flex items-center justify-center">
                  <div className="w-5 h-5 rounded-full bg-black/50 flex items-center justify-center">
                    <span className="text-white text-[8px] pl-0.5">▶</span>
                  </div>
                </div>
              </div>
            ) : (
              <img
                src={stableMediaSrc(scene)}
                alt=""
                className="w-full h-full object-cover"
              />
            )
          ) : scene.media_status === 'RUNNING' ? (
            <div className="w-4 h-4 rounded-full border border-[#f0a35e] border-t-transparent animate-spin" />
          ) : (
            <span className="text-[#4a5568] text-[10px]">
              {scene.media_status.toLowerCase()}
            </span>
          )}
        </div>
        <span className="text-xs font-mono text-[#9aa3b2] shrink-0">
          {String(scene.index + 1).padStart(2, '0')}
        </span>
        <span
          className="w-1.5 h-1.5 rounded-full shrink-0"
          style={{ backgroundColor: imgColor }}
        />
        <span className="text-xs text-[#9aa3b2] truncate flex-1">
          {scene.narration}
        </span>
        <span className="text-[10px] text-[#4a5568] shrink-0 font-mono">
          {expanded ? '▴' : '▾'}
        </span>
      </button>

      {/* Expanded panel */}
      {expanded ? (
        <div className="border-t border-[#2a2f3a] relative overflow-hidden">
          <span
            aria-hidden
            className="absolute right-3 top-0 text-[88px] font-bold leading-none text-[#2a2f3a] select-none pointer-events-none"
          >
            {String(scene.index + 1).padStart(2, '0')}
          </span>
          <div className="relative z-10 p-4 space-y-5">
            {/* Full image preview */}
            <div className="aspect-video bg-[#171a21] rounded-lg overflow-hidden flex items-center justify-center">
              {scene.media_path && scene.media_status === 'DONE' ? (
                isVideo(scene.media_path) ? (
                  <video
                    src={stableMediaSrc(scene)}
                    controls
                    autoPlay
                    muted
                    loop
                    playsInline
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <img
                    src={stableMediaSrc(scene)}
                    alt={`Scene ${scene.index + 1}`}
                    className="w-full h-full object-cover"
                  />
                )
              ) : scene.media_status === 'RUNNING' ? (
                <div className="w-7 h-7 rounded-full border-2 border-[#f0a35e] border-t-transparent animate-spin" />
              ) : scene.media_status === 'FAILED' ? (
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
                disabled={isRegenerating || scene.media_status === 'RUNNING'}
                onClick={handleRegen}
                className="bg-transparent border border-[#2a2f3a] text-[#e7e9ee] text-xs px-3 py-2 rounded-lg hover:bg-[#252a35] disabled:opacity-50"
              >
                {isRegenerating || scene.media_status === 'RUNNING' ? 'Generating…' : 'Regenerate scene'}
              </Button>
              {regenError && (
                <p className="text-xs text-[#f0a35e] mt-1">{regenError}</p>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
})
