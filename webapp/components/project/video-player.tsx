'use client'

import { useTransition } from 'react'
import { Button } from '@/components/ui/button'
import { Project } from '@/lib/project-types'

interface Props {
  projectId: string
  stale: boolean
  onRebuild: (updated: Project) => void
}

export default function VideoPlayer({ projectId, stale, onRebuild }: Props) {
  const [isRebuilding, startRebuild] = useTransition()

  function handleRebuild() {
    startRebuild(async () => {
      const res = await fetch(`/api/projects/${projectId}/reassemble/`, {
        method: 'POST',
      })
      const updated: Project = await res.json()
      onRebuild(updated)
    })
  }

  return (
    <div className="bg-[#1e222b] border border-[#2a2f3a] rounded-[10px] overflow-hidden">
      <video
        controls
        className="w-full aspect-video bg-black"
        src={`/api/projects/${projectId}/download/`}
      >
        Your browser does not support video playback.
      </video>
      <div className="p-4 flex items-center justify-between gap-4 flex-wrap">
        <a
          href={`/api/projects/${projectId}/download/`}
          download="final.mp4"
          className="text-sm text-[#6ea8fe] hover:text-[#5a97f0] underline underline-offset-2"
        >
          Download final.mp4
        </a>
        <Button
          disabled={isRebuilding}
          onClick={handleRebuild}
          className={
            stale
              ? 'bg-[#f0a35e] text-[#0a0d14] font-semibold text-sm px-4 py-2.5 rounded-lg hover:bg-[#d8924f] disabled:opacity-50'
              : 'bg-transparent border border-[#2a2f3a] text-[#e7e9ee] text-sm px-4 py-2.5 rounded-lg hover:bg-[#252a35] disabled:opacity-50'
          }
        >
          {isRebuilding ? 'Rebuilding…' : stale ? 'Rebuild video ●' : 'Rebuild video'}
        </Button>
      </div>
    </div>
  )
}
