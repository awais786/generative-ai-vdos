'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { Project } from '@/lib/project-types'
import { Button } from '@/components/ui/button'
import StatusPill from './status-pill'

interface Props {
  project: Project
  onUpdate: (updates: Partial<Project>) => void
}

export default function FailedView({ project, onUpdate }: Props) {
  const router = useRouter()
  const [isRetrying, startRetry] = useTransition()
  const [retryError, setRetryError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [isDeleting, startDelete] = useTransition()

  function handleRetry() {
    setRetryError(null)
    startRetry(async () => {
      const res = await fetch(`/api/projects/${project.id}/retry/`, {
        method: 'POST',
      })
      if (res.ok || res.status === 202) {
        onUpdate({ status: 'GENERATING', error: '' })
      } else if (res.status === 429) {
        const body = await res.json().catch(() => ({}))
        setRetryError(
          body.code === 'budget_exceeded'
            ? 'Daily generation limit reached. Resets at 00:00 UTC.'
            : `Rate limit hit — try again in ${res.headers.get('Retry-After') ?? 'a moment'}.`
        )
      }
    })
  }

  function handleDelete() {
    startDelete(async () => {
      const res = await fetch(`/api/projects/${project.id}/`, { method: 'DELETE' })
      if (res.status === 204) { router.refresh(); router.push('/home') }
    })
  }

  return (
    <div className="py-6 space-y-5">
      <div className="flex items-center justify-between gap-3">
        <StatusPill status="FAILED" />
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
        {retryError && (
          <p className="text-xs text-[#f0a35e]">{retryError}</p>
        )}
      </div>
    </div>
  )
}
