import { getUser } from '@/lib/auth-server'
import { redirectTo } from '@/lib/public-origin'
import { LoginScreen } from '@/components/login-screen'
import { ROUTES } from '@/lib/routes'

export const metadata = { title: 'Sign in — AI Video Studio' }

export default async function LoginPage() {
  let user = null
  try {
    user = await getUser()
  } catch (err) {
    console.error('[login] getUser failed, showing login page:', err)
  }
  if (user) redirectTo(ROUTES.HOME)
  return <LoginScreen />
}
