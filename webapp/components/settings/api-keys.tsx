'use client'

import { useMemo, useState, type Dispatch, type SetStateAction } from 'react'
import { Button } from '@/components/ui/button'

export interface Provider {
  id: number
  code: string
  name: string
}

export interface ApiKey {
  id: number
  provider: number
  key_hint: string
  label: string
  api_url: string
  created_at: string
}

interface Props {
  keys: ApiKey[]
  onKeysChange: Dispatch<SetStateAction<ApiKey[]>>
  providers: Provider[]
}

const inputCls =
  'bg-[#0a0d14] border border-[#2a2f3a] rounded px-3 py-2 text-sm w-full text-[#e7e9ee] placeholder-[#5a6275] focus:outline-none focus:border-[#6ea8fe] transition-colors'

const ghostBtn =
  'text-xs border-[#2a2f3a] text-[#e7e9ee] bg-transparent hover:bg-[#1e222b]'

export function ApiKeysPanel({ keys, onKeysChange: setKeys, providers }: Props) {
  const [adding, setAdding] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [form, setForm] = useState({ provider: '', api_key: '', label: '', api_url: '' })
  const [editForm, setEditForm] = useState({ api_key: '', label: '', api_url: '' })

  // js-index-maps: O(1) lookup instead of O(n) find on every render
  const providerMap = useMemo(
    () => new Map(providers.map(p => [p.id, p])),
    [providers],
  )
  const usedIds = useMemo(() => new Set(keys.map(k => k.provider)), [keys])
  const available = useMemo(
    () => providers.filter(p => !usedIds.has(p.id)),
    [providers, usedIds],
  )

  const providerName = (id: number) => providerMap.get(id)?.name ?? String(id)
  const isDashscope = (id: number) => providerMap.get(id)?.code === 'dashscope'

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    const res = await fetch('/api/auth/keys/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: Number(form.provider),
        api_key: form.api_key,
        label: form.label,
        api_url: form.api_url,
      }),
    })
    if (!res.ok) {
      const data: Record<string, unknown> = await res.json().catch(() => ({}))
      const nonField = data?.non_field_errors
      if (
        res.status === 400 &&
        Array.isArray(nonField) &&
        nonField.some((m: unknown) => typeof m === 'string' && m.toLowerCase().includes('unique'))
      ) {
        setError(`You already have a key for ${providerName(Number(form.provider))}.`)
      } else {
        setError('Something went wrong. Try again.')
      }
      return
    }
    const newKey: ApiKey = await res.json()
    setKeys(prev => [...prev, newKey])
    setAdding(false)
    setForm({ provider: '', api_key: '', label: '', api_url: '' })
  }

  async function handleDelete(id: number) {
    setError('')
    const res = await fetch(`/api/auth/keys/${id}/`, { method: 'DELETE' })
    if (!res.ok) { setError('Something went wrong. Try again.'); return }
    setKeys(prev => prev.filter(k => k.id !== id))
  }

  async function handleUpdate(e: React.FormEvent, id: number) {
    e.preventDefault()
    setError('')
    const body: Record<string, string> = { label: editForm.label, api_url: editForm.api_url }
    if (editForm.api_key) body.api_key = editForm.api_key
    const res = await fetch(`/api/auth/keys/${id}/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) { setError('Something went wrong. Try again.'); return }
    const updated: ApiKey = await res.json()
    setKeys(prev => prev.map(k => (k.id === id ? updated : k)))
    setEditingId(null)
    setEditForm({ api_key: '', label: '', api_url: '' })
  }

  const isEmpty = keys.length === 0 && !adding

  return (
    <div className="rounded-lg border border-[#2a2f3a] overflow-hidden">

      {/* Empty state — shows CTA inline so user immediately knows what to do */}
      {isEmpty && (
        <div className="flex flex-col items-center gap-3 py-10 px-5 text-center">
          <p className="text-sm text-[#9aa3b2]">No API keys yet.</p>
          <p className="text-xs text-[#5a6275] max-w-xs">
            Add a provider key to use your own account quotas when generating videos.
          </p>
          {available.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => { setAdding(true); setError('') }}
              className={ghostBtn}
            >
              + Add API key
            </Button>
          )}
        </div>
      )}

      {/* Key rows */}
      {keys.map(key => (
        <div key={key.id} className="border-b border-[#2a2f3a] last:border-b-0">
          {editingId === key.id ? (
            <form onSubmit={e => handleUpdate(e, key.id)} className="px-5 py-4 flex flex-col gap-3">
              <p className="text-sm font-medium text-[#e7e9ee]">{providerName(key.provider)}</p>
              <input
                type="password"
                placeholder="New API key (leave blank to keep current)"
                value={editForm.api_key}
                onChange={e => setEditForm(f => ({ ...f, api_key: e.target.value }))}
                className={inputCls}
              />
              <input
                type="text"
                placeholder="Label (optional)"
                value={editForm.label}
                onChange={e => setEditForm(f => ({ ...f, label: e.target.value }))}
                className={inputCls}
              />
              {isDashscope(key.provider) && (
                <input
                  type="url"
                  placeholder="Workspace API URL (optional)"
                  value={editForm.api_url}
                  onChange={e => setEditForm(f => ({ ...f, api_url: e.target.value }))}
                  className={inputCls}
                />
              )}
              {error && <p className="text-red-400 text-xs">{error}</p>}
              <div className="flex gap-2">
                <Button type="submit" size="sm">Save</Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => { setEditingId(null); setError('') }}
                  className={ghostBtn}
                >
                  Cancel
                </Button>
              </div>
            </form>
          ) : (
            <div className="px-5 py-4 flex items-center gap-4">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-[#e7e9ee]">{providerName(key.provider)}</p>
                <div className="flex items-center gap-2 mt-1.5">
                  {/* Signature element: key hint as a masked credential chip */}
                  <span className="inline-block font-mono text-xs tracking-wider text-[#9aa3b2] bg-[#0a0d14] border border-[#2a2f3a] rounded px-2 py-0.5">
                    {key.key_hint}
                  </span>
                  {key.label && (
                    <span className="text-xs text-[#5a6275]">{key.label}</span>
                  )}
                  {isDashscope(key.provider) && key.api_url && (
                    <span className="text-xs text-[#5a6275] truncate">{key.api_url}</span>
                  )}
                </div>
              </div>
              <p className="text-xs text-[#5a6275] shrink-0 tabular-nums">
                {new Date(key.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setEditingId(key.id)
                  setEditForm({ api_key: '', label: key.label, api_url: key.api_url })
                  setConfirmDeleteId(null)
                  setError('')
                }}
                className={ghostBtn}
              >
                Edit
              </Button>
              {confirmDeleteId === key.id ? (
                <div className="flex items-center gap-1.5 shrink-0">
                  <span className="text-xs text-[#9aa3b2]">Delete?</span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleDelete(key.id)}
                    className="text-xs border-red-800 text-red-400 bg-transparent hover:bg-red-950"
                  >
                    Yes
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setConfirmDeleteId(null)}
                    className={ghostBtn}
                  >
                    No
                  </Button>
                </div>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setConfirmDeleteId(key.id)}
                  className="text-xs border-[#2a2f3a] text-red-400 bg-transparent hover:bg-[#1e222b] hover:text-red-300"
                >
                  Delete
                </Button>
              )}
            </div>
          )}
        </div>
      ))}

      {/* Add form */}
      {adding ? (
        <form
          onSubmit={handleAdd}
          className={`${keys.length > 0 ? 'border-t border-[#2a2f3a]' : ''} px-5 py-4 flex flex-col gap-3`}
        >
          <select
            required
            value={form.provider}
            onChange={e => setForm(f => ({ ...f, provider: e.target.value, api_url: '' }))}
            className={inputCls}
          >
            <option value="">Select provider…</option>
            {available.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <input
            required
            type="password"
            placeholder="API key"
            value={form.api_key}
            onChange={e => setForm(f => ({ ...f, api_key: e.target.value }))}
            className={inputCls}
          />
          <input
            type="text"
            placeholder="Label (optional)"
            value={form.label}
            onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
            className={inputCls}
          />
          {form.provider !== '' && isDashscope(Number(form.provider)) && (
            <input
              type="url"
              placeholder="Workspace API URL (optional)"
              value={form.api_url}
              onChange={e => setForm(f => ({ ...f, api_url: e.target.value }))}
              className={inputCls}
            />
          )}
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <div className="flex gap-2">
            <Button type="submit" size="sm">Add key</Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => { setAdding(false); setError('') }}
              className={ghostBtn}
            >
              Cancel
            </Button>
          </div>
        </form>
      ) : !isEmpty && available.length > 0 ? (
        <div className="border-t border-[#2a2f3a] px-5 py-3">
          <Button
            variant="outline"
            size="sm"
            onClick={() => { setAdding(true); setError('') }}
            className={ghostBtn}
          >
            + Add API key
          </Button>
        </div>
      ) : null}

      {!adding && editingId === null && error && (
        <p className="text-red-400 text-xs px-5 pb-4">{error}</p>
      )}
    </div>
  )
}
