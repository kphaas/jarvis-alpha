import { motion } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { Activity, Database, DollarSign, AlertTriangle } from 'lucide-react'
import { getHealth, getNodes, getCosts } from '../api'
import { useAppStore } from '../store'

export default function Home() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/5' : 'bg-[#141414]/5'

  const { data: health } = useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 60000 })
  const { data: nodes } = useQuery({ queryKey: ['nodes'], queryFn: getNodes, refetchInterval: 60000 })
  const { data: costs } = useQuery({ queryKey: ['costs'], queryFn: getCosts, refetchInterval: 900000 })

  const nodeList = ['brain', 'gateway', 'endpoint', 'sandbox']
  const allOk = health?.status === 'ok' && health?.db === 'ok'

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="space-y-8 max-w-5xl">

      <div>
        <h1 className="font-serif italic text-3xl">Home</h1>
        <p className="text-[10px] font-mono uppercase opacity-50 mt-1">System overview · {new Date().toLocaleDateString()}</p>
      </div>

      {/* Service Map */}
      <section>
        <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">Service Map</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {nodeList.map(node => {
            const status = node === 'brain' ? (allOk ? 'ok' : 'error') : (nodes?.[node] ?? 'pending')
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

      {/* Metrics */}
      <section>
        <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">Metrics</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'All-Time Spend', value: costs ? `$${costs.totals.all_time_usd.toFixed(4)}` : '—', icon: DollarSign },
            { label: 'All-Time Calls', value: costs ? costs.totals.all_time_calls.toString() : '—', icon: Activity },
            { label: 'Monthly Avg',    value: costs ? `$${costs.averages.monthly_avg_usd.toFixed(4)}` : '—', icon: Database },
            { label: 'Open Issues',    value: '—', icon: AlertTriangle },
          ].map(({ label, value, icon: Icon }) => (
            <div key={label} className={`p-4 rounded-2xl border ${border} ${subtle}`}>
              <div className="flex items-center gap-2 mb-2">
                <Icon className="w-3.5 h-3.5 opacity-40" />
                <p className="text-[10px] font-mono uppercase opacity-40">{label}</p>
              </div>
              <p className="text-xl font-bold">{value}</p>
            </div>
          ))}
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
