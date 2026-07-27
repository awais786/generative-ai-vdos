import Link from 'next/link'
import { cookies } from 'next/headers'
import { notFound } from 'next/navigation'
import { Project } from '@/lib/project-types'
import ProjectPage from '@/components/project/project-page'
import { API, ROUTES } from '@/lib/routes'

const DJANGO_ORIGIN = (
  process.env.DJANGO_ORIGIN ?? 'http://localhost:8000'
).replace(/\/$/, '')

export default async function ProjectDetailPage({
  params,
}: {
  params: { id: string }
}) {
  const { id } = params
  const cookieStore = await cookies()
  const session = cookieStore.get('sessionid')

  const res = await fetch(`${DJANGO_ORIGIN}${API.PROJECTS.DETAIL(id)}`, {
    headers: { Cookie: `sessionid=${session?.value ?? ''}` },
    cache: 'no-store',
  })

  if (res.status === 404) notFound()
  if (!res.ok) throw new Error(`Failed to load project: ${res.status}`)

  const project: Project = await res.json()


  return (
    <>
      <Link href={ROUTES.HOME} className="flex w-fit items-center gap-1 text-sm text-[#9aa3b2] hover:text-[#e7e9ee] transition-colors mb-6">
        ← Back
      </Link>

      <ProjectPage initialProject={project} />
    </>
  )
}
