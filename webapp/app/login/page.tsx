import { getUser } from '@/lib/auth-server'
import { redirectTo } from '@/lib/public-origin'
import { LoginScreen } from '@/components/login-screen'

export const metadata = { title: 'Sign in — AI Video Studio' }

export default async function LoginPage() {
  const user = await getUser()
  if (user) redirectTo('/home')
  return <LoginScreen />
}
