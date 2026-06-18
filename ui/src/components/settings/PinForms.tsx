import { useState } from 'react'
import { CheckCircle, Eye, EyeOff, KeyRound, XCircle } from 'lucide-react'
import { apiJson } from '../../lib/apiFetch'
import { useAppStore } from '../../store'

interface PinFormState {
  pin: string
  confirm: string
  show: boolean
  loading: boolean
  result: 'idle' | 'success' | 'error'
  message: string
}

export function PinForm({ profileId, onSuccess }: { profileId: string; onSuccess: () => void }) {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const inputBg = isDark ? 'bg-white/5' : 'bg-[#141414]/5'
  const [form, setForm] = useState<PinFormState>({
    pin: '', confirm: '', show: false, loading: false, result: 'idle', message: ''
  })

  async function handleSubmit() {
    if (form.pin.length < 4) {
      setForm(f => ({ ...f, result: 'error', message: 'PIN must be at least 4 digits' }))
      return
    }
    if (form.pin !== form.confirm) {
      setForm(f => ({ ...f, result: 'error', message: 'PINs do not match' }))
      return
    }
    setForm(f => ({ ...f, loading: true, result: 'idle', message: '' }))
    try {
      await apiJson('/v1/auth/set-profile-pin', {
        method: 'POST',
        body: JSON.stringify({ profile_id: profileId, new_pin: form.pin }),
      })
      setForm(f => ({ ...f, loading: false, result: 'success', message: 'PIN set successfully', pin: '', confirm: '' }))
      onSuccess()
    } catch (e: unknown) {
      setForm(f => ({ ...f, loading: false, result: 'error', message: e instanceof Error ? e.message : 'Failed to set PIN' }))
    }
  }

  return (
    <div className="space-y-3 mt-3">
      <div className="relative">
        <input type={form.show ? 'text' : 'password'} placeholder="New PIN" value={form.pin} onChange={e => setForm(f => ({ ...f, pin: e.target.value }))} className={`w-full px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm font-mono focus:outline-none`} />
        <button onClick={() => setForm(f => ({ ...f, show: !f.show }))} className="absolute right-3 top-2.5 opacity-40 hover:opacity-80">
          {form.show ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>
      <input type={form.show ? 'text' : 'password'} placeholder="Confirm PIN" value={form.confirm} onChange={e => setForm(f => ({ ...f, confirm: e.target.value }))} className={`w-full px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm font-mono focus:outline-none`} />
      {form.result !== 'idle' && (
        <div className={`flex items-center gap-2 text-xs ${form.result === 'success' ? 'text-emerald-400' : 'text-rose-400'}`}>
          {form.result === 'success' ? <CheckCircle size={12} /> : <XCircle size={12} />}
          {form.message}
        </div>
      )}
      <button onClick={handleSubmit} disabled={form.loading} className="w-full min-h-11 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-sm font-mono hover:bg-emerald-500/30 disabled:opacity-40 transition-colors">
        {form.loading ? 'Setting...' : 'Set PIN'}
      </button>
    </div>
  )
}

export function AdminPinForm() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const inputBg = isDark ? 'bg-white/5' : 'bg-[#141414]/5'
  const [form, setForm] = useState({ current: '', next: '', confirm: '', show: false, loading: false, result: 'idle' as 'idle'|'success'|'error', message: '' })

  async function handleSubmit() {
    if (form.next.length < 4) {
      setForm(f => ({ ...f, result: 'error', message: 'PIN must be at least 4 characters' }))
      return
    }
    if (form.next !== form.confirm) {
      setForm(f => ({ ...f, result: 'error', message: 'PINs do not match' }))
      return
    }
    setForm(f => ({ ...f, loading: true, result: 'idle', message: '' }))
    try {
      await apiJson('/v1/auth/set-admin-pin', {
        method: 'POST',
        body: JSON.stringify({ current_pin: form.current, new_pin: form.next }),
      })
      setForm(f => ({ ...f, loading: false, result: 'success', message: 'PIN updated', current: '', next: '', confirm: '' }))
    } catch (e: unknown) {
      setForm(f => ({ ...f, loading: false, result: 'error', message: e instanceof Error ? e.message : 'Failed to update PIN' }))
    }
  }

  return (
    <div className={`p-5 rounded-2xl border ${border} ${isDark ? 'bg-white/5' : 'bg-[#141414]/5'} space-y-3`}>
      <div className="flex items-center gap-2">
        <KeyRound size={14} className="opacity-60" />
        <span className="text-sm font-medium">Change Admin PIN</span>
      </div>
      {(['current', 'next', 'confirm'] as const).map(field => (
        <input key={field} type={form.show ? 'text' : 'password'} placeholder={field === 'current' ? 'Current PIN' : field === 'next' ? 'New PIN' : 'Confirm New PIN'} value={form[field]} onChange={e => setForm(f => ({ ...f, [field]: e.target.value }))} className={`w-full px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm font-mono focus:outline-none`} />
      ))}
      <button onClick={() => setForm(f => ({ ...f, show: !f.show }))} className="min-h-11 inline-flex items-center gap-2 text-xs opacity-50 hover:opacity-90">
        {form.show ? <EyeOff size={12} /> : <Eye size={12} />}
        {form.show ? 'Hide' : 'Show'} PINs
      </button>
      {form.result !== 'idle' && (
        <div className={`flex items-center gap-2 text-xs ${form.result === 'success' ? 'text-emerald-400' : 'text-rose-400'}`}>
          {form.result === 'success' ? <CheckCircle size={12} /> : <XCircle size={12} />}
          {form.message}
        </div>
      )}
      <button onClick={handleSubmit} disabled={form.loading} className="w-full min-h-11 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-sm font-mono hover:bg-emerald-500/30 disabled:opacity-40 transition-colors">
        {form.loading ? 'Updating...' : 'Update PIN'}
      </button>
    </div>
  )
}
