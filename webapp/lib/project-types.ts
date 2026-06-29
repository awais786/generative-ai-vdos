export type ProjectStatus =
  | 'DRAFT'
  | 'PLANNING'
  | 'REVIEW'
  | 'GENERATING'
  | 'VIDEO_GENERATING'
  | 'DONE'
  | 'FAILED'

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
