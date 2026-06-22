'use client'

import { useEffect, useRef } from 'react'
import { Project } from '@/lib/project-types'
import StatusPill from './status-pill'

interface Props {
  project: Project
  onUpdate: (updates: Partial<Project>) => void
}

export default function PlanningView({ project, onUpdate }: Props) {
  const onUpdateRef = useRef(onUpdate)
  onUpdateRef.current = onUpdate

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/projects/${project.id}/`)
        if (!res.ok) return
        const updated: Project = await res.json()
        if (updated.status !== 'DRAFT' && updated.status !== 'PLANNING') {
          clearInterval(interval)
          onUpdateRef.current(updated)
        }
      } catch {
        // network error — keep polling
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [project.id])

  return (
    <div className="flex flex-col items-center justify-center py-24 gap-8 max-w-sm mx-auto text-center">
      <StatusPill status={project.status === 'DRAFT' ? 'DRAFT' : 'PLANNING'} />

      {project.prompt ? (
        <p className="text-sm text-[#9aa3b2] italic leading-relaxed">
          &ldquo;{project.prompt}&rdquo;
        </p>
      ) : null}

      <div className="flex flex-col items-center gap-3">
        <div className="w-7 h-7 rounded-full border-2 border-[#6ea8fe] border-t-transparent animate-spin" />
        <p className="text-sm font-medium text-[#e7e9ee]">Generating your shot plan</p>
        <p className="text-xs text-[#4a5568]">Usually under a minute.</p>
      </div>
    </div>
  )
}
