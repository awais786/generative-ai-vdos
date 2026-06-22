'use client'

import { useTransition } from 'react'
import { Project } from '@/lib/project-types'
import { Button } from '@/components/ui/button'
import StatusPill from './status-pill'

interface Props {
  project: Project
  onUpdate: (updates: Partial<Project>) => void
}

export default function FailedView({ project, onUpdate }: Props) {
  const [isRetrying, startRetry] = useTransition()

  function handleRetry() {
    startRetry(async () => {
      const res = await fetch(`/api/projects/${project.id}/approve/`, {
        method: 'POST',
      })
      if (res.ok || res.status === 202) {
        onUpdate({ status: 'GENERATING', error: '' })
      }
    })
  }

  return (
    <div className="py-6 space-y-5">
      <StatusPill status="FAILED" />

      <div className="bg-[#1e222b] border border-[#f06a6a]/30 rounded-[10px] p-5 space-y-4">
        <p className="text-sm font-medium text-[#e7e9ee]">Generation failed</p>

        {project.error ? (
          <pre className="text-xs text-[#9aa3b2] font-mono break-all whitespace-pre-wrap bg-[#171a21] border border-[#2a2f3a] rounded-lg px-3 py-2.5">
            {project.error}
          </pre>
        ) : (
          <p className="text-sm text-[#9aa3b2]">
            An unexpected error occurred. Check the pipeline logs for details.
          </p>
        )}

        <Button
          disabled={isRetrying}
          onClick={handleRetry}
          className="bg-[#6ea8fe] text-[#0a0d14] font-semibold text-sm px-4 py-2.5 rounded-lg hover:bg-[#5a97f0] disabled:opacity-50"
        >
          {isRetrying ? 'Retrying…' : 'Retry generation'}
        </Button>
      </div>
    </div>
  )
}
