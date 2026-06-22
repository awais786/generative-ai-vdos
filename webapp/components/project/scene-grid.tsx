import { Scene } from '@/lib/project-types'

const STATUS_LABEL: Record<string, string> = {
  PENDING: 'pending',
  RUNNING: 'generating…',
  DONE: 'done',
  FAILED: 'failed',
}

const STATUS_COLOR: Record<string, string> = {
  PENDING: '#9aa3b2',
  RUNNING: '#f0a35e',
  DONE: '#5cd6a4',
  FAILED: '#f06a6a',
}

export default function SceneGrid({ scenes }: { scenes: Scene[] }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {scenes.map(scene => (
        <div
          key={scene.id}
          className="bg-[#1e222b] border border-[#2a2f3a] rounded-[10px] overflow-hidden"
        >
          <div className="aspect-video bg-[#171a21] relative flex items-center justify-center">
            {scene.media_path && scene.image_status === 'DONE' ? (
              <img
                src={scene.media_path}
                alt={`Scene ${scene.index + 1}`}
                className="w-full h-full object-cover absolute inset-0"
              />
            ) : null}
            {scene.image_status === 'RUNNING' ? (
              <div className="w-6 h-6 rounded-full border-2 border-[#f0a35e] border-t-transparent animate-spin" />
            ) : null}
            {scene.image_status === 'FAILED' ? (
              <span className="text-[#f06a6a] text-2xl">✕</span>
            ) : null}
            {scene.image_status === 'PENDING' ? (
              <span className="text-[#4a5568] text-xs">waiting…</span>
            ) : null}
          </div>
          <div className="px-3 py-2 flex items-center justify-between">
            <span className="text-xs font-mono text-[#9aa3b2]">
              Scene {scene.index + 1}
            </span>
            <span
              className="text-xs"
              style={{ color: STATUS_COLOR[scene.image_status] ?? '#9aa3b2' }}
            >
              {STATUS_LABEL[scene.image_status] ??
                scene.image_status.toLowerCase()}
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}
