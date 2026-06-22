'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { Project, ShotPlan, Character, Scene } from '@/lib/project-types'
import { Button } from '@/components/ui/button'
import StatusPill from './status-pill'

interface Props {
  project: Project
  onUpdate: (updates: Partial<Project>) => void
}

const TA =
  'w-full bg-[#171a21] text-[#e7e9ee] border border-[#2a2f3a] rounded-lg px-3 py-2 text-sm resize-y focus:outline-none focus:ring-1 focus:ring-[#6ea8fe]'

const INPUT =
  'w-full bg-[#171a21] text-[#e7e9ee] border border-[#2a2f3a] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-[#6ea8fe]'

export default function PlanEditor({ project, onUpdate }: Props) {
  const router = useRouter()
  const [refineText, setRefineText] = useState('')
  const [refineError, setRefineError] = useState('')
  const [patchError, setPatchError] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [isRefining, startRefine] = useTransition()
  const [isApproving, startApprove] = useTransition()
  const [isDeleting, startDelete] = useTransition()

  const plan = project.shot_plan
  const [planTitle, setPlanTitle] = useState(plan?.title ?? project.title ?? '')
  const [musicMood, setMusicMood] = useState(plan?.music_mood ?? project.music ?? '')
  const [stylePrefix, setStylePrefix] = useState(plan?.style_prefix ?? '')
  const [globalNegative, setGlobalNegative] = useState(plan?.global_negative ?? '')

  // Scenes come from DB (project.scenes), not shot_plan.
  const scenes = project.scenes ?? []
  const characters = plan?.characters ?? []

  async function patchPlan(updates: Partial<ShotPlan>, extraFields?: { title?: string }) {
    setPatchError('')
    const newPlan = { ...(project.shot_plan ?? {}), ...updates }
    const body: Record<string, unknown> = { shot_plan: newPlan }
    if (extraFields?.title !== undefined) body.title = extraFields.title

    const res = await fetch(`/api/projects/${project.id}/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (res.status === 409) {
      setPatchError('Can only edit plan in REVIEW state.')
      return
    }
    if (res.ok) {
      const updated: Project = await res.json()
      onUpdate({ shot_plan: updated.shot_plan, title: updated.title })
    }
  }

  async function patchScene(index: number, updates: Partial<Scene>) {
    const res = await fetch(`/api/projects/${project.id}/scenes/${index}/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    })
    if (res.ok) {
      const updatedScene: Scene = await res.json()
      const updatedScenes = scenes.map(s => s.index === index ? updatedScene : s)
      onUpdate({ scenes: updatedScenes })
    }
  }

  async function patchCharacter(index: number, description: string) {
    const updated = characters.map((c, i) =>
      i === index ? { ...c, description } : c,
    )
    await patchPlan({ characters: updated })
  }

  function handleRefine() {
    if (!refineText.trim()) return
    setRefineError('')
    startRefine(async () => {
      const res = await fetch(`/api/projects/${project.id}/refine/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instruction: refineText.trim() }),
      })
      if (res.ok || res.status === 202) {
        setRefineText('')
        onUpdate({ status: 'PLANNING' })
      } else {
        const data: { detail?: string } = await res.json().catch(() => ({}))
        setRefineError(data.detail ?? 'Refine failed. Please try again.')
      }
    })
  }

  function handleApprove() {
    startApprove(async () => {
      const res = await fetch(`/api/projects/${project.id}/approve/`, {
        method: 'POST',
      })
      if (res.ok || res.status === 202) {
        onUpdate({ status: 'GENERATING' })
      }
    })
  }

  function handleDelete() {
    startDelete(async () => {
      const res = await fetch(`/api/projects/${project.id}/`, {
        method: 'DELETE',
      })
      if (res.status === 204) {
        router.push('/home')
      }
    })
  }

  return (
    <div className="flex flex-col md:flex-row gap-6 items-start">
      {/* ── Sidebar ── */}
      <aside className="w-full md:w-64 lg:w-72 shrink-0 space-y-5 md:sticky md:top-6">
        <StatusPill status="REVIEW" />

        <div>
          <p className="text-sm font-medium text-[#e7e9ee] leading-snug line-clamp-2">
            {planTitle || project.title || 'Untitled plan'}
          </p>
          <p className="text-xs text-[#9aa3b2] mt-1 leading-relaxed line-clamp-3">
            {project.prompt}
          </p>
        </div>

        <div className="h-px bg-[#2a2f3a]" />

        <div className="space-y-2">
          <label className="block text-[10px] uppercase tracking-[0.15em] font-medium text-[#4a5568]">
            Refine with an instruction
          </label>
          <textarea
            value={refineText}
            onChange={e => setRefineText(e.target.value)}
            placeholder="make the keeper older, add a harbor scene…"
            rows={3}
            disabled={isRefining}
            className={TA + ' disabled:opacity-50 text-xs'}
          />
          {refineError ? (
            <p className="text-xs text-[#f06a6a]">{refineError}</p>
          ) : null}
          <Button
            disabled={isRefining || !refineText.trim()}
            onClick={handleRefine}
            className="w-full bg-transparent border border-[#2a2f3a] text-[#e7e9ee] text-xs px-3 py-2 rounded-lg hover:bg-[#252a35] disabled:opacity-50"
          >
            {isRefining ? 'Refining…' : 'Refine plan'}
          </Button>
        </div>

        <div className="h-px bg-[#2a2f3a]" />

        {patchError ? (
          <p className="text-xs text-[#f06a6a]">{patchError}</p>
        ) : null}

        {confirmDelete ? (
          <div className="space-y-2">
            <p className="text-xs text-[#9aa3b2]">Delete this project?</p>
            <Button
              disabled={isDeleting}
              onClick={handleDelete}
              className="w-full bg-[#f06a6a] text-white text-xs px-3 py-2 rounded-lg hover:bg-[#d95858] disabled:opacity-50"
            >
              {isDeleting ? 'Deleting…' : 'Yes, delete'}
            </Button>
            <Button
              onClick={() => setConfirmDelete(false)}
              className="w-full bg-transparent border border-[#2a2f3a] text-[#e7e9ee] text-xs px-3 py-2 rounded-lg hover:bg-[#1e222b]"
            >
              Cancel
            </Button>
          </div>
        ) : (
          <div className="space-y-2">
            <Button
              disabled={isApproving || scenes.length === 0}
              onClick={handleApprove}
              className="w-full bg-[#6ea8fe] text-[#0a0d14] font-semibold text-sm px-4 py-2.5 rounded-lg hover:bg-[#5a97f0] disabled:opacity-50"
            >
              {isApproving ? 'Approving…' : 'Approve →'}
            </Button>
            <Button
              onClick={() => setConfirmDelete(true)}
              className="w-full bg-transparent border border-[#f06a6a]/40 text-[#f06a6a] text-xs px-3 py-2 rounded-lg hover:bg-[#f06a6a]/10"
            >
              Delete project
            </Button>
          </div>
        )}
      </aside>

      {/* ── Main ── */}
      <div className="flex-1 min-w-0 space-y-6">

        {/* Plan-level fields */}
        <section className="bg-[#1e222b] border border-[#2a2f3a] rounded-[10px] p-4 space-y-4">
          <p className="text-[10px] uppercase tracking-[0.2em] font-medium text-[#4a5568]">
            Plan — edits save on blur
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-[2fr_1fr] gap-3">
            <div>
              <label className="block text-xs text-[#9aa3b2] mb-1">Title</label>
              <input
                value={planTitle}
                onChange={e => setPlanTitle(e.target.value)}
                onBlur={() => patchPlan({ title: planTitle }, { title: planTitle })}
                className={INPUT}
              />
            </div>
            <div>
              <label className="block text-xs text-[#9aa3b2] mb-1">Music mood</label>
              <input
                value={musicMood}
                onChange={e => setMusicMood(e.target.value)}
                onBlur={() => patchPlan({ music_mood: musicMood })}
                placeholder="calm"
                className={INPUT}
              />
            </div>
          </div>

          <div>
            <label className="block text-xs text-[#9aa3b2] mb-1">Style prefix</label>
            <input
              value={stylePrefix}
              onChange={e => setStylePrefix(e.target.value)}
              onBlur={() => patchPlan({ style_prefix: stylePrefix })}
              placeholder="cinematic photo, shallow depth of field, muted colors"
              className={INPUT}
            />
          </div>

          <div>
            <label className="block text-xs text-[#9aa3b2] mb-1">Global negative prompt</label>
            <input
              value={globalNegative}
              onChange={e => setGlobalNegative(e.target.value)}
              onBlur={() => patchPlan({ global_negative: globalNegative })}
              placeholder="text, watermark, extra limbs, blurry"
              className={INPUT}
            />
          </div>
        </section>

        {/* Characters */}
        {characters.length > 0 ? (
          <section className="space-y-3">
            <p className="text-[10px] uppercase tracking-[0.2em] font-medium text-[#4a5568]">
              Characters — descriptions save on blur
            </p>
            {characters.map((char, i) => (
              <CharacterCard
                key={char.name}
                index={i}
                character={char}
                onPatch={patchCharacter}
              />
            ))}
          </section>
        ) : null}

        {/* Scenes */}
        <section className="space-y-3">
          <div className="flex items-center gap-2">
            <p className="text-[10px] uppercase tracking-[0.2em] font-medium text-[#4a5568]">
              Scenes
            </p>
            {scenes.length > 0 ? (
              <span className="text-[10px] text-[#4a5568]">({scenes.length})</span>
            ) : null}
            <span className="text-[10px] text-[#4a5568] ml-1">— edits save on blur</span>
          </div>
          {scenes.map(scene => (
            <PlanSceneCard
              key={scene.id}
              scene={scene}
              onPatch={patchScene}
            />
          ))}
        </section>
      </div>
    </div>
  )
}

function CharacterCard({
  index,
  character,
  onPatch,
}: {
  index: number
  character: Character
  onPatch: (index: number, description: string) => void
}) {
  const [description, setDescription] = useState(character.description)

  return (
    <div className="bg-[#1e222b] border border-[#2a2f3a] rounded-[10px] p-4 space-y-2">
      <span className="text-xs font-mono text-[#6ea8fe]">
        {'{' + character.name + '}'}
      </span>
      <textarea
        value={description}
        onChange={e => setDescription(e.target.value)}
        onBlur={() => onPatch(index, description)}
        rows={2}
        className={TA}
      />
      {character.negative ? (
        <p className="text-[10px] text-[#4a5568]">
          negative: {character.negative}
        </p>
      ) : null}
    </div>
  )
}

function PlanSceneCard({
  scene,
  onPatch,
}: {
  scene: Scene
  onPatch: (index: number, updates: Partial<Scene>) => void
}) {
  const [mediaPrompt, setMediaPrompt] = useState(scene.media_prompt)
  const [narration, setNarration] = useState(scene.narration)

  return (
    <div className="bg-[#1e222b] border border-[#2a2f3a] rounded-[10px] p-4 relative overflow-hidden">
      {/* Ghost numeral — signature design element */}
      <span
        aria-hidden
        className="absolute right-3 top-0 text-[88px] font-bold leading-none text-[#2a2f3a] select-none pointer-events-none"
      >
        {String(scene.index + 1).padStart(2, '0')}
      </span>

      <div className="relative z-10 space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-[#6ea8fe]">Scene {scene.index + 1}</span>
          <button
            type="button"
            onClick={() => onPatch(scene.index, { animate: !scene.animate })}
            className={`text-[10px] px-2 py-0.5 rounded-full border transition-colors ${
              scene.animate
                ? 'border-[#f0a35e]/60 text-[#f0a35e]'
                : 'border-[#2a2f3a] text-[#4a5568] hover:border-[#3a3f4a] hover:text-[#9aa3b2]'
            }`}
          >
            {scene.animate ? 'animate' : 'still'}
          </button>
        </div>

        <div>
          <label className="block text-xs text-[#9aa3b2] mb-1">Image prompt</label>
          <textarea
            value={mediaPrompt}
            onChange={e => setMediaPrompt(e.target.value)}
            onBlur={() => onPatch(scene.index, { media_prompt: mediaPrompt })}
            rows={2}
            className={TA}
          />
        </div>

        <div>
          <label className="block text-xs text-[#9aa3b2] mb-1">Narration</label>
          <textarea
            value={narration}
            onChange={e => setNarration(e.target.value)}
            onBlur={() => onPatch(scene.index, { narration })}
            rows={2}
            className={TA}
          />
        </div>
      </div>
    </div>
  )
}
