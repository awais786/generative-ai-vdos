'use client'

import { useEffect, useRef, useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { Project, Scene } from '@/lib/project-types'
import { Button } from '@/components/ui/button'
import SceneGrid from './scene-grid'
import StatusPill from './status-pill'
import { API, ROUTES } from '@/lib/routes'

interface Props {
  project: Project
  onUpdate: (updates: Partial<Project>) => void
}

interface LogEntry {
  id: number
  stage: string
  level: 'info' | 'warn' | 'error'
  message: string
}

const LEVEL_COLOR: Record<string, string> = {
  info: '#9aa3b2',
  warn: '#f0a35e',
  error: '#f06a6a',
}

const BASE_INTERVAL = 3000
const MAX_INTERVAL = 8000

export default function GeneratingView({ project, onUpdate }: Props) {
  const router = useRouter()
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [scenes, setScenes] = useState<Scene[]>(project.scenes)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [isDeleting, startDelete] = useTransition()
  const logEndRef = useRef<HTMLDivElement>(null)
  const onUpdateRef = useRef(onUpdate)
  onUpdateRef.current = onUpdate

  function handleDelete() {
    startDelete(async () => {
      const res = await fetch(API.PROJECTS.DETAIL(project.id), { method: 'DELETE' })
      if (res.status === 204) { router.refresh(); router.push(ROUTES.HOME) }
    })
  }

  useEffect(() => {
    let done = false
    let lastLogId = 0
    let emptyCount = 0
    let currentDelay = BASE_INTERVAL
    let timerId: ReturnType<typeof setTimeout>
    let inFlight = false

    function scheduleNext() {
      if (done) return
      timerId = setTimeout(tick, currentDelay)
    }

    async function tick() {
      if (done) return
      if (inFlight) return

      // Pause while the tab is hidden; resume on visibilitychange (below).
      if (document.visibilityState === 'hidden') return

      inFlight = true
      try {
        const [projectRes, logsRes] = await Promise.all([
          fetch(API.PROJECTS.DETAIL(project.id)),
          fetch(API.PROJECTS.LOGS(project.id, lastLogId)),
        ])

        if (projectRes.ok) {
          const updated: Project = await projectRes.json()
          setScenes(updated.scenes)
          if (!['GENERATING', 'VIDEO_GENERATING'].includes(updated.status)) {
            done = true
            inFlight = false
            onUpdateRef.current(updated)
            return
          }
        }

        if (logsRes.ok) {
          const newLogs: LogEntry[] = await logsRes.json()
          if (newLogs.length > 0) {
            lastLogId = newLogs[newLogs.length - 1].id
            setLogs(prev => [...prev, ...newLogs])
            emptyCount = 0
            currentDelay = BASE_INTERVAL
          } else {
            emptyCount++
            // Exponential backoff capped at MAX_INTERVAL (8 s) so stage
            // transitions (e.g., arriving at IMAGE_REVIEW) don't feel sluggish.
            currentDelay = Math.min(BASE_INTERVAL * Math.pow(1.5, emptyCount), MAX_INTERVAL)
          }
        }
      } catch {
        // Network error — keep polling at current interval.
      }

      inFlight = false
      scheduleNext()
    }

    function onVisibilityChange() {
      if (document.visibilityState === 'visible') {
        // Reset backoff so the user sees fresh data quickly on tab return.
        emptyCount = 0
        currentDelay = BASE_INTERVAL
        clearTimeout(timerId)
        tick()
      }
    }

    document.addEventListener('visibilitychange', onVisibilityChange)
    scheduleNext()

    return () => {
      done = true
      clearTimeout(timerId)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [project.id])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <StatusPill status="GENERATING" />
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

      {/* Side-by-side on lg+: log panel left, scene grid right */}
      <div className="grid grid-cols-1 lg:grid-cols-[2fr_3fr] gap-5 items-start">
        {/* Log terminal */}
        <div className="lg:sticky lg:top-6">
          <p className="text-[10px] uppercase tracking-[0.2em] font-medium text-[#4a5568] mb-2">
            Pipeline log
          </p>
          <div className="bg-[#1e222b] border border-[#2a2f3a] rounded-[10px] p-4 h-64 overflow-y-auto font-mono text-xs space-y-1">
            {logs.length === 0 ? (
              <p className="text-[#4a5568]">Waiting for events…</p>
            ) : (
              logs.map(log => (
                <p key={log.id} style={{ color: LEVEL_COLOR[log.level] }}>
                  <span className="text-[#4a5568]">[{log.stage}]</span>{' '}
                  {log.message}
                </p>
              ))
            )}
            <div ref={logEndRef} />
          </div>
        </div>

        {/* Scene thumbnails */}
        <div>
          <p className="text-[10px] uppercase tracking-[0.2em] font-medium text-[#4a5568] mb-2">
            Scenes
          </p>
          {scenes.length > 0 ? (
            <SceneGrid scenes={scenes} />
          ) : (
            <p className="text-xs text-[#4a5568]">Scene images will appear here.</p>
          )}
        </div>
      </div>
    </div>
  )
}
