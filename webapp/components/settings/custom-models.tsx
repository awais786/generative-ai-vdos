'use client'

import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import type { ApiKey, Provider } from './api-keys'
import type { LLMModel } from '@/lib/project-types'
import { API } from '@/lib/routes'

interface Props {
  initialModels: LLMModel[]
  keys: ApiKey[]
  providers: Provider[]
}

const inputCls =
  'bg-[#0a0d14] border border-[#2a2f3a] rounded px-3 py-2 text-sm w-full text-[#e7e9ee] placeholder-[#5a6275] focus:outline-none focus:border-[#6ea8fe] transition-colors'

const ghostBtn =
  'text-xs border-[#2a2f3a] text-[#e7e9ee] bg-transparent hover:bg-[#1e222b]'

const CAPABILITIES = [
  { value: 'plan', label: 'Plan' },
  { value: 'image', label: 'Image' },
  { value: 'video', label: 'Video' },
]

export function CustomModelsPanel({ initialModels, keys, providers }: Props) {
  const [models, setModels] = useState<LLMModel[]>(initialModels.filter(m => m.owned))
  const [adding, setAdding] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [form, setForm] = useState({ provider: '', capability: 'image', model_id: '', display_name: '' })

  const providerMap = useMemo(() => new Map(providers.map(p => [p.id, p.name])), [providers])
  const keyedProviderIds = useMemo(() => new Set(keys.map(k => k.provider)), [keys])
  const keyedProviders = useMemo(
    () => providers.filter(p => keyedProviderIds.has(p.id)),
    [providers, keyedProviderIds],
  )

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    if (submitting) return
    setError('')
    setSubmitting(true)
    try {
      const res = await fetch(API.MODELS.LIST, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: Number(form.provider),
          capability: form.capability,
          model_id: form.model_id,
          display_name: form.display_name,
        }),
      })
      if (!res.ok) {
        setError('Something went wrong. Check the fields and try again.')
        return
      }
      const created: LLMModel = await res.json()
      setModels(prev => [...prev, created])
      setAdding(false)
      setForm({ provider: '', capability: 'image', model_id: '', display_name: '' })
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDelete(id: number) {
    setError('')
    const res = await fetch(API.MODELS.DETAIL(id), { method: 'DELETE' })
    if (!res.ok) { setError('Something went wrong. Try again.'); return }
    setModels(prev => prev.filter(m => m.id !== id))
  }

  const isEmpty = models.length === 0 && !adding

  return (
    <div className="rounded-lg border border-[#2a2f3a] overflow-hidden">
      {isEmpty && (
        <div className="flex flex-col items-center gap-3 py-10 px-5 text-center">
          <p className="text-sm text-[#9aa3b2]">No custom models yet.</p>
          <p className="text-xs text-[#5a6275] max-w-xs">
            Register a model_id under a provider you&apos;ve added a key for.
          </p>
          {keyedProviders.length > 0 && (
            <Button variant="outline" size="sm" onClick={() => { setAdding(true); setError('') }} className={ghostBtn}>
              + Add custom model
            </Button>
          )}
        </div>
      )}

      {models.map(m => (
        <div key={m.id} className="border-b border-[#2a2f3a] last:border-b-0 px-5 py-4 flex items-center gap-4">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-[#e7e9ee]">{m.display_name}</p>
            <p className="text-xs text-[#5a6275] mt-1">{m.provider} · {m.capability} · {m.model_id}</p>
          </div>
          {confirmDeleteId === m.id ? (
            <div className="flex items-center gap-1.5 shrink-0">
              <span className="text-xs text-[#9aa3b2]">Delete?</span>
              <Button variant="outline" size="sm" onClick={() => handleDelete(m.id)}
                className="text-xs border-red-800 text-red-400 bg-transparent hover:bg-red-950">Yes</Button>
              <Button variant="outline" size="sm" onClick={() => setConfirmDeleteId(null)} className={ghostBtn}>No</Button>
            </div>
          ) : (
            <Button variant="outline" size="sm" onClick={() => setConfirmDeleteId(m.id)}
              className="text-xs border-[#2a2f3a] text-red-400 bg-transparent hover:bg-[#1e222b] hover:text-red-300">
              Delete
            </Button>
          )}
        </div>
      ))}

      {adding ? (
        <form onSubmit={handleAdd} className={`${models.length > 0 ? 'border-t border-[#2a2f3a]' : ''} px-5 py-4 flex flex-col gap-3`}>
          <select required value={form.provider} onChange={e => setForm(f => ({ ...f, provider: e.target.value }))} className={inputCls}>
            <option value="">Select provider…</option>
            {keyedProviders.map(p => <option key={p.id} value={p.id}>{providerMap.get(p.id)}</option>)}
          </select>
          <select required value={form.capability} onChange={e => setForm(f => ({ ...f, capability: e.target.value }))} className={inputCls}>
            {CAPABILITIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          <input required type="text" placeholder="model_id (e.g. gpt-4o-mini-ft-xyz)" value={form.model_id}
            onChange={e => setForm(f => ({ ...f, model_id: e.target.value }))} className={inputCls} />
          <input required type="text" placeholder="Display name" value={form.display_name}
            onChange={e => setForm(f => ({ ...f, display_name: e.target.value }))} className={inputCls} />
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={submitting}>
              {submitting ? 'Adding…' : 'Add model'}
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => { setAdding(false); setError('') }} className={ghostBtn}>Cancel</Button>
          </div>
        </form>
      ) : !isEmpty && keyedProviders.length > 0 ? (
        <div className="border-t border-[#2a2f3a] px-5 py-3">
          <Button variant="outline" size="sm" onClick={() => { setAdding(true); setError('') }} className={ghostBtn}>
            + Add custom model
          </Button>
        </div>
      ) : null}

      {!adding && error && <p className="text-red-400 text-xs px-5 pb-4">{error}</p>}
    </div>
  )
}
