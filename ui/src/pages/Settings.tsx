import { useState } from 'react'
import { KeyRound, MapPin, ShieldCheck, Users } from 'lucide-react'
import { useAppStore } from '../store'
import { UsersSettingsPanel } from '../components/settings/UsersSettingsPanel'
import { PersonalDataSettingsPanel } from '../components/settings/PersonalDataSettingsPanel'
import { SecuritySettingsPanel } from '../components/settings/SecuritySettingsPanel'

type SettingsTab = 'users' | 'personal' | 'security'

const TABS: Array<{ id: SettingsTab; label: string; icon: typeof Users }> = [
  { id: 'users', label: 'Users', icon: Users },
  { id: 'personal', label: 'Personal Data', icon: MapPin },
  { id: 'security', label: 'Security', icon: ShieldCheck },
]

export default function Settings() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const [tab, setTab] = useState<SettingsTab>('users')

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className={`font-serif italic text-3xl ${isDark ? 'text-white' : 'text-[#141414]'}`}>Settings</h1>
        <p className="text-[10px] font-mono uppercase opacity-40 mt-1">AT-0 · Identity, data &amp; security</p>
      </div>

      <div className={`flex flex-wrap gap-2 rounded-xl border p-1 ${isDark ? 'border-white/10 bg-white/5' : 'border-[#141414]/10 bg-[#141414]/5'}`}>
        {TABS.map(item => {
          const Icon = item.icon
          const active = tab === item.id
          return (
            <button
              key={item.id}
              onClick={() => setTab(item.id)}
              className={`min-h-11 flex-1 inline-flex items-center justify-center gap-2 rounded-lg px-3 text-sm font-mono transition-colors ${
                active
                  ? isDark ? 'bg-white/15 text-white' : 'bg-white text-[#141414] shadow-sm'
                  : 'opacity-55 hover:opacity-90'
              }`}
            >
              <Icon size={15} />
              {item.label}
            </button>
          )
        })}
      </div>

      {tab === 'users' && <UsersSettingsPanel />}
      {tab === 'personal' && <PersonalDataSettingsPanel />}
      {tab === 'security' && (
        <section className="space-y-3">
          <h2 className="text-xs font-mono uppercase opacity-40 tracking-widest inline-flex items-center gap-2">
            <KeyRound size={13} />
            Admin Security
          </h2>
          <SecuritySettingsPanel />
        </section>
      )}
    </div>
  )
}
