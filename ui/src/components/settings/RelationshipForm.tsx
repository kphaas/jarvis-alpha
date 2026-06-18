import { Heart } from 'lucide-react'
import { useMemo, useState } from 'react'
import { apiJson } from '../../lib/apiFetch'
import { useAppStore } from '../../store'
import { CUSTOM_RELATIONSHIP_KEY, getRelationshipPreset, RELATIONSHIP_PRESETS } from './relationshipPresets'
import { SettingsStatusLine, type SaveState } from './SettingsStatusLine'
import type { Profile } from './types'

export function RelationshipForm({ profiles, onSaved }: { profiles: Profile[]; onSaved: () => void }) {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const inputBg = isDark ? 'bg-white/5' : 'bg-[#141414]/5'
  const [form, setForm] = useState({
    from_profile_id: profiles[0]?.id ?? '',
    to_profile_id: profiles[1]?.id ?? profiles[0]?.id ?? '',
    relationship_preset_key: RELATIONSHIP_PRESETS[0]?.key ?? CUSTOM_RELATIONSHIP_KEY,
    custom_relationship_label: '',
    custom_inverse_relationship_label: '',
  })
  const [state, setState] = useState<SaveState>('idle')
  const [message, setMessage] = useState('')
  const selectedPreset = getRelationshipPreset(form.relationship_preset_key)
  const isCustom = form.relationship_preset_key === CUSTOM_RELATIONSHIP_KEY
  const relationshipLabel = isCustom ? form.custom_relationship_label.trim() : selectedPreset?.relationshipLabel ?? ''
  const inverseRelationshipLabel = isCustom
    ? form.custom_inverse_relationship_label.trim()
    : selectedPreset?.inverseRelationshipLabel ?? ''
  const fromName = useMemo(
    () => profiles.find(profile => profile.id === form.from_profile_id)?.display_name ?? 'First person',
    [form.from_profile_id, profiles],
  )
  const toName = useMemo(
    () => profiles.find(profile => profile.id === form.to_profile_id)?.display_name ?? 'Second person',
    [form.to_profile_id, profiles],
  )
  const canSave = Boolean(
    form.from_profile_id
      && form.to_profile_id
      && form.from_profile_id !== form.to_profile_id
      && relationshipLabel,
  )

  async function save() {
    if (!canSave) return
    setState('saving')
    setMessage('')
    try {
      await apiJson('/v1/settings/relationships', {
        method: 'PUT',
        body: JSON.stringify({
          from_profile_id: form.from_profile_id,
          to_profile_id: form.to_profile_id,
          relationship_label: relationshipLabel,
          inverse_relationship_label: inverseRelationshipLabel || null,
        }),
      })
      setForm(f => ({ ...f, custom_relationship_label: '', custom_inverse_relationship_label: '' }))
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
        <select value={form.to_profile_id} onChange={e => setForm(f => ({ ...f, to_profile_id: e.target.value }))} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`}>
          {profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.display_name}</option>)}
        </select>
        <select value={form.relationship_preset_key} onChange={e => setForm(f => ({ ...f, relationship_preset_key: e.target.value }))} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none sm:col-span-2`}>
          {RELATIONSHIP_PRESETS.map(preset => <option key={preset.key} value={preset.key}>{preset.label}</option>)}
          <option value={CUSTOM_RELATIONSHIP_KEY}>Custom relationship</option>
        </select>
      </div>
      {isCustom ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <input aria-label={`${fromName} is to ${toName}`} placeholder={`${fromName} is...`} value={form.custom_relationship_label} onChange={e => setForm(f => ({ ...f, custom_relationship_label: e.target.value }))} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
          <input aria-label={`${toName} is to ${fromName}`} placeholder={`${toName} is...`} value={form.custom_inverse_relationship_label} onChange={e => setForm(f => ({ ...f, custom_inverse_relationship_label: e.target.value }))} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
        </div>
      ) : null}
      <div className={`rounded-lg border ${border} ${inputBg} px-3 py-2 text-xs leading-5`}>
        {form.from_profile_id === form.to_profile_id ? (
          <span className="text-amber-400">Pick two different people.</span>
        ) : relationshipLabel ? (
          <>
            <span>{fromName} is {relationshipLabel} to {toName}.</span>
            {inverseRelationshipLabel ? <span className="block opacity-70">{toName} is {inverseRelationshipLabel} to {fromName}.</span> : null}
          </>
        ) : (
          <span className="opacity-60">Choose a relationship.</span>
        )}
      </div>
      <SettingsStatusLine state={state} message={message} />
      <button onClick={save} disabled={state === 'saving' || !canSave} className="w-full min-h-11 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-sm font-mono hover:bg-emerald-500/30 disabled:opacity-40 transition-colors">
        {state === 'saving' ? 'Saving...' : 'Save Relationship'}
      </button>
    </div>
  )
}
