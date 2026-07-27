'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import type { LLMModel } from '@/lib/project-types'
import { API, ROUTES } from '@/lib/routes'

interface ProjectFormProps {
  imageModels: LLMModel[]
  videoModels: LLMModel[]
}

const VOICES = [
  { value: 'en-US-AndrewNeural', label: 'Andrew (US Male)' },
  { value: 'en-US-RyanNeural', label: 'Ryan (US Male)' },
  { value: 'en-US-AvaNeural', label: 'Ava (US Female)' },
]

const MUSIC_MOODS = [
  { value: 'calm', label: 'Calm' },
  { value: 'upbeat', label: 'Upbeat' },
  { value: 'dramatic', label: 'Dramatic' },
  { value: 'mysterious', label: 'Mysterious' },
  { value: 'inspiring', label: 'Inspiring' },
]

const SELECT_CLASS =
  'w-full bg-[#1e222b] text-[#e7e9ee] border border-[#2a2f3a] rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-[#6ea8fe]'

export default function ProjectForm({ imageModels, videoModels }: ProjectFormProps) {
  const router = useRouter()
  const [isPending, startTransition] = useTransition()
  const [prompt, setPrompt] = useState('')

  const [imageModel, setImageModel] = useState(imageModels[0]?.model_id ?? '')
  const [videModel, setVideModel] = useState(videoModels[0]?.model_id ?? '')
  const [voice, setVoice] = useState('en-US-AndrewNeural')
  const [music, setMusic] = useState('calm')
  const [animate, setAnimate] = useState(false)
  const [promptError, setPromptError] = useState('')
  const [submitError, setSubmitError] = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setPromptError('')
    setSubmitError('')

    if (!prompt.trim()) {
      setPromptError('Please describe an idea for your video.')
      return
    }

    startTransition(async () => {
      try {
        const body: Record<string, unknown> = {
          prompt: prompt.trim(),
          narrator_voice: voice,
          music,
          animate,
        }
        body.image_model = imageModel
        body.video_model = videModel

        const res = await fetch(API.PROJECTS.LIST, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })

        if (res.status === 201) {
          const data = await res.json()
          router.refresh()
          router.push(ROUTES.PROJECT(data.id))
          return
        }

        const data: { detail?: string } = await res.json().catch(() => ({}))
        setSubmitError(data.detail ?? 'Something went wrong. Please try again.')
      } catch {
        setSubmitError('Network error. Please try again.')
      }
    })
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-[#171a21] border border-[#2a2f3a] rounded-[12px] p-[18px] space-y-4"
    >
      <div>
        <label className="block text-xs text-[#9aa3b2] mb-1.5">Idea</label>
        <textarea
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          placeholder="a lonely lighthouse keeper befriends a storm petrel during a winter gale"
          rows={3}
          className="w-full bg-[#1e222b] text-[#e7e9ee] border border-[#2a2f3a] rounded-lg px-3 py-2.5 text-sm resize-y focus:outline-none focus:ring-1 focus:ring-[#6ea8fe] placeholder:text-[#4a5568]"
        />
        {promptError ? (
          <p className="text-xs text-[#f06a6a] mt-1">{promptError}</p>
        ) : null}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div>
          <label className="block text-xs text-[#9aa3b2] mb-1.5">Image model</label>
          <select
            value={imageModel}
            onChange={e => setImageModel(e.target.value)}
            className={SELECT_CLASS}
          >
            {imageModels.map(opt => (
              <option key={opt.id} value={opt.model_id}>
                {opt.display_name}{opt.is_free ? ' — free' : ''}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-[#9aa3b2] mb-1.5">Video model</label>
          <select
            value={videModel}
            onChange={e => setVideModel(e.target.value)}
            className={SELECT_CLASS}
          >
            {videoModels.map(opt => (
              <option key={opt.id} value={opt.model_id}>
                {opt.display_name}{opt.is_free ? ' — free' : ''}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-[#9aa3b2] mb-1.5">Narrator voice</label>
          <select
            value={voice}
            onChange={e => setVoice(e.target.value)}
            className={SELECT_CLASS}
          >
            {VOICES.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-[#9aa3b2] mb-1.5">Music mood</label>
          <select
            value={music}
            onChange={e => setMusic(e.target.value)}
            className={SELECT_CLASS}
          >
            {MUSIC_MOODS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <label className="flex items-center gap-2 text-sm text-[#e7e9ee] cursor-pointer select-none">
          <input
            type="checkbox"
            checked={animate}
            onChange={e => setAnimate(e.target.checked)}
            className="accent-[#6ea8fe]"
          />
          Animate stills
        </label>
        <span className="text-xs px-2.5 py-1 rounded-full border border-[#5e472b] text-[#f0a35e]">
          spends DashScope credit
        </span>

        <div className="ml-auto flex flex-col items-end gap-1">
          {submitError ? (
            <p className="text-xs text-[#f06a6a]">{submitError}</p>
          ) : null}
          <Button
            type="submit"
            disabled={isPending}
            className="bg-[#6ea8fe] text-[#0a0d14] font-semibold text-sm px-4 py-2.5 rounded-lg hover:bg-[#5a97f0] active:scale-[0.98] transition-all disabled:opacity-50"
          >
            {isPending ? 'Creating…' : 'Create plan →'}
          </Button>
        </div>
      </div>

      <p className="text-[11px] text-[#4a5568]">
        Generation needs an API key for the selected model&apos;s provider — add one in <Link href={ROUTES.SETTINGS} className="text-[#6ea8fe] hover:underline">Settings</Link>.
      </p>
    </form>
  )
}
