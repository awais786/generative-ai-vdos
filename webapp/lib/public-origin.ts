import { headers } from 'next/headers'
import type { NextRequest } from 'next/server'
import { redirect } from 'next/navigation'

/** Resolve the public origin from proxy headers, or null when host is missing. */
function originFromHeaders(
  get: (name: string) => string | null,
): string | null {
  const host = get('x-forwarded-host') ?? get('host')
  // Reverse proxies may send comma-separated lists; first value is client-facing.
  const proto = (get('x-forwarded-proto') ?? 'http').split(',')[0].trim()
  if (!host) return null
  return `${proto}://${host.split(',')[0].trim()}`
}

/** Public site origin when Next.js runs behind nginx (Edge middleware). */
export function publicOrigin(request: NextRequest): string {
  return originFromHeaders((name) => request.headers.get(name)) ?? request.nextUrl.origin
}

/** Build an absolute URL on the public site origin (Edge middleware). */
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
