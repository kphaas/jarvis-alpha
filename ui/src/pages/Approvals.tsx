import { useEffect, useState, useCallback } from 'react'
import { motion } from 'framer-motion'
import { ShieldCheck, ShieldX, Clock, AlertTriangle } from 'lucide-react'
import { apiJson, apiFetch } from '../lib/apiFetch'
import { useAppStore } from '../store'

interface PendingApproval {
  step_id: string
  step_name: string
  step_type: string
  input: Record<string, unknown> | null
  graph_id: string
  graph_title: string
  content_tier: string
  user_type: string
  priority: number
  created_at: string
}

interface PendingResponse {
  pending: PendingApproval[]
  count: number
}

const REFRESH_MS = 30_000

function priorityBadge(p: number) {
  const color =
    p <= 2
      ? 'text-rose-400 bg-rose-500/15 border-rose-500/30'
      : p <= 5
        ? 'text-amber-400 bg-amber-500/15 border-amber-500/30'
        : 'text-zinc-400 bg-zinc-500/15 border-zinc-500/30'
  return (
    <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${color}`}>
      P{p}
    </span>
  )
}

function tierBadge(tier: string) {
  const map: Record<string, string> = {
    unrestricted: 'text-zinc-400 bg-zinc-500/15 border-zinc-500/30',
    filtered: 'text-yellow-400 bg-yellow-500/15 border-yellow-500/30',
    child_safe: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30',
  }
  const cls = map[tier] ?? map.unrestricted
  return (
    <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${cls}`}>
      {tier}
    </span>
  )
}

function userTypeBadge(ut: string) {
  const cls =
    ut === 'child'
      ? 'text-blue-400 bg-blue-500/15 border-blue-500/30'
      : 'text-zinc-400 bg-zinc-500/15 border-zinc-500/30'
  return (
    <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${cls}`}>
      {ut}
    </span>
  )
}

function truncateJson(obj: Record<string, unknown> | null, maxLen = 200): string {
  if (!obj) return '{}'
  const s = JSON.stringify(obj, null, 2)
  return s.length > maxLen ? s.slice(0, maxLen) + '...' : s
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

  const load = useCallback(async () => {
    try {
      const res = await apiJson<PendingResponse>('/v1/tasks/pending-approvals')
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

  const handleAction = async (stepId: string, action: 'approve' | 'deny') => {
    setActing(stepId)
    try {
      await apiFetch(`/v1/tasks/steps/${stepId}/${action}`, { method: 'POST' })
      await load()
    } catch {
      // refresh anyway
      await load()
    } finally {
      setActing(null)
    }
  }

  const pending = data?.pending ?? []
  const count = data?.count ?? 0

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="space-y-6 max-w-4xl">
      <div className="flex items-center gap-3">
        <h1 className="font-serif italic text-3xl">Pending Approvals</h1>
        {count > 0 && (
          <span className="text-xs font-mono font-bold px-2.5 py-1 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">
            {count}
          </span>
        )}
      </div>

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

      {pending.map((item) => (
        <div key={item.step_id} className={`p-5 rounded-2xl border ${border} ${subtle} space-y-3`}>
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-bold">{item.graph_title}</span>
                {priorityBadge(item.priority)}
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-mono opacity-60">{item.step_name}</span>
                <span className="text-[10px] font-mono opacity-40">{item.step_type}</span>
              </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              {tierBadge(item.content_tier)}
              {userTypeBadge(item.user_type)}
            </div>
          </div>

          <div className={`p-3 rounded-lg text-xs font-mono whitespace-pre-wrap break-all ${isDark ? 'bg-black/30' : 'bg-black/5'} opacity-70`}>
            {truncateJson(item.input)}
          </div>

          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-1.5 text-xs opacity-40">
              <Clock className="w-3 h-3" />
              {new Date(item.created_at).toLocaleString()}
            </div>
            <div className="flex items-center gap-2">
              <button
                disabled={acting === item.step_id}
                onClick={() => handleAction(item.step_id, 'approve')}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-bold bg-emerald-600 hover:bg-emerald-500 text-white transition-colors disabled:opacity-40"
              >
                <ShieldCheck className="w-3.5 h-3.5" />
                Approve
              </button>
              <button
                disabled={acting === item.step_id}
                onClick={() => handleAction(item.step_id, 'deny')}
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
