import { redirectTo } from '@/lib/public-origin'
import { ROUTES } from '@/lib/routes'

export default function RootPage() {
  redirectTo(ROUTES.HOME)
}
