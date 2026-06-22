import { redirect } from 'next/navigation'
import { Header } from '@/components/header'
import { getUser } from '@/lib/auth-server'

export default async function ProjectsLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const user = await getUser()
  if (!user) redirect('/login')

  return (
    <>
      <Header email={user.email} name={user.name} />
      <main className="max-w-[1040px] mx-auto px-5 py-7 pb-20">{children}</main>
    </>
  )
}
