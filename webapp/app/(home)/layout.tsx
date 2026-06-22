import { Header } from '@/components/header'
import { getUser } from '@/lib/auth-server'
import { redirectTo } from '@/lib/public-origin'

export default async function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const user = await getUser()
  if (!user) redirectTo('/login')

  return (
    <>
      <Header email={user.email} name={user.name} />
      <main className="max-w-[1040px] mx-auto px-5 py-7 pb-20">{children}</main>
    </>
  )
}
