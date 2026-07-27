'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { Project, Scene } from '@/lib/project-types'
import { Button } from '@/components/ui/button'
import VideoPlayer from './video-player'
import StatusPill from './status-pill'
import { API, ROUTES } from '@/lib/routes'

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

export default function DoneView({ project, onUpdate }: Props) {
  const router = useRouter()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [isDeleting, startDelete] = useTransition()

  function handleDelete() {
    startDelete(async () => {
      const res = await fetch(API.PROJECTS.DETAIL(project.id), { method: 'DELETE' })
      if (res.status === 204) { router.refresh(); router.push(ROUTES.HOME) }
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

      <VideoPlayer
        projectId={project.id}
        stale={project.stale}
        onRebuild={(updated) => onUpdate(updated)}
      />

      <div>
        <p className="text-[10px] uppercase tracking-[0.2em] font-medium text-[#4a5568] mb-2">
          Scenes
        </p>
        <div className="space-y-2">
          {project.scenes.map(scene => (
            <div
              key={scene.id}
              className="bg-[#1e222b] border border-[#2a2f3a] rounded-[10px] flex items-center gap-3 px-3 py-2.5"
            >
              <div className="w-16 h-10 rounded bg-[#171a21] shrink-0 overflow-hidden flex items-center justify-center">
                {scene.media_path ? (
                  isVideo(scene.media_path) ? (
                    <video
                      src={stableMediaSrc(scene)}
                      playsInline
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <img
                      src={stableMediaSrc(scene)}
                      alt=""
                      className="w-full h-full object-cover"
                    />
                  )
                ) : (
                  <span className="text-[#4a5568] text-[10px]">none</span>
                )}
              </div>
              <span className="text-xs font-mono text-[#9aa3b2] shrink-0">
                {String(scene.index + 1).padStart(2, '0')}
              </span>
              <span className="text-xs text-[#9aa3b2] truncate flex-1">
                {scene.narration}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
