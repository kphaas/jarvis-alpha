import { motion } from 'framer-motion'
import { Lock, User } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useAppStore } from '../../store'
import { PinForm } from './PinForms'
import { RATING_LABEL } from './types'
import type { Profile, Relationship } from './types'

export function UserProfileCard({
  profile,
  relationships,
  profiles,
  onPinUpdated,
}: {
  profile: Profile
  relationships: Relationship[]
  profiles: Profile[]
  onPinUpdated: () => void
}) {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/5' : 'bg-[#141414]/5'
  const canManagePin = profile.id !== 'ken'
  const [expanded, setExpanded] = useState(canManagePin && profile.pin_status === 'placeholder')
  const pinSet = profile.pin_status === 'set'

  const profileById = useMemo(() => new Map(profiles.map(row => [row.id, row])), [profiles])
  const chips = relationships.flatMap(rel => {
    if (rel.from_profile_id === profile.id) {
      return [`${rel.relationship_label} to ${profileById.get(rel.to_profile_id)?.display_name ?? rel.to_profile_id}`]
    }
    if (rel.to_profile_id === profile.id && rel.inverse_relationship_label) {
      return [`${rel.inverse_relationship_label} to ${profileById.get(rel.from_profile_id)?.display_name ?? rel.from_profile_id}`]
    }
    return []
  })

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className={`p-5 rounded-2xl border ${border} ${subtle} space-y-3`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className={`w-9 h-9 rounded-full flex items-center justify-center ${subtle} border ${border}`}>
            <User size={16} className="opacity-60" />
          </div>
          <div>
            <p className="font-medium text-sm">{profile.display_name}</p>
            <p className="text-[10px] font-mono uppercase opacity-40">
              {profile.role} · {RATING_LABEL[profile.max_rating] ?? profile.max_rating}
              {profile.child_age ? ` · Age ${profile.child_age}` : ''}
            </p>
            {profile.personal_data?.email && <p className="text-xs opacity-50 mt-1">{profile.personal_data.email}</p>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-mono px-2 py-0.5 rounded border ${pinSet ? 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30' : 'text-amber-400 bg-amber-500/15 border-amber-500/30'}`}>
            {pinSet ? 'PIN SET' : 'PIN REQUIRED'}
          </span>
          {canManagePin && (
            <button onClick={() => setExpanded(e => !e)} className="min-h-11 min-w-11 inline-flex items-center justify-center opacity-40 hover:opacity-80 transition-opacity" aria-label={`Set PIN for ${profile.display_name}`}>
              <Lock size={14} />
            </button>
          )}
        </div>
      </div>
      {chips.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {chips.map(chip => (
            <span key={chip} className={`text-[10px] font-mono px-2 py-1 rounded border ${isDark ? 'border-pink-300/20 bg-pink-500/10 text-pink-100' : 'border-pink-700/15 bg-pink-50 text-pink-800'}`}>
              {chip}
            </span>
          ))}
        </div>
      )}
      {canManagePin && expanded && (
        <PinForm profileId={profile.id} onSuccess={() => { setExpanded(false); onPinUpdated() }} />
      )}
    </motion.div>
  )
}
