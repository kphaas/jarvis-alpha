import { Heart } from 'lucide-react'
import { useState } from 'react'
import { apiJson } from '../../lib/apiFetch'
import { useAppStore } from '../../store'
import { SettingsStatusLine, type SaveState } from './SettingsStatusLine'
import type { Profile } from './types'

export function RelationshipForm({ profiles, onSaved }: { profiles: Profile[]; onSaved: () => void }) {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const inputBg = isDark ? 'bg-white/5' : 'bg-[#141414]/5'
  const [form, setForm] = useState({
    from_profile_id: profiles[0]?.id ?? '',
    relationship_label: '',
    to_profile_id: profiles[1]?.id ?? profiles[0]?.id ?? '',
    inverse_relationship_label: '',
  })
  const [state, setState] = useState<SaveState>('idle')
  const [message, setMessage] = useState('')

  async function save() {
    setState('saving')
    setMessage('')
    try {
      await apiJson('/v1/settings/relationships', {
        method: 'PUT',
        body: JSON.stringify({
          ...form,
          inverse_relationship_label: form.inverse_relationship_label || null,
        }),
      })
      setForm(f => ({ ...f, relationship_label: '', inverse_relationship_label: '' }))
      setState('success')
      setMessage('Relationship saved')
      onSaved()
    } catch (e: unknown) {
      setState('error')
      setMessage(e instanceof Error ? e.message : 'Failed to save relationship')
    }
  }

  return (
    <div className={`p-5 rounded-2xl border ${border} ${isDark ? 'bg-white/5' : 'bg-[#141414]/5'} space-y-3`}>
      <div className="flex items-center gap-2">
        <Heart size={14} className="opacity-60" />
        <span className="text-sm font-medium">Relationship</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <select value={form.from_profile_id} onChange={e => setForm(f => ({ ...f, from_profile_id: e.target.value }))} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`}>
          {profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.display_name}</option>)}
        </select>
        <input placeholder="Relationship" value={form.relationship_label} onChange={e => setForm(f => ({ ...f, relationship_label: e.target.value }))} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
        <select value={form.to_profile_id} onChange={e => setForm(f => ({ ...f, to_profile_id: e.target.value }))} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`}>
          {profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.display_name}</option>)}
        </select>
        <input placeholder="Inverse label" value={form.inverse_relationship_label} onChange={e => setForm(f => ({ ...f, inverse_relationship_label: e.target.value }))} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
      </div>
      <SettingsStatusLine state={state} message={message} />
      <button onClick={save} disabled={state === 'saving' || !form.relationship_label || form.from_profile_id === form.to_profile_id} className="w-full min-h-11 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-sm font-mono hover:bg-emerald-500/30 disabled:opacity-40 transition-colors">
        {state === 'saving' ? 'Saving...' : 'Save Relationship'}
      </button>
    </div>
  )
}
