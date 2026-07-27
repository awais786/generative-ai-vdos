'use client'

import Link from 'next/link'
import { Button } from '@/components/ui/button'

interface HeaderProps {
  email: string
  name: string
}

export function Header({ email, name }: HeaderProps) {
  function handleLogout() {
    window.location.replace('/api/auth/logout')
  }

  const initials = (name || email).slice(0, 1).toUpperCase()

  return (
    <header className="sticky top-0 z-10 flex items-center gap-4 px-5 py-3 bg-[#0c0e12] border-b border-[#2a2f3a]">
      <Link href="/home" className="font-bold tracking-tight hover:opacity-80 transition-opacity">
        🎬 AI Video Studio
      </Link>

      <div className="ml-auto flex items-center gap-3">
        <Link
          href="/settings"
          className="text-xs text-[#9aa3b2] hover:text-[#e7e9ee] transition-colors"
        >
          Settings
        </Link>
        <div className="flex items-center gap-2 text-sm text-[#9aa3b2] border border-[#2a2f3a] rounded-full pl-1 pr-3 py-1">
          <span className="w-6 h-6 rounded-full bg-[#6ea8fe] text-[#0a0d14] flex items-center justify-center font-bold text-xs">
            {initials}
          </span>
          <span className="max-w-[180px] truncate">{email}</span>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleLogout}
          className="text-xs border-[#2a2f3a] text-[#e7e9ee] bg-transparent hover:bg-[#1e222b]"
        >
          Log out
        </Button>
      </div>
    </header>
  )
}
