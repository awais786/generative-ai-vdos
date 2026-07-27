import Link from 'next/link'
import type { ApiKey, Provider } from '@/components/settings/api-keys'
import { SettingsPanels } from '@/components/settings/settings-panels'
import { serverFetch } from '@/lib/server-fetch'
import type { LLMModel } from '@/lib/project-types'
import { API, ROUTES } from '@/lib/routes'

export default async function SettingsPage() {
  const [initialKeys, providers, initialModels] = await Promise.all([
    serverFetch<ApiKey[]>(API.AUTH.KEYS),
    serverFetch<Provider[]>(API.CORE.PROVIDERS),
    serverFetch<LLMModel[]>(API.MODELS.LIST),
  ])

  return (
    <div className="max-w-xl">
      <Link href={ROUTES.HOME} className="flex w-fit items-center gap-1 text-sm text-[#9aa3b2] hover:text-[#e7e9ee] transition-colors mb-6">
        ← Back
      </Link>
      <div className="mb-8">
        <h1 className="text-xl font-semibold text-[#e7e9ee]">Settings</h1>
        <p className="text-sm text-[#5a6275] mt-1">Manage your provider API keys and account preferences.</p>
      </div>
      <SettingsPanels initialKeys={initialKeys} providers={providers} initialModels={initialModels} />
    </div>
  )
}
