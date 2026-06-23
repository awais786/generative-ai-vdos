const DOT: Record<string, { color: string; pulse: boolean }> = {
  DRAFT:      { color: '#9aa3b2', pulse: false },
  PLANNING:   { color: '#6ea8fe', pulse: true  },
  REVIEW:     { color: '#5cd6a4', pulse: false },
  GENERATING:       { color: '#f0a35e', pulse: true  },
  VIDEO_GENERATING: { color: '#f0a35e', pulse: true  },
  DONE:       { color: '#5cd6a4', pulse: false },
  FAILED:     { color: '#f06a6a', pulse: false },
}

export default function StatusPill({ status }: { status: string }) {
  const { color, pulse } = DOT[status] ?? { color: '#9aa3b2', pulse: false }
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
