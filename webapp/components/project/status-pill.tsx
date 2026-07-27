import { STATUS_CONFIG } from '@/lib/project-types'

export default function StatusPill({ status }: { status: string }) {
  const { color, pulse } = STATUS_CONFIG[status as keyof typeof STATUS_CONFIG] ?? { color: '#9aa3b2', pulse: false }
  return (
    <div className="inline-flex items-center gap-1.5">
      <span
        className={`w-1.5 h-1.5 rounded-full${pulse ? ' animate-pulse' : ''}`}
        style={{ backgroundColor: color }}
      />
      <span className="text-[10px] tracking-[0.2em] uppercase font-medium text-[#9aa3b2]">
        {status.toLowerCase()}
      </span>
    </div>
  )
}
