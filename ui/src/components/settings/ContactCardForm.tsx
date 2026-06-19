import { Mail, UserRound } from 'lucide-react'
import { useMemo, useState } from 'react'
import { apiJson } from '../../lib/apiFetch'
import { useAppStore } from '../../store'
import { SettingsStatusLine, type SaveState } from './SettingsStatusLine'
import { EMPTY_CONTACT, toContactForm, type ContactFormDraft } from './personalDataForms'
import type { Profile } from './types'

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function isEmailValid(value: string) {
  return !value.trim() || EMAIL_RE.test(value.trim().toLowerCase())
}

function formatPhone(value: string) {
  const digits = value.replace(/\D/g, '')
  const normalized = digits.length === 11 && digits.startsWith('1') ? digits.slice(1) : digits
  if (normalized.length !== 10) return value
  return `${normalized.slice(0, 3)}-${normalized.slice(3, 6)}-${normalized.slice(6)}`
}

function isPhoneValid(value: string) {
  return !value.trim() || /^\d{3}-\d{3}-\d{4}$/.test(formatPhone(value.trim()))
}

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
  const emailInvalid = Boolean(form.email && !isEmailValid(form.email))
  const phoneInvalid = Boolean(form.phone && !isPhoneValid(form.phone))

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
    if (emailInvalid || phoneInvalid) {
      setState('error')
      setMessage('Fix email or phone before saving')
      return
    }
    setState('saving')
    setMessage('')
    const formattedPhone = formatPhone(form.phone.trim())
    try {
      await apiJson(`/v1/settings/users/${profile.id}/personal-data`, {
        method: 'PUT',
        body: JSON.stringify({
          legal_name: form.legal_name || null,
          preferred_name: form.preferred_name || null,
          email: form.email.trim().toLowerCase() || null,
          phone: formattedPhone || null,
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
        <label className="space-y-1">
          <input type="email" placeholder="Email" value={form.email} aria-invalid={emailInvalid} onChange={e => updateForm('email', e.target.value)} className={`w-full px-3 py-2 rounded-lg border ${emailInvalid ? 'border-rose-500/60' : border} ${inputBg} text-sm focus:outline-none`} />
          {emailInvalid ? <span className="block text-xs text-rose-400">Use an email like name@example.com.</span> : null}
        </label>
        <label className="space-y-1">
          <input inputMode="tel" placeholder="Phone 555-555-5555" value={form.phone} aria-invalid={phoneInvalid} onBlur={() => updateForm('phone', formatPhone(form.phone))} onChange={e => updateForm('phone', e.target.value)} className={`w-full px-3 py-2 rounded-lg border ${phoneInvalid ? 'border-rose-500/60' : border} ${inputBg} text-sm focus:outline-none`} />
          {phoneInvalid ? <span className="block text-xs text-rose-400">Use a 10 digit phone like 555-555-5555.</span> : null}
        </label>
        <input type="date" value={form.birthday} onChange={e => updateForm('birthday', e.target.value)} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
        <input placeholder="Notes" value={form.notes} onChange={e => updateForm('notes', e.target.value)} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
      </div>
      <SettingsStatusLine state={state} message={message} />
      <button onClick={save} disabled={state === 'saving' || !profile || emailInvalid || phoneInvalid} className="w-full min-h-11 inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-sm font-mono hover:bg-emerald-500/30 disabled:opacity-40 transition-colors">
        <UserRound size={14} />
        {state === 'saving' ? 'Saving...' : 'Save Contact'}
      </button>
    </div>
  )
}
