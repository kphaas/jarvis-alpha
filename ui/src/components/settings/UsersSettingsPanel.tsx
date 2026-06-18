import { Users } from 'lucide-react'
import { useAppStore } from '../../store'
import { AddUserForm } from './AddUserForm'
import { RelationshipForm } from './RelationshipForm'
import { RelationshipsList } from './RelationshipsList'
import { UserProfileCard } from './UserProfileCard'
import { useIdentitySettings } from './useIdentitySettings'

export function UsersSettingsPanel() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const { identity, loading, error, reload } = useIdentitySettings()

  return (
    <section className="space-y-4">
      <h2 className="text-xs font-mono uppercase opacity-40 tracking-widest inline-flex items-center gap-2">
        <Users size={13} />
        Users
      </h2>
      {loading && [0, 1, 2].map(i => (
        <div key={i} className={`h-28 rounded-2xl border ${isDark ? 'border-white/10 bg-white/5' : 'border-[#141414]/10 bg-[#141414]/5'} animate-pulse`} />
      ))}
      {error && (
        <div className={`p-4 rounded-2xl border ${isDark ? 'border-rose-400/30 bg-rose-500/10 text-rose-200' : 'border-rose-600/30 bg-rose-50 text-rose-700'} text-sm`}>
          {error}
        </div>
      )}
      {identity && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <AddUserForm onSaved={reload} />
            <RelationshipForm profiles={identity.profiles} onSaved={reload} />
          </div>
          <div className="space-y-3">
            {identity.profiles.map(profile => (
              <UserProfileCard key={`${profile.id}:${profile.pin_status}`} profile={profile} relationships={identity.relationships} profiles={identity.profiles} onPinUpdated={reload} />
            ))}
          </div>
          <RelationshipsList profiles={identity.profiles} relationships={identity.relationships} onDeleted={reload} />
        </>
      )}
    </section>
  )
}
