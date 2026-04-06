import { useEffect, useState, useCallback } from 'react'
import { motion } from 'framer-motion'
import { ShieldCheck, ShieldX, Clock, AlertTriangle, Lock, Unlock } from 'lucide-react'
import { apiJson } from '../lib/apiFetch'
import { useAppStore } from '../store'

interface QueueItem {
  id: string
  action_class: string[]
  risk_tier: string
  actor_sub: string
  actor_type: string
  description: string
  status: string
  requested_at: string
  expires_at: string
  overnight: boolean
}

interface PendingResponse {
  pending: QueueItem[]
  count: number
}

interface DecideResponse {
  queue_id: string
  decision: string
  description: string
  expires_at: string | null
}

const REFRESH_MS = 10_000

const TIER_COLORS: Record<string, string> = {
  T4: 'text-amber-400 bg-amber-500/15 border-amber-500/30',
  T5: 'text-rose-400 bg-rose-500/15 border-rose-500/30',
}

const ACTION_LABELS: Record<string, string> = {
  destructive: 'Permanently deletes data',
  admin: 'Changes system config or permissions',
  deploy: 'Deploys to a live node',
  child_facing: 'Affects content for Ryleigh or Sloane',
  unclassified: 'No classification — blocked by default',
}

function tierBadge(tier: string) {
  const cls = TIER_COLORS[tier] ?? 'text-zinc-400 bg-zinc-500/15 border-zinc-500/30'
  return (
    <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${cls}`}>
      {tier}
    </span>
  )
}

function actionBadge(ac: string) {
  const colors: Record<string, string> = {
    destructive: 'text-rose-400 bg-rose-500/15 border-rose-500/30',
    admin: 'text-purple-400 bg-purple-500/15 border-purple-500/30',
    deploy: 'text-blue-400 bg-blue-500/15 border-blue-500/30',
    child_facing: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30',
    unclassified: 'text-zinc-400 bg-zinc-500/15 border-zinc-500/30',
  }
  const cls = colors[ac] ?? colors.unclassified
  return (
    <span key={ac} className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${cls}`}>
      {ac}
    </span>
  )
}

function timeLeft(expiresAt: string): string {
  const ms = new Date(expiresAt).getTime() - Date.now()
  if (ms <= 0) return 'Expired'
  const mins = Math.floor(ms / 60000)
  const secs = Math.floor((ms % 60000) / 1000)
  return `${mins}m ${secs}s left`
}

export default function Approvals() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/5' : 'bg-[#141414]/5'

  const [data, setData] = useState<PendingResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [acting, setActing] = useState<string | null>(null)
  const [approvalToken, setApprovalToken] = useState<string | null>(null)
  const [tokenExpiry, setTokenExpiry] = useState<number>(0)
  const [pinInput, setPinInput] = useState('')
  const [showPinModal, setShowPinModal] = useState(false)
  const [pinError, setPinError] = useState<string | null>(null)
  const [actionResult, setActionResult] = useState<{ id: string; decision: string } | null>(null)

  const isUnlocked = approvalToken && Date.now() < tokenExpiry

  const load = useCallback(async () => {
    try {
      const res = await apiJson<PendingResponse>('/v1/approvals/pending')
      setData(res)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => clearInterval(id)
  }, [load])

  const handleUnlock = async () => {
    setPinError(null)
    try {
      const res = await apiJson<{ approval_token: string; expires_in: number }>(
        '/v1/approvals/unlock',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pin: pinInput }),
        }
      )
      setApprovalToken(res.approval_token)
      setTokenExpiry(Date.now() + res.expires_in * 1000)
      setShowPinModal(false)
      setPinInput('')
    } catch {
      setPinError('Invalid PIN')
    }
  }

  const handleDecide = async (queueId: string, decision: 'approved' | 'denied') => {
    if (!isUnlocked) {
      setShowPinModal(true)
      return
    }
    setActing(queueId)
    setActionResult(null)
    try {
      const res = await apiJson<DecideResponse>(
        `/v1/approvals/${queueId}/decide`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Approval-Token': approvalToken!,
          },
          body: JSON.stringify({ decision }),
        }
      )
      setActionResult({ id: queueId, decision: res.decision })
      await load()
    } catch (e) {
      if (e instanceof Error && e.message.includes('403')) {
        setApprovalToken(null)
        setShowPinModal(true)
      }
    } finally {
      setActing(null)
    }
  }

  const pending = data?.pending ?? []
  const count = data?.count ?? 0

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="space-y-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <h1 className="font-serif italic text-3xl">Approvals</h1>
          {count > 0 && (
            <span className="text-xs font-mono font-bold px-2.5 py-1 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">
              {count}
            </span>
          )}
        </div>
        <button
          onClick={() => isUnlocked ? setApprovalToken(null) : setShowPinModal(true)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-colors border ${
            isUnlocked
              ? 'bg-emerald-600/20 border-emerald-500/30 text-emerald-400 hover:bg-emerald-600/30'
              : 'bg-zinc-600/20 border-zinc-500/30 text-zinc-400 hover:bg-zinc-600/30'
          }`}
        >
          {isUnlocked ? <Unlock className="w-3.5 h-3.5" /> : <Lock className="w-3.5 h-3.5" />}
          {isUnlocked ? 'Unlocked' : 'Locked'}
        </button>
      </div>

      {/* PIN Modal */}
      {showPinModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className={`p-6 rounded-2xl border ${border} ${isDark ? 'bg-zinc-900' : 'bg-white'} w-80 space-y-4`}>
            <div className="flex items-center gap-2">
              <Lock className="w-5 h-5 text-amber-400" />
              <h2 className="font-bold text-lg">Enter PIN to Approve</h2>
            </div>
            <p className="text-xs opacity-60">Unlocks approve/deny for 5 minutes.</p>
            <input
              type="password"
              autoFocus
              value={pinInput}
              onChange={(e) => setPinInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleUnlock()}
              placeholder="PIN"
              className={`w-full px-3 py-2 rounded-lg border text-center text-lg tracking-widest font-mono ${border} ${isDark ? 'bg-black/30' : 'bg-black/5'}`}
            />
            {pinError && <p className="text-xs text-rose-400">{pinError}</p>}
            <div className="flex gap-2">
              <button
                onClick={() => { setShowPinModal(false); setPinInput(''); setPinError(null) }}
                className={`flex-1 px-3 py-2 rounded-lg text-xs font-bold border ${border} hover:opacity-80`}
              >
                Cancel
              </button>
              <button
                onClick={handleUnlock}
                className="flex-1 px-3 py-2 rounded-lg text-xs font-bold bg-amber-600 hover:bg-amber-500 text-white"
              >
                Unlock
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Action result toast */}
      {actionResult && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className={`flex items-center gap-2 p-3 rounded-xl text-sm ${
            actionResult.decision === 'approved'
              ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400'
              : 'bg-rose-500/10 border border-rose-500/20 text-rose-400'
          }`}
        >
          {actionResult.decision === 'approved' ? <ShieldCheck className="w-4 h-4" /> : <ShieldX className="w-4 h-4" />}
          Request {actionResult.decision}
        </motion.div>
      )}

      {loading && <p className="text-sm opacity-40">Loading...</p>}

      {error && (
        <div className="flex items-center gap-2 p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {!loading && !error && pending.length === 0 && (
        <div className={`flex flex-col items-center justify-center py-16 rounded-2xl border ${border} ${subtle}`}>
          <ShieldCheck className="w-10 h-10 text-emerald-500 mb-3" />
          <p className="text-sm font-medium opacity-60">No pending approvals</p>
        </div>
      )}

      {/* Pending items */}
      {pending.map((item) => (
        <div key={item.id} className={`p-5 rounded-2xl border ${border} ${subtle} space-y-3`}>
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="space-y-1.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-bold font-mono">{item.description}</span>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                {tierBadge(item.risk_tier)}
                {item.action_class.map(ac => actionBadge(ac))}
                {item.overnight && (
                  <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border text-indigo-400 bg-indigo-500/15 border-indigo-500/30">
                    overnight
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Risk context */}
          <div className={`p-3 rounded-lg text-xs space-y-1 ${isDark ? 'bg-black/30' : 'bg-black/5'}`}>
            {item.action_class.map(ac => {
              const label = ACTION_LABELS[ac]
              return label ? (
                <div key={ac} className="flex items-start gap-2 opacity-70">
                  <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0 text-amber-400" />
                  <span><strong>{ac}:</strong> {label}</span>
                </div>
              ) : null
            })}
          </div>

          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-3 text-xs opacity-40">
              <div className="flex items-center gap-1.5">
                <Clock className="w-3 h-3" />
                {new Date(item.requested_at).toLocaleString()}
              </div>
              <span className="font-mono">{timeLeft(item.expires_at)}</span>
              <span className="font-mono opacity-60">by {item.actor_sub}</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                disabled={acting === item.id}
                onClick={() => handleDecide(item.id, 'approved')}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-bold bg-emerald-600 hover:bg-emerald-500 text-white transition-colors disabled:opacity-40"
              >
                <ShieldCheck className="w-3.5 h-3.5" />
                Approve
              </button>
              <button
                disabled={acting === item.id}
                onClick={() => handleDecide(item.id, 'denied')}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-bold bg-rose-600 hover:bg-rose-500 text-white transition-colors disabled:opacity-40"
              >
                <ShieldX className="w-3.5 h-3.5" />
                Deny
              </button>
            </div>
          </div>
        </div>
      ))}
    </motion.div>
  )
}
