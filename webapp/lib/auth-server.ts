import { cache } from 'react'
import { cookies } from 'next/headers'
import { API } from '@/lib/routes'

const DJANGO_ORIGIN = (process.env.DJANGO_ORIGIN ?? 'http://localhost:8000').replace(/\/$/, '')

export interface UserProfile {
  id: number
  cognito_sub: string
  email: string
  name: string
  created_at: string
}

export const getUser = cache(async (): Promise<UserProfile | null> => {
  const cookieStore = await cookies()
  const session = cookieStore.get('sessionid')
  if (!session) return null

  const res = await fetch(`${DJANGO_ORIGIN}${API.AUTH.ME}`, {
    headers: { Cookie: `sessionid=${session.value}` },
    cache: 'no-store',
  })
  if (res.status === 401 || res.status === 403) return null
  if (!res.ok) {
    throw new Error(`Failed to fetch user profile: ${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<UserProfile>
})
