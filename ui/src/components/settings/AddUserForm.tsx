import { Plus } from 'lucide-react'
import { useState } from 'react'
import { apiJson } from '../../lib/apiFetch'
import { useAppStore } from '../../store'
import { SettingsStatusLine, type SaveState } from './SettingsStatusLine'

const EMPTY_USER_FORM = {
  display_name: '',
  id: '',
  role: 'admin',
  child_age: '',
  max_rating: 'adult',
}

export function AddUserForm({ onSaved }: { onSaved: () => void }) {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const inputBg = isDark ? 'bg-white/5' : 'bg-[#141414]/5'
  const [form, setForm] = useState(EMPTY_USER_FORM)
  const [state, setState] = useState<SaveState>('idle')
  const [message, setMessage] = useState('')

  async function save() {
    setState('saving')
    setMessage('')
    try {
      await apiJson('/v1/settings/users', {
        method: 'POST',
        body: JSON.stringify({
          display_name: form.display_name,
          id: form.id || null,
          role: form.role,
          child_age: form.role === 'child' ? Number(form.child_age) : null,
          max_rating: form.role === 'child' ? form.max_rating : 'adult',
        }),
      })
      setForm(EMPTY_USER_FORM)
      setState('success')
      setMessage('User added')
      onSaved()
    } catch (e: unknown) {
      setState('error')
      setMessage(e instanceof Error ? e.message : 'Failed to add user')
    }
  }

  return (
    <div className={`p-5 rounded-2xl border ${border} ${isDark ? 'bg-white/5' : 'bg-[#141414]/5'} space-y-3`}>
      <div className="flex items-center gap-2">
        <Plus size={14} className="opacity-60" />
        <span className="text-sm font-medium">Add User</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <input placeholder="Display name" value={form.display_name} onChange={e => setForm(f => ({ ...f, display_name: e.target.value }))} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
        <input placeholder="ID" value={form.id} onChange={e => setForm(f => ({ ...f, id: e.target.value.toLowerCase() }))} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm font-mono focus:outline-none`} />
        <select value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value, max_rating: e.target.value === 'admin' ? 'adult' : 'all_ages' }))} className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`}>
          <option value="admin">Admin</option>
          <option value="child">Child</option>
        </select>
        {form.role === 'child' ? (
          <input placeholder="Age" value={form.child_age} onChange={e => setForm(f => ({ ...f, child_age: e.target.value }))} inputMode="numeric" className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
        ) : (
          <div className={`px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm opacity-40`}>Adult rating</div>
        )}
      </div>
      {form.role === 'child' && (
        <select value={form.max_rating} onChange={e => setForm(f => ({ ...f, max_rating: e.target.value }))} className={`w-full px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`}>
          <option value="all_ages">All Ages</option>
          <option value="age_8_plus">8+</option>
          <option value="teen">Teen</option>
        </select>
      )}
      <SettingsStatusLine state={state} message={message} />
      <button onClick={save} disabled={state === 'saving' || !form.display_name} className="w-full min-h-11 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-sm font-mono hover:bg-emerald-500/30 disabled:opacity-40 transition-colors">
        {state === 'saving' ? 'Adding...' : 'Add User'}
      </button>
    </div>
  )
}
