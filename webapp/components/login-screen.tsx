import { API } from '@/lib/routes'

const DEV_AUTH =
  process.env.NODE_ENV !== 'production' &&
  process.env.NEXT_PUBLIC_DEV_AUTH === 'true'

export function LoginScreen() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0f1115]">
      <div className="w-[390px] max-w-full bg-[#171a21] border border-[#2a2f3a] rounded-xl p-8">
        <div className="text-xl font-bold mb-1">🎬 AI Video Studio</div>
        <p className="text-sm text-[#9aa3b2] mb-6">
          Sign in to create and manage your videos.
        </p>
        <a
          href={API.AUTH.LOGIN}
          className="flex items-center justify-center w-full rounded-lg px-4 py-2.5 bg-[#6ea8fe] text-[#0a0d14] font-semibold text-sm hover:bg-[#5a97f0] transition-colors"
        >
          Log in
        </a>
        {DEV_AUTH && (
          <form method="post" action={API.AUTH.DEV_LOGIN}>
            <button
              type="submit"
              className="flex items-center justify-center w-full rounded-lg px-4 py-2.5 mt-3 border border-[#2a2f3a] text-[#9aa3b2] text-sm hover:bg-[#1e222b] transition-colors"
            >
              Dev login (local only)
            </button>
          </form>
        )}
        <p className="text-xs text-[#9aa3b2] text-center mt-5 leading-relaxed">
          🔒 Authentication by <strong className="text-[#e7e9ee]">AWS Cognito</strong>
        </p>
      </div>
    </div>
  )
}
