import { headers } from 'next/headers'
import type { NextRequest } from 'next/server'
import { redirect } from 'next/navigation'

function originFromHeaders(
  get: (name: string) => string | null,
): string | null {
  const host = get('x-forwarded-host') ?? get('host')
  const proto = get('x-forwarded-proto') ?? 'http'
  if (!host) return null
  return `${proto}://${host.split(',')[0].trim()}`
}

/** Public site origin when Next.js runs behind nginx (Edge middleware). */
export function publicOrigin(request: NextRequest): string {
  return originFromHeaders((name) => request.headers.get(name)) ?? request.nextUrl.origin
}

export function publicUrl(request: NextRequest, path: string): URL {
  return new URL(path, publicOrigin(request))
}

/** Public site origin for Server Components / route handlers. */
export function publicOriginFromHeaders(): string | null {
  const h = headers()
  return originFromHeaders((name) => h.get(name))
}

/** Proxy-aware redirect for Server Components. */
export function redirectTo(path: string): never {
  const origin = publicOriginFromHeaders()
  redirect(origin ? `${origin}${path}` : path)
}
