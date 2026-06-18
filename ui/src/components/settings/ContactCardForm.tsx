import { Mail, UserRound } from 'lucide-react'
import { useMemo, useState } from 'react'
import { apiJson } from '../../lib/apiFetch'
import { useAppStore } from '../../store'
import { SettingsStatusLine, type SaveState } from './SettingsStatusLine'
import { EMPTY_CONTACT, toContactForm, type ContactFormDraft } from './personalDataForms'
import type { Profile } from './types'

export function ContactCardForm({ profiles, onSaved }: { profiles: Profile[]; onSaved: () => void }) {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const inputBg = isDark ? 'bg-white/5' : 'bg-[#141414]/5'
  const [selected, setSelected] = useState(profiles[0]?.id ?? '')
  const profile = useMemo(() => profiles.find(row => row.id === selected) ?? profiles[0], [profiles, selected])
  const [drafts, setDrafts] = useState<Record<string, ContactFormDraft>>({})
  const [state, setState] = useState<SaveState>('idle')
  const [message, setMessage] = useState('')
  const form = profile ? drafts[profile.id] ?? toContactForm(profile.personal_data) : EMPTY_CONTACT

  function updateForm(field: keyof ContactFormDraft, value: string) {
    if (!profile) return
    setDrafts(current => ({
      ...current,
      [profile.id]: {
        ...form,
        [field]: value,
      },
    }))
  }

  async function save() {
    if (!profile) return
    setState('saving')
    setMessage('')
    try {
      await apiJson(`/v1/settings/users/${profile.id}/personal-data`, {
        method: 'PUT',
        body: JSON.stringify({
          legal_name: form.legal_name || null,
          preferred_name: form.preferred_name || null,
          email: form.email || null,
          phone: form.phone || null,
          birthday: form.birthday || null,
          notes: form.notes || null,
        }),
      })
      setState('success')
      setMessage('Contact saved')
      setDrafts(current => {
        const next = { ...current }
        delete next[profile.id]
        return next
      })
      onSaved()
    } catch (e: unknown) {
      setState('error')
      setMessage(e instanceof Error ? e.message : 'Failed to save contact')
    }
  }

  return (
    <div className={`p-5 rounded-2xl border ${border} ${isDark ? 'bg-white/5' : 'bg-[#141414]/5'} space-y-3`}>
      <div className="flex items-center gap-2">
        <Mail size={14} className="opacity-60" />
        <span className="text-sm font-medium">Contact Card</span>
      </div>
      <select value={profile?.id ?? ''} onChange={e => setSelected(e.target.value)} className={`w-full px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`}>
        {profiles.map(row => <option key={row.id} value={row.id}>{row.display_name}</option>)}
      </select>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <input placeholder="Legal name" value={form.legal_name} onChange={e => updateForm('legal_name', e.target.value)} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
        <input placeholder="Preferred name" value={form.preferred_name} onChange={e => updateForm('preferred_name', e.target.value)} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
        <input placeholder="Email" value={form.email} onChange={e => updateForm('email', e.target.value)} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
        <input placeholder="Phone" value={form.phone} onChange={e => updateForm('phone', e.target.value)} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
        <input type="date" value={form.birthday} onChange={e => updateForm('birthday', e.target.value)} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
        <input placeholder="Notes" value={form.notes} onChange={e => updateForm('notes', e.target.value)} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
      </div>
      <SettingsStatusLine state={state} message={message} />
      <button onClick={save} disabled={state === 'saving' || !profile} className="w-full min-h-11 inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-sm font-mono hover:bg-emerald-500/30 disabled:opacity-40 transition-colors">
        <UserRound size={14} />
        {state === 'saving' ? 'Saving...' : 'Save Contact'}
      </button>
    </div>
  )
}
