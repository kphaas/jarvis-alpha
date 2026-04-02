import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { DollarSign } from 'lucide-react'
import { getNodes } from '../api'
import { apiJson } from '../lib/apiFetch'
import { useAppStore } from '../store'

interface HealthPayload {
  status: string
  uptime_seconds?: number
  node: string
}

interface CostsSummaryPayload {
  total_usd: number
  budget_usd: number
}

interface GraphTaskRow {
  graph_id: string
  status: string
  created_at: string
}

function formatUptime(total: number): string {
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  return `${h}h ${m}m`
}

function formatRelativeTime(iso: string): string {
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return iso
  let diffSec = Math.floor((Date.now() - t) / 1000)
  if (diffSec < 0) diffSec = 0
  if (diffSec < 45) return 'just now'
  if (diffSec < 90) return '1 minute ago'
  const minutes = Math.floor(diffSec / 60)
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} day${days === 1 ? '' : 's'} ago`
  const months = Math.floor(days / 30)
  return `${months} month${months === 1 ? '' : 's'} ago`
}

export default function Home() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/5' : 'bg-[#141414]/5'

  const { data: nodes } = useQuery({ queryKey: ['nodes'], queryFn: getNodes, refetchInterval: 60000 })

  const [health, setHealth] = useState<HealthPayload | null>(null)
  const [healthLoading, setHealthLoading] = useState(true)
  const [healthErr, setHealthErr] = useState(false)

  const [costs, setCosts] = useState<CostsSummaryPayload | null>(null)
  const [costsLoading, setCostsLoading] = useState(true)
  const [costsErr, setCostsErr] = useState(false)

  const [graphs, setGraphs] = useState<GraphTaskRow[] | null>(null)
  const [graphsLoading, setGraphsLoading] = useState(true)
  const [graphsErr, setGraphsErr] = useState(false)

  useEffect(() => {
    let alive = true
    setHealthLoading(true)
    setHealthErr(false)
    apiJson<HealthPayload>('/health')
      .then((d) => {
        if (alive) {
          setHealth(d)
          setHealthErr(false)
        }
      })
      .catch(() => {
        if (alive) {
          setHealth(null)
          setHealthErr(true)
        }
      })
      .finally(() => {
        if (alive) setHealthLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    let alive = true
    setCostsLoading(true)
    setCostsErr(false)
    apiJson<CostsSummaryPayload>('/v1/costs/summary')
      .then((d) => {
        if (alive) {
          setCosts(d)
          setCostsErr(false)
        }
      })
      .catch(() => {
        if (alive) {
          setCosts(null)
          setCostsErr(true)
        }
      })
      .finally(() => {
        if (alive) setCostsLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    let alive = true
    setGraphsLoading(true)
    setGraphsErr(false)
    apiJson<GraphTaskRow[]>('/v1/tasks/graphs?limit=1')
      .then((d) => {
        if (alive) {
          setGraphs(d)
          setGraphsErr(false)
        }
      })
      .catch(() => {
        if (alive) {
          setGraphs(null)
          setGraphsErr(true)
        }
      })
      .finally(() => {
        if (alive) setGraphsLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  const nodeList = ['brain', 'gateway', 'endpoint', 'sandbox'] as const
  const brainOk = health?.status === 'ok'

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="space-y-8 max-w-5xl">

      <div>
        <h1 className="font-serif italic text-3xl">Home</h1>
        <p className="text-[10px] font-mono uppercase opacity-50 mt-1">System overview · {new Date().toLocaleDateString()}</p>
      </div>

      {/* System Status */}
      <section>
        <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">System Status</p>
        <div className={`p-4 rounded-2xl border ${border} ${subtle}`}>
          {healthLoading && <p className="text-sm opacity-40">Loading...</p>}
          {!healthLoading && healthErr && (
            <>
              <p className="text-sm opacity-40">—</p>
              <p className="text-xs text-rose-500 mt-2">Failed to load</p>
            </>
          )}
          {!healthLoading && !healthErr && health && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <p className="text-[10px] font-mono uppercase opacity-40 mb-2">Status</p>
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${health.status === 'ok' ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                  <span className="text-sm font-bold font-mono">{health.status}</span>
                </div>
              </div>
              <div>
                <p className="text-[10px] font-mono uppercase opacity-40 mb-2">Uptime</p>
                <p className="text-sm font-bold">{health?.uptime_seconds != null ? formatUptime(health.uptime_seconds) : '—'}</p>
              </div>
              <div>
                <p className="text-[10px] font-mono uppercase opacity-40 mb-2">Node</p>
                <p className="text-sm font-bold font-mono">{health.node}</p>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Cloud Spend — hidden until /v1/costs/summary is built */}
      {false && (
      <section>
        <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">Cloud Spend</p>
        <div className={`p-4 rounded-2xl border ${border} ${subtle}`}>
          <div className="flex items-center gap-2 mb-2">
            <DollarSign className="w-3.5 h-3.5 opacity-40" />
            <p className="text-[10px] font-mono uppercase opacity-40">Spend vs budget</p>
          </div>
          {costsLoading && <p className="text-sm opacity-40">Loading...</p>}
          {!costsLoading && costsErr && (
            <>
              <p className="text-xl font-bold opacity-40">—</p>
              <p className="text-xs text-rose-500 mt-2">Failed to load</p>
            </>
          )}
          {!costsLoading && !costsErr && costs != null && (
            <p className="text-xl font-bold">
              {costs?.total_usd.toFixed(2)} <span className="opacity-40">/ ${costs?.budget_usd.toFixed(2)}</span>
            </p>
          )}
        </div>
      </section>
      )}

      {/* Last Overnight */}
      <section>
        <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">Last Overnight</p>
        <div className={`p-4 rounded-2xl border ${border} ${subtle}`}>
          {graphsLoading && <p className="text-sm opacity-40">Loading...</p>}
          {!graphsLoading && graphsErr && (
            <>
              <p className="text-sm opacity-40">—</p>
              <p className="text-xs text-rose-500 mt-2">Failed to load</p>
            </>
          )}
          {!graphsLoading && !graphsErr && graphs && graphs.length === 0 && (
            <p className="text-sm opacity-40">No runs yet</p>
          )}
          {!graphsLoading && !graphsErr && graphs && graphs.length > 0 && (
            <div className="flex flex-wrap items-center gap-3">
              <span
                className={`text-xs font-mono font-bold px-2 py-1 rounded-md border ${border} ${
                  graphs[0].status === 'pass' || graphs[0].status === 'ok'
                    ? 'text-emerald-500 border-emerald-500/30'
                    : 'text-amber-500 border-amber-500/30'
                }`}
              >
                {graphs[0].status}
              </span>
              <span className="text-sm opacity-70">{formatRelativeTime(graphs[0].created_at)}</span>
            </div>
          )}
        </div>
      </section>

      {/* Service Map */}
      <section>
        <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">Service Map</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {nodeList.map(node => {
            const status =
              node === 'brain'
                ? healthLoading
                  ? 'pending'
                  : healthErr
                    ? 'error'
                    : brainOk
                      ? 'ok'
                      : 'error'
                : (nodes?.[node] ?? 'pending')
            const isOk = status === 'ok'
            return (
              <div key={node} className={`p-4 rounded-2xl border ${border} ${subtle}`}>
                <div className="flex items-center gap-2 mb-2">
                  <span className={`w-2 h-2 rounded-full ${isOk ? 'bg-emerald-500' : status === 'pending' ? 'bg-gray-500' : 'bg-rose-500'}`} />
                  <span className="text-sm font-bold capitalize">{node}</span>
                </div>
                <p className={`text-xs font-mono ${isOk ? 'text-emerald-500' : 'opacity-40'}`}>{status}</p>
              </div>
            )
          })}
        </div>
      </section>

      {/* Timeline placeholder */}
      <section>
        <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">Timeline</p>
        <div className={`p-6 rounded-2xl border ${border} ${subtle} text-center`}>
          <p className="text-sm opacity-40">Timeline feed — wired next session</p>
        </div>
      </section>
    </motion.div>
  )
}
