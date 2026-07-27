export const ROUTES = {
  HOME: '/home',
  LOGIN: '/login',
  SETTINGS: '/settings',
  PROJECT: (id: string) => `/projects/${id}`,
} as const

export const API = {
  AUTH: {
    LOGIN: '/api/auth/login',
    LOGOUT: '/api/auth/logout',
    ME: '/api/auth/me',
    DEV_LOGIN: '/api/auth/dev-login', // dev-only — never use in production code paths
    KEYS: '/api/auth/keys/',
    KEY: (id: number) => `/api/auth/keys/${id}/`,
  },
  PROJECTS: {
    LIST: '/api/projects/',
    DETAIL: (id: string) => `/api/projects/${id}/`,
    LOGS: (id: string, after: number) => `/api/projects/${id}/logs/?after=${after}`,
    APPROVE_IMAGES: (id: string) => `/api/projects/${id}/approve-images/`,
    RETRY: (id: string) => `/api/projects/${id}/retry/`,
    REFINE: (id: string) => `/api/projects/${id}/refine/`,
    APPROVE: (id: string) => `/api/projects/${id}/approve/`,
    REASSEMBLE: (id: string) => `/api/projects/${id}/reassemble/`,
    DOWNLOAD: (id: string) => `/api/projects/${id}/download/`,
    SCENE: (projectId: string, index: number) => `/api/projects/${projectId}/scenes/${index}/`,
    SCENE_REGENERATE: (projectId: string, index: number) =>
      `/api/projects/${projectId}/scenes/${index}/regenerate/`,
  },
  CORE: {
    PROVIDERS: '/api/core/providers/',
  },
  MODELS: {
    LIST: '/api/models/',
    DETAIL: (id: number) => `/api/models/${id}/`,
  },
} as const
