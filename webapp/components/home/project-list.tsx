import { cookies } from 'next/headers'
import Link from 'next/link'

const DJANGO_ORIGIN = (process.env.DJANGO_ORIGIN ?? 'http://localhost:8000').replace(/\/$/, '')

const GRADIENTS = [
  'linear-gradient(135deg, #6ea8fe, #9b6efe)',
  'linear-gradient(135deg, #5cd6a4, #3a9bd6)',
  'linear-gradient(135deg, #f0a35e, #f06a6a)',
  'linear-gradient(135deg, #c06efe, #6e8efe)',
  'linear-gradient(135deg, #5cd6a4, #d6cf5c)',
]

function getGradient(id: string): string {
  const code = id.charCodeAt(id.length - 1)
  return GRADIENTS[code % GRADIENTS.length]
}

const STATUS_STYLES: Record<string, { color: string; border: string }> = {
  DRAFT:      { color: '#9aa3b2', border: '#2a2f3a' },
  PLANNING:   { color: '#f0a35e', border: '#5e472b' },
  REVIEW:     { color: '#6ea8fe', border: '#33507e' },
  GENERATING: { color: '#f0a35e', border: '#5e472b' },
  DONE:       { color: '#5cd6a4', border: '#2c5544' },
  FAILED:     { color: '#f06a6a', border: '#5e2b2b' },
}

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diffMs / 60_000)
  if (mins < 2) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return days === 1 ? 'yesterday' : `${days} days ago`
}

interface Project {
  id: string
  title: string
  status: string
  created_at: string
}

export default async function ProjectList() {
  const cookieStore = await cookies()
  const session = cookieStore.get('sessionid')

  let projects: Project[] = []
  let fetchError = false

  try {
    const res = await fetch(`${DJANGO_ORIGIN}/api/projects/`, {
      headers: { Cookie: `sessionid=${session?.value ?? ''}` },
      cache: 'no-store',
    })
    if (res.ok) {
      projects = await res.json()
    } else {
      fetchError = true
    }
  } catch {
    fetchError = true
  }

  if (fetchError) {
    return <p className="text-sm text-[#f06a6a]">Could not load projects.</p>
  }

  if (projects.length === 0) {
    return (
      <p className="text-sm text-[#9aa3b2]">
        No projects yet — create your first one above.
      </p>
    )
  }

  return (
    <div className="space-y-2.5">
      {projects.map(project => {
        const style = STATUS_STYLES[project.status] ?? STATUS_STYLES.DRAFT
        return (
          <Link
            key={project.id}
            href={`/projects/${project.id}`}
            className="flex items-center gap-3 px-3 py-3 rounded-[10px] border border-[#2a2f3a] bg-[#1e222b] hover:bg-[#252a35] transition-colors"
          >
            <span
              className="w-[34px] h-[34px] rounded-[7px] shrink-0"
              style={{ background: getGradient(project.id) }}
            />
            <span className="font-semibold text-[#e7e9ee] truncate flex-1 min-w-0">
              {project.title || 'Untitled'}
            </span>
            <span
              className="text-xs px-2.5 py-1 rounded-full border shrink-0"
              style={{ color: style.color, borderColor: style.border }}
            >
              {project.status.toLowerCase()}
            </span>
            <span className="text-sm text-[#9aa3b2] shrink-0">
              {relativeTime(project.created_at)}
            </span>
          </Link>
        )
      })}
    </div>
  )
}
