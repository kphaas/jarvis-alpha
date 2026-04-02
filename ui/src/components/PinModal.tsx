import { useState } from 'react'
import { motion } from 'framer-motion'
import { Lock } from 'lucide-react'
import { apiJson } from '../lib/apiFetch'
import type { Theme } from '../types'

interface Props {
  theme: Theme
  title?: string
  subtitle?: string
  onUnlock: () => void
  onCancel: () => void
}

export function PinModal({ theme, title = 'Vault', subtitle = 'Enter PIN to unlock', onUnlock, onCancel }: Props) {
  const [pin, setPin] = useState('')
  const [error, setError] = useState(false)
  const [checking, setChecking] = useState(false)
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'

  const submit = async () => {
    if (!pin.trim()) return
    setChecking(true)
    setError(false)
    const res = await apiJson<{ token: string }>('/v1/auth/pin', { method: 'POST', body: JSON.stringify({ pin }) })
    const valid = !!(res?.token)
    setChecking(false)
    if (valid) { onUnlock(); setPin('') }
    else { setError(true); setPin('') }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <motion.div
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        onClick={onCancel}
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
      />
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 10 }}
        className={`relative p-10 rounded-3xl border shadow-2xl w-full max-w-sm text-center space-y-6 ${isDark ? 'bg-[#0F0F0F]' : 'bg-white'} ${border}`}
      >
        <div className={`w-16 h-16 rounded-2xl flex items-center justify-center mx-auto ${isDark ? 'bg-emerald-500 text-[#0A0A0A]' : 'bg-[#141414] text-[#E4E3E0]'}`}>
          <Lock className="w-7 h-7" />
        </div>
        <div>
          <h3 className="font-serif italic text-2xl mb-1">{title}</h3>
          <p className="text-[10px] font-mono uppercase opacity-50">{subtitle}</p>
        </div>
        <input
          type="password"
          value={pin}
          onChange={e => setPin(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && submit()}
          placeholder="Enter PIN"
          maxLength={12}
          autoFocus
          className={`w-full px-4 py-3 rounded-xl border text-center font-mono text-lg tracking-widest focus:outline-none focus:ring-2 transition-all bg-transparent ${error ? 'border-rose-500 focus:ring-rose-500/20' : `${border} focus:ring-emerald-500/20`}`}
        />
        {error && <p className="text-[10px] font-mono text-rose-500 uppercase">Incorrect PIN — try again</p>}
        <button
          onClick={submit}
          disabled={checking || !pin.trim()}
          className={`w-full py-3 rounded-xl font-bold transition-all disabled:opacity-50 ${isDark ? 'bg-emerald-500 text-[#0A0A0A]' : 'bg-[#141414] text-[#E4E3E0]'}`}
        >
          {checking ? 'Verifying...' : 'Unlock'}
        </button>
        <p className="text-[9px] font-mono opacity-20 uppercase">Session unlock · Resets on refresh</p>
      </motion.div>
    </div>
  )
}
