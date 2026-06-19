import { Trash2 } from 'lucide-react'
import { apiJson } from '../../lib/apiFetch'
import { useAppStore } from '../../store'
import type { Profile, Relationship } from './types'

export function RelationshipsList({
  profiles,
  relationships,
  onDeleted,
}: {
  profiles: Profile[]
  relationships: Relationship[]
  onDeleted: () => Promise<void>
}) {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const profileName = (profileId: string) =>
    profiles.find(profile => profile.id === profileId)?.display_name ?? profileId

  if (relationships.length === 0) return null

  return (
    <div className={`p-5 rounded-2xl border ${border} ${isDark ? 'bg-white/5' : 'bg-[#141414]/5'} space-y-2`}>
      {relationships.map(rel => (
        <div key={rel.id} className="flex items-center justify-between gap-3 text-sm">
          <span>{profileName(rel.from_profile_id)} · {rel.relationship_label} · {profileName(rel.to_profile_id)}</span>
          <button onClick={async () => { await apiJson(`/v1/settings/relationships/${rel.id}`, { method: 'DELETE' }); await onDeleted() }} className="min-h-11 min-w-11 inline-flex items-center justify-center opacity-40 hover:opacity-80" aria-label="Delete relationship">
            <Trash2 size={14} />
          </button>
        </div>
      ))}
    </div>
  )
}
