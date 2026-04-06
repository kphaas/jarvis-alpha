import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { ExternalLink, Plus, Trash2 } from 'lucide-react'
import { apiJson } from '../../lib/apiFetch'
import { useCostsSubscriptions } from '../../hooks/useCosts'
import { SectionSkeleton } from '../shared/SectionSkeleton'
import { SectionError } from '../shared/SectionError'
import type { SubscriptionRow } from '../../types/costs'
import { fmtMoney } from '../../types/costs'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function subscriptionMonthTotals(subs: SubscriptionRow[], year: number): { totals: number[]; tips: string[][] } {
  const totals = Array(12).fill(0)
  const tips: string[][] = Array.from({ length: 12 }, () => [])
  for (const s of subs) {
    if (s.billing === 'monthly') {
      for (let m = 0; m < 12; m++) {
        totals[m] += s.cost_usd
        tips[m].push(`${s.name} (monthly) ${fmtMoney(s.cost_usd)}`)
      }
    } else {
      const rd = new Date(s.next_renewal + 'T12:00:00')
      if (rd.getFullYear() === year) {
        const m = rd.getMonth()
        totals[m] += s.cost_usd
        tips[m].push(`${s.name} (annual) ${fmtMoney(s.cost_usd)}`)
      }
    }
  }
  return { totals, tips }
}

export function SubscriptionSection({
  isDark,
  border,
  subtle,
}: {
  isDark: boolean
  border: string
  subtle: string
}) {
  const qc = useQueryClient()
  const { data, isLoading, error } = useCostsSubscriptions()
  const rows = data ?? null
  const [err, setErr] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [hoverM, setHoverM] = useState<number | null>(null)
  const [form, setForm] = useState({
    name: '',
    url: '',
    cost_usd: '',
    billing: 'monthly' as 'monthly' | 'yearly',
    next_renewal: '',
  })

  const year = new Date().getFullYear()
  const { totals, tips } = useMemo(
    () => subscriptionMonthTotals(rows ?? [], year),
    [rows, year]
  )
  const maxBar = Math.max(1, ...totals)

  const addSubscription = async () => {
    setSubmitting(true)
    try {
      await apiJson('/v1/costs/subscriptions', {
        method: 'POST',
        body: JSON.stringify({
          name: form.name.trim(),
          url: form.url.trim() || null,
          cost_usd: parseFloat(form.cost_usd) || 0,
          billing: form.billing,
          next_renewal: form.next_renewal,
        }),
      })
      setModalOpen(false)
      setForm({ name: '', url: '', cost_usd: '', billing: 'monthly', next_renewal: '' })
      await qc.invalidateQueries({ queryKey: ['costs', 'subscriptions'] })
    } catch {
      setErr('Failed to add subscription.')
    } finally {
      setSubmitting(false)
    }
  }

  const remove = async (id: string) => {
    if (!window.confirm('Delete this subscription?')) return
    try {
      await apiJson(`/v1/costs/subscriptions/${id}`, { method: 'DELETE' })
      await qc.invalidateQueries({ queryKey: ['costs', 'subscriptions'] })
    } catch {
      setErr('Delete failed.')
    }
  }

  const monthlyDisplay = (r: SubscriptionRow) =>
    r.billing === 'yearly' ? (
      <span>
        {fmtMoney(r.cost_usd / 12)}
        <span className="text-[10px] opacity-50 ml-1">(yearly)</span>
      </span>
    ) : (
      fmtMoney(r.cost_usd)
    )

  const daysClass = (d: number) => {
    if (d < 7) return isDark ? 'text-rose-400' : 'text-rose-600'
    if (d < 30) return isDark ? 'text-amber-400' : 'text-amber-700'
    return ''
  }

  const w = 480
  const h = 200
  const pad = 36
  const bw = (w - pad * 2) / 12

  const card = `rounded-3xl border overflow-hidden ${border} ${subtle} ${isDark ? 'bg-white/[0.03]' : 'bg-white/60'}`

  return (
    <section>
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] opacity-40 mb-4">Subscriptions</p>
      {isLoading && <SectionSkeleton />}
      {!isLoading && (err || error) && !rows && (
        <div className={`p-8 ${card}`}>
          <SectionError message={err ?? 'Could not load subscriptions.'} />
        </div>
      )}
      {!isLoading && rows && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <div className={card}>
            <div className="flex justify-end p-4 border-b border-white/5">
              <button
                type="button"
                onClick={() => setModalOpen(true)}
                className={`inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-wide px-4 py-2 rounded-full border ${border}`}
              >
                <Plus className="w-4 h-4" />
                Add
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className={`text-[10px] font-semibold uppercase opacity-40 border-b ${border}`}>
                    <th className="p-4">Name</th>
                    <th className="p-4">Monthly</th>
                    <th className="p-4">Renewal</th>
                    <th className="p-4">Days</th>
                    <th className="p-4 w-10" />
                    <th className="p-4 w-10" />
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 && (
                    <tr>
                      <td colSpan={6} className="p-8 text-center text-sm opacity-50">
                        No subscriptions
                      </td>
                    </tr>
                  )}
                  {rows.map((r) => (
                    <tr key={r.id} className={`border-b border-white/5 ${border}`}>
                      <td className="p-4 font-medium">{r.name}</td>
                      <td className="p-4 font-mono text-xs tabular-nums">{monthlyDisplay(r)}</td>
                      <td className="p-4 font-mono text-xs">{r.next_renewal}</td>
                      <td className={`p-4 font-mono text-xs ${daysClass(r.days_until_renewal)}`}>{r.days_until_renewal}</td>
                      <td className="p-4">
                        {r.url ? (
                          <a
                            href={r.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex p-2 rounded-xl opacity-70 hover:opacity-100"
                          >
                            <ExternalLink className="w-4 h-4" />
                          </a>
                        ) : (
                          <span className="opacity-20">—</span>
                        )}
                      </td>
                      <td className="p-4">
                        <button
                          type="button"
                          onClick={() => remove(r.id)}
                          className="p-2 rounded-xl text-rose-500/80 hover:bg-rose-500/10"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {(err || error) && rows.length >= 0 && (
              <p className="text-xs text-rose-500 p-4 border-t border-white/5">{err ?? 'Could not load subscriptions.'}</p>
            )}
          </div>
          <div className={`${card} p-6`}>
            <p className="text-xs font-semibold uppercase tracking-wider opacity-50 mb-6">{year} cash view</p>
            <div className="relative">
              <svg width="100%" viewBox={`0 0 ${w} ${h}`} className="overflow-visible">
                {[0, 0.25, 0.5, 0.75, 1].map((t) => {
                  const y = pad + (1 - t) * (h - pad * 2)
                  return (
                    <g key={t}>
                      <line
                        x1={pad}
                        y1={y}
                        x2={w - pad}
                        y2={y}
                        stroke={isDark ? 'rgba(255,255,255,0.06)' : 'rgba(20,20,20,0.08)'}
                        strokeWidth={1}
                      />
                    </g>
                  )
                })}
                {MONTHS.map((label, m) => {
                  const barH = (totals[m] / maxBar) * (h - pad * 2)
                  const x = pad + m * bw + bw * 0.15
                  const bwInner = bw * 0.7
                  const y = h - pad - barH
                  const active = hoverM === m
                  return (
                    <g
                      key={label}
                      onMouseEnter={() => setHoverM(m)}
                      onMouseLeave={() => setHoverM(null)}
                      className="cursor-crosshair"
                    >
                      <rect
                        x={x}
                        y={y}
                        width={bwInner}
                        height={Math.max(barH, 0)}
                        rx={6}
                        fill={active ? '#f59e0b' : '#d97706'}
                        opacity={active ? 1 : 0.85}
                      />
                      <text
                        x={x + bwInner / 2}
                        y={h - pad + 14}
                        textAnchor="middle"
                        className={`text-[9px] font-medium ${isDark ? 'fill-white/35' : 'fill-[#141414]/45'}`}
                      >
                        {label}
                      </text>
                    </g>
                  )
                })}
              </svg>
              {hoverM != null && tips[hoverM].length > 0 && (
                <div
                  className={`absolute z-10 left-1/2 -translate-x-1/2 bottom-full mb-2 px-3 py-2 rounded-xl border text-xs max-w-xs shadow-xl ${
                    isDark ? 'bg-[#1a1a1a] border-white/10' : 'bg-white border-[#141414]/10'
                  }`}
                >
                  <p className="font-mono font-semibold mb-1">{fmtMoney(totals[hoverM])}</p>
                  <ul className="opacity-80 space-y-0.5 text-[11px]">
                    {tips[hoverM].map((t, i) => (
                      <li key={i}>{t}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <AnimatePresence>
        {modalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 bg-black/50 backdrop-blur-sm"
              onClick={() => !submitting && setModalOpen(false)}
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.96, y: 12 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96, y: 12 }}
              className={`relative w-full max-w-md rounded-3xl border p-8 shadow-2xl ${border} ${isDark ? 'bg-[#141414]' : 'bg-white'}`}
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="text-xl font-semibold tracking-tight mb-6">New subscription</h3>
              <div className="space-y-4">
                <input
                  placeholder="Name"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  className={`w-full px-4 py-3 rounded-2xl border bg-transparent text-sm ${border}`}
                />
                <input
                  placeholder="URL (optional)"
                  value={form.url}
                  onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
                  className={`w-full px-4 py-3 rounded-2xl border bg-transparent text-sm ${border}`}
                />
                <input
                  type="number"
                  placeholder="Cost USD"
                  value={form.cost_usd}
                  onChange={(e) => setForm((f) => ({ ...f, cost_usd: e.target.value }))}
                  className={`w-full px-4 py-3 rounded-2xl border bg-transparent text-sm font-mono ${border}`}
                />
                <select
                  value={form.billing}
                  onChange={(e) => setForm((f) => ({ ...f, billing: e.target.value as 'monthly' | 'yearly' }))}
                  className={`w-full px-4 py-3 rounded-2xl border bg-transparent text-sm ${border}`}
                >
                  <option value="monthly">Monthly</option>
                  <option value="yearly">Yearly</option>
                </select>
                <input
                  type="date"
                  value={form.next_renewal}
                  onChange={(e) => setForm((f) => ({ ...f, next_renewal: e.target.value }))}
                  className={`w-full px-4 py-3 rounded-2xl border bg-transparent text-sm ${border}`}
                />
              </div>
              <div className="flex gap-3 mt-8">
                <button
                  type="button"
                  disabled={submitting || !form.name.trim() || !form.next_renewal}
                  onClick={addSubscription}
                  className="flex-1 py-3 rounded-2xl bg-emerald-500 text-[#0a0a0a] font-semibold text-sm disabled:opacity-40"
                >
                  Save
                </button>
                <button
                  type="button"
                  onClick={() => setModalOpen(false)}
                  className="px-6 py-3 rounded-2xl border border-white/10 text-sm font-medium"
                >
                  Cancel
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </section>
  )
}
