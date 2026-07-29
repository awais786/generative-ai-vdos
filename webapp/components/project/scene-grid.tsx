import { memo } from 'react'
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

// S3 presigned URLs change signature each render, but the filename is stable.
// Extract it so the memo comparator can skip re-renders when only the signature
// churns — otherwise the <img src> would swap every 3 s poll and flicker.
function fileKey(url: string | undefined | null): string {
  if (!url) return ''
  const pathname = url.split('?')[0]
  const parts = pathname.split('/')
  return parts[parts.length - 1] || pathname
}

interface SceneCardProps {
  scene: Scene
}

const SceneCard = memo(
  function SceneCard({ scene }: SceneCardProps) {
    const displaySrc =
      scene.media_status === 'DONE'
        ? scene.media_path || null
        : scene.preview_url || scene.media_path || null

    return (
      <div className="bg-[#1e222b] border border-[#2a2f3a] rounded-[10px] overflow-hidden">
        <div className="aspect-video bg-[#171a21] relative flex items-center justify-center">
          {displaySrc
            ? (displaySrc.split('?')[0].endsWith('.mp4') ? (
                <video
                  src={displaySrc}
                  playsInline
                  className="w-full h-full object-cover absolute inset-0"
                />
              ) : (
                <img
                  src={displaySrc}
                  alt={`Scene ${scene.index + 1}`}
                  className="w-full h-full object-cover absolute inset-0"
                />
              ))
            : null}
          {scene.media_status === 'RUNNING' ? (
            <div className="absolute inset-0 flex items-center justify-center bg-black/30">
              <div className="w-6 h-6 rounded-full border-2 border-[#f0a35e] border-t-transparent animate-spin" />
            </div>
          ) : null}
          {scene.media_status === 'FAILED' ? (
            <span className="text-[#f06a6a] text-2xl">✕</span>
          ) : null}
          {scene.media_status === 'PENDING' ? (
            <span className="text-[#4a5568] text-xs">waiting…</span>
          ) : null}
        </div>
        <div className="px-3 py-2 flex items-center justify-between">
          <span className="text-xs font-mono text-[#9aa3b2]">
            Scene {scene.index + 1}
          </span>
          <span
            className="text-xs"
            style={{ color: STATUS_COLOR[scene.media_status] ?? '#9aa3b2' }}
          >
            {STATUS_LABEL[scene.media_status] ?? scene.media_status}
          </span>
        </div>
      </div>
    )
  },
  // Skip re-render when only updated_at churns from the 3 s poll. The visible
  // fields are the media file (by filename, not signed URL), the status pill,
  // and the index label — everything else on the Scene is irrelevant here.
  (prev, next) =>
    prev.scene.id === next.scene.id &&
    prev.scene.index === next.scene.index &&
    prev.scene.media_status === next.scene.media_status &&
    fileKey(prev.scene.media_path) === fileKey(next.scene.media_path) &&
    fileKey(prev.scene.preview_url) === fileKey(next.scene.preview_url),
)

export default function SceneGrid({ scenes }: { scenes: Scene[] }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {scenes.map(scene => (
        <SceneCard key={scene.id} scene={scene} />
      ))}
    </div>
  )
}
