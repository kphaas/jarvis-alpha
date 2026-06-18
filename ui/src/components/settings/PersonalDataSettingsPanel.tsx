import { Home } from 'lucide-react'
import { useAppStore } from '../../store'
import { ContactCardForm } from './ContactCardForm'
import { HomeAddressForm } from './HomeAddressForm'
import { WebAgentLocationForm } from './WebAgentLocationForm'
import { useIdentitySettings } from './useIdentitySettings'

export function PersonalDataSettingsPanel() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const { identity, loading, error, reload } = useIdentitySettings('Failed to load personal data')

  return (
    <section className="space-y-4">
      <h2 className="text-xs font-mono uppercase opacity-40 tracking-widest inline-flex items-center gap-2">
        <Home size={13} />
        Personal Data
      </h2>
      {loading && <div className={`h-48 rounded-2xl ${isDark ? 'bg-white/5' : 'bg-[#141414]/5'} animate-pulse`} />}
      {error && (
        <div className={`p-4 rounded-2xl border ${isDark ? 'border-rose-400/30 bg-rose-500/10 text-rose-200' : 'border-rose-600/30 bg-rose-50 text-rose-700'} text-sm`}>
          {error}
        </div>
      )}
      {identity && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <HomeAddressForm key={identity.personal_data.home_address?.updated_at ?? 'empty-address'} identity={identity} onSaved={reload} />
            <ContactCardForm profiles={identity.profiles} onSaved={reload} />
          </div>
          <WebAgentLocationForm />
        </>
      )}
    </section>
  )
}
