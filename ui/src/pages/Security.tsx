import { useEffect, useState, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Shield, Lock, CheckCircle, Activity } from 'lucide-react'
import { apiJson } from '../lib/apiFetch'
import { useAppStore } from '../store'

interface MeshNode {
  name: string
  display_name: string
  status: string
  cert_days_remaining?: number | null
  cert_status?: string | null
}

interface MeshStatus {
  mesh_status: string
  checked_at: string
  nodes: MeshNode[]
}

interface GraphRow {
  id: string
  title: string
  status: string
  created_at: string
  step_count: number
}

const KNOWN_AGENTS = ['brain', 'executor', 'watchdog', 'buddy', 'power_sampler'] as const

const JWT_ROUTES = [
  { route: '/health', protected: false },
  { route: '/v1/auth/pin', protected: false },
  { route: 'OPTIONS *', protected: false },
  { route: '/v1/ask', protected: true },
  { route: '/v1/chat/completions', protected: true },
  { route: '/v1/tasks/*', protected: true },
  { route: '/v1/mesh/*', protected: true },
  { route: '/v1/costs/*', protected: true },
  { route: '/v1/home/*', protected: true },
  { route: '/v1/vault/*', protected: true },
  { route: '/v1/buddy/*', protected: true },
]

function certDayColor(days: number | null | undefined): string {
  if (days == null) return 'text-zinc-500'
  if (days > 30) return 'text-emerald-400'
  if (days >= 15) return 'text-yellow-400'
  return 'text-rose-400'
}

function certDayBg(days: number | null | undefined): string {
  if (days == null) return 'bg-zinc-500/10 border-zinc-500/20'
  if (days > 30) return 'bg-emerald-500/10 border-emerald-500/20'
  if (days >= 15) return 'bg-yellow-500/10 border-yellow-500/20'
  return 'bg-rose-500/10 border-rose-500/20'
}

function statusBadge(status: string) {
  const map: Record<string, string> = {
    completed: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30',
    complete: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30',
    running: 'text-blue-400 bg-blue-500/15 border-blue-500/30',
    pending: 'text-zinc-400 bg-zinc-500/15 border-zinc-500/30',
    failed: 'text-rose-400 bg-rose-500/15 border-rose-500/30',
    halted: 'text-rose-400 bg-rose-500/15 border-rose-500/30',
    cancelled: 'text-zinc-500 bg-zinc-500/10 border-zinc-500/20',
    needs_approval: 'text-amber-400 bg-amber-500/15 border-amber-500/30',
  }
  const cls = map[status] ?? map.pending
  return (
    <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${cls}`}>
      {status}
    </span>
  )
}

export default function Security() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/5' : 'bg-[#141414]/5'

  const [mesh, setMesh] = useState<MeshStatus | null>(null)
  const [graphs, setGraphs] = useState<GraphRow[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const [meshData, graphData] = await Promise.all([
        apiJson<MeshStatus>('/v1/mesh/status').catch(() => null),
        apiJson<GraphRow[]>('/v1/tasks/graphs?limit=5').catch(() => []),
      ])
      setMesh(meshData)
      setGraphs(graphData)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const nodes = mesh?.nodes ?? []

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="space-y-8 max-w-5xl">
      <div>
        <h1 className="font-serif italic text-3xl">Security</h1>
        <p className="text-[10px] font-mono uppercase opacity-50 mt-1">TLS, JWT, TaskGraph, LaunchAgents</p>
      </div>

      {loading && <p className="text-sm opacity-40">Loading...</p>}

      {/* TLS Certificates */}
      <section>
        <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">TLS Certificates</p>
        <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
          {nodes.length === 0 && !loading && (
            <div className="p-4 text-sm opacity-40">No node data available</div>
          )}
          {nodes.length > 0 && (
            <div className="divide-y divide-white/5">
              {nodes.map((node) => {
                const days = node.cert_days_remaining
                return (
                  <div key={node.name} className="flex items-center justify-between px-5 py-3">
                    <div className="flex items-center gap-3">
                      <Shield className="w-4 h-4 opacity-40" />
                      <span className="text-sm font-bold">{node.display_name}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      {days != null ? (
                        <span className={`text-xs font-mono font-bold px-2.5 py-1 rounded border ${certDayBg(days)} ${certDayColor(days)}`}>
                          {days}d remaining
                        </span>
                      ) : (
                        <span className="text-xs font-mono opacity-30">no cert data</span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </section>

      {/* JWT Coverage */}
      <section>
        <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">JWT Coverage</p>
        <div className={`rounded-2xl border ${border} ${subtle} p-5 space-y-4`}>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <p className="text-[10px] font-mono uppercase opacity-40 mb-1">Algorithm</p>
              <p className="text-sm font-bold font-mono">RS256</p>
            </div>
            <div>
              <p className="text-[10px] font-mono uppercase opacity-40 mb-1">Token Lifetime</p>
              <p className="text-sm font-bold font-mono">30 days</p>
            </div>
            <div>
              <p className="text-[10px] font-mono uppercase opacity-40 mb-1">Protected Routes</p>
              <p className="text-sm font-bold font-mono">All except 3</p>
            </div>
          </div>
          <div className={`rounded-lg border ${border} overflow-hidden`}>
            <table className="w-full text-xs">
              <thead>
                <tr className={isDark ? 'bg-white/5' : 'bg-black/5'}>
                  <th className="text-left px-3 py-2 font-mono uppercase opacity-40">Route</th>
                  <th className="text-center px-3 py-2 font-mono uppercase opacity-40">JWT</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {JWT_ROUTES.map((r) => (
                  <tr key={r.route}>
                    <td className="px-3 py-1.5 font-mono">{r.route}</td>
                    <td className="px-3 py-1.5 text-center">
                      {r.protected ? (
                        <CheckCircle className="w-3.5 h-3.5 text-emerald-500 inline-block" />
                      ) : (
                        <Lock className="w-3.5 h-3.5 opacity-30 inline-block" />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* Active TaskGraph Summary */}
      <section>
        <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">Recent TaskGraphs</p>
        <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
          {graphs.length === 0 && !loading && (
            <div className="p-4 text-sm opacity-40">No graphs found</div>
          )}
          {graphs.length > 0 && (
            <div className="divide-y divide-white/5">
              {graphs.map((g) => (
                <div key={g.id} className="flex items-center justify-between px-5 py-3">
                  <div className="flex items-center gap-3">
                    <Activity className="w-4 h-4 opacity-40" />
                    <div>
                      <p className="text-sm font-bold">{g.title}</p>
                      <p className="text-[10px] font-mono opacity-40">
                        {g.step_count} step{g.step_count !== 1 ? 's' : ''}
                        {' · '}
                        {new Date(g.created_at).toLocaleDateString()}
                      </p>
                    </div>
                  </div>
                  {statusBadge(g.status)}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* LaunchAgent Status */}
      <section>
        <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">LaunchAgents</p>
        <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
          <div className="divide-y divide-white/5">
            {KNOWN_AGENTS.map((agent) => {
              const node = nodes.find((n) => n.name === agent)
              const statusLabel = node ? node.status : 'unknown'
              const isOk = statusLabel === 'healthy' || statusLabel === 'online' || statusLabel === 'running'
              return (
                <div key={agent} className="flex items-center justify-between px-5 py-3">
                  <span className="text-sm font-mono font-bold">{agent}</span>
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${isOk ? 'bg-emerald-500' : 'bg-zinc-500'}`} />
                    <span className={`text-xs font-mono ${isOk ? 'text-emerald-400' : 'opacity-40'}`}>
                      {statusLabel}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </section>
    </motion.div>
  )
}
