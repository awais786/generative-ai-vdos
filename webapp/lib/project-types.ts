export type ProjectStatus =
  | 'DRAFT'
  | 'PLANNING'
  | 'REFINING'
  | 'REVIEW'
  | 'IMAGE_REVIEW'
  | 'GENERATING'
  | 'VIDEO_GENERATING'
  | 'DONE'
  | 'FAILED'

export const STATUS_CONFIG: Record<ProjectStatus, { color: string; pulse: boolean }> = {
  DRAFT:            { color: '#9aa3b2', pulse: false },
  PLANNING:         { color: '#6ea8fe', pulse: true  },
  REFINING:         { color: '#a78bfa', pulse: true  },
  REVIEW:           { color: '#5cd6a4', pulse: false },
  IMAGE_REVIEW:     { color: '#6ea8fe', pulse: false },
  GENERATING:       { color: '#f0a35e', pulse: true  },
  VIDEO_GENERATING: { color: '#f0a35e', pulse: true  },
  DONE:             { color: '#5cd6a4', pulse: false },
  FAILED:           { color: '#f06a6a', pulse: false },
}

export interface Character {
  name: string
  description: string
  negative?: string
  outfits?: Record<string, string>
  is_inanimate?: boolean
}

export interface ShotPlan {
  title?: string
  description?: string
  tags?: string[]
  music_mood?: string
  style_prefix?: string
  characters?: Character[]
  global_negative?: string
  [key: string]: unknown
}

// Django Scene model — created after approve, single source of truth for scene data
export interface Scene {
  id: number
  index: number
  narration: string
  media_prompt: string
  animate: boolean
  voice: string
  on_screen_text: string
  negative_prompt: string
  preview_url: string
  media_path: string
  media_status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED'
  media_provider: string
  audio_path: string
  voice_status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED'
  created_at: string
  updated_at: string
}

export interface Project {
  id: string
  title: string
  prompt: string
  status: ProjectStatus
  shot_plan: ShotPlan | null
  plan_model: string | null
  image_model: string | null
  video_model: string | null
  animate: boolean
  narrator_voice: string
  music: string
  error: string
  stale: boolean
  scenes: Scene[]
  created_at: string
  updated_at: string
}

export interface LLMModel {
  id: number
  model_id: string
  display_name: string
  provider: string
  capability: string
  is_free: boolean
  is_default: boolean
  owned: boolean
}

export interface SSEEvent {
  type: string
  stage: string
  level: 'info' | 'warn' | 'error'
  message: string
  ts: string
  project_status: ProjectStatus
  scene_index: number | null
  media_status: Scene['media_status'] | null
}
