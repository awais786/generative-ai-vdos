export function getActionErrorMessage(
  res: Response,
  body: { detail?: string; code?: string },
  fallback: string,
): string {
  if (res.status === 429) {
    return body.code === 'budget_exceeded'
      ? 'Daily generation limit reached. Resets at 00:00 UTC.'
      : `Rate limit hit — try again in ${res.headers.get('Retry-After') ?? 'a moment'}.`
  }
  return body.detail ?? fallback
}
