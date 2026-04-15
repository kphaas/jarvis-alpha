import { useState } from 'react'
import { motion } from 'framer-motion'
import { User, Lock, CheckCircle, XCircle, Eye, EyeOff, KeyRound } from 'lucide-react'
import { apiJson } from '../lib/apiFetch'
import { useAppStore } from '../store'

interface Profile {
  id: string
  display_name: string
  role: string
  child_age?: number
  max_rating: string
  pin_status: 'set' | 'placeholder'
}

interface PinFormState {
  pin: string
  confirm: string
  show: boolean
  loading: boolean
  result: 'idle' | 'success' | 'error'
  message: string
}

const RATING_LABEL: Record<string, string> = {
  all_ages:  'All Ages',
  age_8_plus: '8+',
  teen:      'Teen',
  adult:     'Adult',
}

function PinForm({ profileId, onSuccess }: { profileId: string; onSuccess: () => void }) {
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
      await apiJson('/v1/auth/set-child-pin', {
        method: 'POST',
        body: JSON.stringify({ profile_id: profileId, new_pin: form.pin }),
      })
      setForm(f => ({ ...f, loading: false, result: 'success', message: 'PIN set successfully', pin: '', confirm: '' }))
      onSuccess()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to set PIN'
      setForm(f => ({ ...f, loading: false, result: 'error', message: msg }))
    }
  }

  return (
    <div className="space-y-3 mt-3">
      <div className="relative">
        <input
          type={form.show ? 'text' : 'password'}
          placeholder="New PIN"
          value={form.pin}
          onChange={e => setForm(f => ({ ...f, pin: e.target.value }))}
          className={`w-full px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm font-mono focus:outline-none`}
        />
        <button
          onClick={() => setForm(f => ({ ...f, show: !f.show }))}
          className="absolute right-3 top-2.5 opacity-40 hover:opacity-80"
        >
          {form.show ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>
      <input
        type={form.show ? 'text' : 'password'}
        placeholder="Confirm PIN"
        value={form.confirm}
        onChange={e => setForm(f => ({ ...f, confirm: e.target.value }))}
        className={`w-full px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm font-mono focus:outline-none`}
      />
      {form.result !== 'idle' && (
        <div className={`flex items-center gap-2 text-xs ${form.result === 'success' ? 'text-emerald-400' : 'text-rose-400'}`}>
          {form.result === 'success' ? <CheckCircle size={12} /> : <XCircle size={12} />}
          {form.message}
        </div>
      )}
      <button
        onClick={handleSubmit}
        disabled={form.loading}
        className="w-full py-2 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-sm font-mono hover:bg-emerald-500/30 disabled:opacity-40 transition-colors"
      >
        {form.loading ? 'Setting...' : 'Set PIN'}
      </button>
    </div>
  )
}

function AdminPinForm() {
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
      const msg = e instanceof Error ? e.message : 'Failed to update PIN'
      setForm(f => ({ ...f, loading: false, result: 'error', message: msg }))
    }
  }

  return (
    <div className={`p-5 rounded-2xl border ${border} ${isDark ? 'bg-white/5' : 'bg-[#141414]/5'} space-y-3`}>
      <div className="flex items-center gap-2">
        <KeyRound size={14} className="opacity-60" />
        <span className="text-sm font-medium">Change Admin PIN</span>
      </div>
      {(['current', 'next', 'confirm'] as const).map(field => (
        <div key={field} className="relative">
          <input
            type={form.show ? 'text' : 'password'}
            placeholder={field === 'current' ? 'Current PIN' : field === 'next' ? 'New PIN' : 'Confirm New PIN'}
            value={form[field]}
            onChange={e => setForm(f => ({ ...f, [field]: e.target.value }))}
            className={`w-full px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm font-mono focus:outline-none`}
          />
        </div>
      ))}
      <div className="flex items-center gap-2 text-xs opacity-40">
        <button onClick={() => setForm(f => ({ ...f, show: !f.show }))}>
          {form.show ? <EyeOff size={12} /> : <Eye size={12} />}
        </button>
        <span>{form.show ? 'Hide' : 'Show'} PINs</span>
      </div>
      {form.result !== 'idle' && (
        <div className={`flex items-center gap-2 text-xs ${form.result === 'success' ? 'text-emerald-400' : 'text-rose-400'}`}>
          {form.result === 'success' ? <CheckCircle size={12} /> : <XCircle size={12} />}
          {form.message}
        </div>
      )}
      <button
        onClick={handleSubmit}
        disabled={form.loading}
        className="w-full py-2 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-sm font-mono hover:bg-emerald-500/30 disabled:opacity-40 transition-colors"
      >
        {form.loading ? 'Updating...' : 'Update PIN'}
      </button>
    </div>
  )
}

function ProfileCard({ profile }: { profile: Profile }) {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/5' : 'bg-[#141414]/5'
  const [expanded, setExpanded] = useState(profile.pin_status === 'placeholder')
  const [pinSet, setPinSet] = useState(profile.pin_status === 'set')

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
      className={`p-5 rounded-2xl border ${border} ${subtle} space-y-3`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`w-9 h-9 rounded-full flex items-center justify-center ${subtle} border ${border}`}>
            <User size={16} className="opacity-60" />
          </div>
          <div>
            <p className="font-medium text-sm">{profile.display_name}</p>
            <p className="text-[10px] font-mono uppercase opacity-40">
              {profile.role} · {RATING_LABEL[profile.max_rating] ?? profile.max_rating}
              {profile.child_age ? ` · Age ${profile.child_age}` : ''}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-mono px-2 py-0.5 rounded border ${pinSet ? 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30' : 'text-amber-400 bg-amber-500/15 border-amber-500/30'}`}>
            {pinSet ? 'PIN SET' : 'PIN REQUIRED'}
          </span>
          {profile.role === 'child' && (
            <button
              onClick={() => setExpanded(e => !e)}
              className="opacity-40 hover:opacity-80 transition-opacity"
            >
              <Lock size={14} />
            </button>
          )}
        </div>
      </div>

      {profile.role === 'child' && expanded && (
        <PinForm
          profileId={profile.id}
          onSuccess={() => { setPinSet(true); setExpanded(false) }}
        />
      )}
    </motion.div>
  )
}

export default function Settings() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'

  const profiles: Profile[] = [
    { id: 'ken',     display_name: 'Ken',     role: 'admin',  max_rating: 'adult',     pin_status: 'set' },
    { id: 'ryleigh', display_name: 'Ryleigh', role: 'child',  max_rating: 'age_8_plus', child_age: 8, pin_status: 'set' },
    { id: 'sloane',  display_name: 'Sloane',  role: 'child',  max_rating: 'all_ages',   child_age: 5, pin_status: 'placeholder' },
  ]

  return (
    <div className="space-y-8 max-w-xl">
      <div>
        <h1 className={`font-serif italic text-3xl ${isDark ? 'text-white' : 'text-[#141414]'}`}>Settings</h1>
        <p className="text-[10px] font-mono uppercase opacity-40 mt-1">Alpha-2 · Profiles &amp; Security</p>
      </div>

      <section className="space-y-3">
        <h2 className="text-xs font-mono uppercase opacity-40 tracking-widest">Family Profiles</h2>
        {profiles.map(p => <ProfileCard key={p.id} profile={p} />)}
      </section>

      <section className="space-y-3">
        <h2 className="text-xs font-mono uppercase opacity-40 tracking-widest">Admin Security</h2>
        <AdminPinForm />
      </section>
    </div>
  )
}
