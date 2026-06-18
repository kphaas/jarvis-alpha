import { Home, Save } from 'lucide-react'
import { useState } from 'react'
import { apiJson } from '../../lib/apiFetch'
import { useAppStore } from '../../store'
import { SettingsStatusLine, type SaveState } from './SettingsStatusLine'
import { toAddressForm } from './personalDataForms'
import type { IdentitySettings } from './types'

export function HomeAddressForm({ identity, onSaved }: { identity: IdentitySettings; onSaved: () => void }) {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const inputBg = isDark ? 'bg-white/5' : 'bg-[#141414]/5'
  const [form, setForm] = useState(toAddressForm(identity.personal_data.home_address))
  const [state, setState] = useState<SaveState>('idle')
  const [message, setMessage] = useState('')

  async function save() {
    setState('saving')
    setMessage('')
    try {
      await apiJson('/v1/settings/personal-data/home-address', {
        method: 'PUT',
        body: JSON.stringify({
          label: form.label || 'Home',
          line1: form.line1 || null,
          line2: form.line2 || null,
          city: form.city || null,
          region: form.region || null,
          postal_code: form.postal_code || null,
          country: form.country || 'US',
        }),
      })
      setState('success')
      setMessage('Home address saved')
      onSaved()
    } catch (e: unknown) {
      setState('error')
      setMessage(e instanceof Error ? e.message : 'Failed to save home address')
    }
  }

  return (
    <div className={`p-5 rounded-2xl border ${border} ${isDark ? 'bg-white/5' : 'bg-[#141414]/5'} space-y-3`}>
      <div className="flex items-center gap-2">
        <Home size={14} className="opacity-60" />
        <span className="text-sm font-medium">Home Address</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <input placeholder="Label" value={form.label} onChange={e => setForm(f => ({ ...f, label: e.target.value }))} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
        <input placeholder="Country" value={form.country} onChange={e => setForm(f => ({ ...f, country: e.target.value.toUpperCase() }))} maxLength={2} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm font-mono focus:outline-none`} />
        <input placeholder="Address line 1" value={form.line1} onChange={e => setForm(f => ({ ...f, line1: e.target.value }))} className={`sm:col-span-2 px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
        <input placeholder="Address line 2" value={form.line2} onChange={e => setForm(f => ({ ...f, line2: e.target.value }))} className={`sm:col-span-2 px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
        <input placeholder="City" value={form.city} onChange={e => setForm(f => ({ ...f, city: e.target.value }))} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
        <input placeholder="State" value={form.region} onChange={e => setForm(f => ({ ...f, region: e.target.value }))} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
        <input placeholder="ZIP" value={form.postal_code} onChange={e => setForm(f => ({ ...f, postal_code: e.target.value }))} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
      </div>
      <SettingsStatusLine state={state} message={message} />
      <button onClick={save} disabled={state === 'saving'} className="w-full min-h-11 inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-sm font-mono hover:bg-emerald-500/30 disabled:opacity-40 transition-colors">
        <Save size={14} />
        {state === 'saving' ? 'Saving...' : 'Save Address'}
      </button>
    </div>
  )
}
