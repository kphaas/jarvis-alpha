import { useCallback, useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Check,
  Cpu,
  DollarSign,
  ExternalLink,
  Factory,
  Loader2,
  Pencil,
  Plus,
  Trash2,
  X,
  Zap,
} from 'lucide-react'
import { apiJson } from '../lib/apiFetch'
import { useAppStore } from '../store'

/* —— Types —— */

interface CostsSummary {
  subscriptions_monthly_usd: number
  credit: { balance_usd: number; spent_usd: number; pending_usd: number }
  power_monthly_usd: number
  forge_monthly_usd: number
  api_mtd_usd: number
  total_estimated_monthly_usd: number
  generated_at: string
}

interface CreditPayload {
  balance_usd: number
  spent_usd: number
  pending_usd: number
  updated_at: string | null
}

interface SubscriptionRow {
  id: string
  name: string
  url: string | null
  cost_usd: number
  billing: string
  next_renewal: string
  days_until_renewal: number
}

interface PowerNode {
  name: string
  watts: number
  kwh_monthly: number
  cost_monthly: number
}

interface PowerPayload {
  rate_per_kwh: number
  nodes: PowerNode[]
  total_watts: number
  total_cost_monthly: number
}

/* —— Shared UI —— */

function SectionSkeleton({ isDark, border }: { isDark: boolean; border: string }) {
  return (
    <div className={`animate-pulse rounded-2xl border p-6 ${border} ${isDark ? 'bg-white/[0.03]' : 'bg-[#141414]/5'}`}>
      <div className={`h-3 w-32 rounded ${isDark ? 'bg-white/10' : 'bg-[#141414]/15'}`} />
      <div className={`mt-4 h-24 rounded-xl ${isDark ? 'bg-white/5' : 'bg-[#141414]/8'}`} />
    </div>
  )
}

function SectionError({ message, isDark }: { message: string; isDark: boolean }) {
  return (
    <p className={`text-xs font-mono ${isDark ? 'text-amber-400/90' : 'text-amber-700'}`}>
      {message}
    </p>
  )
}

/* —— 1. Monthly overview —— */

function MonthlyOverviewSection({
  isDark,
  border,
  subtle,
}: {
  isDark: boolean
  border: string
  subtle: string
}) {
  const [data, setData] = useState<CostsSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setErr(null)
    apiJson<CostsSummary>('/v1/costs/summary')
      .then((d) => {
        if (alive) {
          setData(d)
          setErr(null)
        }
      })
      .catch(() => {
        if (alive) {
          setData(null)
          setErr('Could not load monthly overview.')
        }
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  const bars = useMemo(() => {
    if (!data) return []
    return [
      { key: 'sub', label: 'Subscriptions', value: data.subscriptions_monthly_usd, color: 'bg-blue-500' },
      { key: 'api', label: 'API', value: data.api_mtd_usd, color: 'bg-teal-500', suffix: ' MTD' },
      { key: 'pwr', label: 'Power', value: data.power_monthly_usd, color: 'bg-amber-500' },
      { key: 'frg', label: 'Forge', value: data.forge_monthly_usd, color: 'bg-purple-500' },
    ]
  }, [data])

  const maxVal = useMemo(() => Math.max(1, ...bars.map((b) => b.value)), [bars])

  return (
    <section>
      <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3 flex items-center gap-2">
        <DollarSign className="w-3.5 h-3.5" />
        Monthly overview
      </p>
      {loading && <SectionSkeleton isDark={isDark} border={border} />}
      {!loading && err && (
        <div className={`rounded-2xl border p-6 ${border} ${subtle}`}>
          <SectionError message={err} isDark={isDark} />
        </div>
      )}
      {!loading && !err && data && (
        <div className={`rounded-2xl border p-6 space-y-5 ${border} ${subtle}`}>
          <div className="space-y-4">
            {bars.map((b) => {
              const pct = Math.min(100, (b.value / maxVal) * 100)
              return (
                <div key={b.key} className="grid grid-cols-[8rem_1fr_auto] gap-3 items-center text-sm">
                  <span className="text-[11px] font-mono uppercase opacity-70 truncate">{b.label}</span>
                  <div className={`h-2.5 rounded-full overflow-hidden ${isDark ? 'bg-white/10' : 'bg-[#141414]/10'}`}>
                    <div className={`h-full rounded-full transition-all ${b.color}`} style={{ width: `${pct}%` }} />
                  </div>
                  <span className="text-right font-mono text-xs tabular-nums whitespace-nowrap">
                    ${b.value.toFixed(2)}
                    {b.suffix ? <span className="opacity-50">{b.suffix}</span> : <span className="opacity-50">/mo</span>}
                  </span>
                </div>
              )
            })}
          </div>
          <div className={`pt-4 border-t flex items-center justify-between ${border}`}>
            <span className="text-[10px] font-mono uppercase opacity-50 tracking-widest">
              ESTIMATED MONTHLY TOTAL
            </span>
            <span className="text-lg font-bold font-mono tabular-nums">
              ${data.total_estimated_monthly_usd.toFixed(2)}
            </span>
          </div>
        </div>
      )}
    </section>
  )
}

/* —— 2. Credit balance —— */

function CreditBalanceSection({
  isDark,
  border,
  subtle,
}: {
  isDark: boolean
  border: string
  subtle: string
}) {
  const [data, setData] = useState<CreditPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({ balance_usd: '', spent_usd: '', pending_usd: '' })

  const load = useCallback(() => {
    setLoading(true)
    setErr(null)
    apiJson<CreditPayload>('/v1/costs/credit')
      .then((d) => {
        setData(d)
        setForm({
          balance_usd: String(d.balance_usd),
          spent_usd: String(d.spent_usd),
          pending_usd: String(d.pending_usd),
        })
        setErr(null)
      })
      .catch(() => {
        setData(null)
        setErr('Could not load credit balance.')
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const save = async () => {
    setSaving(true)
    try {
      const body = {
        balance_usd: parseFloat(form.balance_usd) || 0,
        spent_usd: parseFloat(form.spent_usd) || 0,
        pending_usd: parseFloat(form.pending_usd) || 0,
      }
      const out = await apiJson<CreditPayload>('/v1/costs/credit', {
        method: 'POST',
        body: JSON.stringify(body),
      })
      setData(out)
      setEditing(false)
      setErr(null)
    } catch {
      setErr('Save failed.')
    } finally {
      setSaving(false)
    }
  }

  const lowBalance = data && data.balance_usd < 10

  return (
    <section>
      <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3 flex items-center gap-2">
        <Zap className="w-3.5 h-3.5" />
        Anthropic credit balance
      </p>
      {loading && <SectionSkeleton isDark={isDark} border={border} />}
      {!loading && err && !data && (
        <div className={`rounded-2xl border p-6 ${border} ${subtle}`}>
          <SectionError message={err} isDark={isDark} />
        </div>
      )}
      {!loading && data && (
        <div className={`rounded-2xl border p-6 ${border} ${subtle}`}>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <p className="text-4xl font-bold font-mono tabular-nums tracking-tight">
                  ${data.balance_usd.toFixed(2)}
                </p>
                {lowBalance && (
                  <span className="text-[9px] font-mono uppercase px-2 py-0.5 rounded-full border border-amber-500/50 text-amber-500 bg-amber-500/10">
                    Low balance
                  </span>
                )}
              </div>
              <div className="mt-3 flex gap-6 text-xs font-mono opacity-70">
                <span>Spent: ${Number(data.spent_usd).toFixed(4)}</span>
                <span>Pending: ${Number(data.pending_usd).toFixed(2)}</span>
              </div>
              {data.updated_at && (
                <p className="text-[9px] font-mono opacity-30 mt-2">Updated {data.updated_at}</p>
              )}
            </div>
            {!editing && (
              <button
                type="button"
                onClick={() => setEditing(true)}
                className={`p-2 rounded-lg border ${border} ${isDark ? 'hover:bg-white/10' : 'hover:bg-[#141414]/10'}`}
                aria-label="Edit credit"
              >
                <Pencil className="w-4 h-4" />
              </button>
            )}
          </div>
          {editing && (
            <div className="mt-6 space-y-3 pt-4 border-t border-dashed border-white/10">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <label className="text-[9px] font-mono uppercase opacity-50 block">
                  Balance USD
                  <input
                    type="number"
                    step="0.01"
                    value={form.balance_usd}
                    onChange={(e) => setForm((f) => ({ ...f, balance_usd: e.target.value }))}
                    className={`mt-1 w-full px-3 py-2 rounded-lg border text-sm font-mono bg-transparent ${border}`}
                  />
                </label>
                <label className="text-[9px] font-mono uppercase opacity-50 block">
                  Spent USD
                  <input
                    type="number"
                    step="0.000001"
                    value={form.spent_usd}
                    onChange={(e) => setForm((f) => ({ ...f, spent_usd: e.target.value }))}
                    className={`mt-1 w-full px-3 py-2 rounded-lg border text-sm font-mono bg-transparent ${border}`}
                  />
                </label>
                <label className="text-[9px] font-mono uppercase opacity-50 block">
                  Pending USD
                  <input
                    type="number"
                    step="0.01"
                    value={form.pending_usd}
                    onChange={(e) => setForm((f) => ({ ...f, pending_usd: e.target.value }))}
                    className={`mt-1 w-full px-3 py-2 rounded-lg border text-sm font-mono bg-transparent ${border}`}
                  />
                </label>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={saving}
                  onClick={save}
                  className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold font-mono uppercase ${isDark ? 'bg-emerald-500 text-[#0A0A0A]' : 'bg-[#141414] text-[#E4E3E0]'} disabled:opacity-50`}
                >
                  {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                  Save
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditing(false)
                    if (data) {
                      setForm({
                        balance_usd: String(data.balance_usd),
                        spent_usd: String(data.spent_usd),
                        pending_usd: String(data.pending_usd),
                      })
                    }
                  }}
                  className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-mono uppercase border ${border}`}
                >
                  <X className="w-3.5 h-3.5" />
                  Cancel
                </button>
              </div>
            </div>
          )}
          {err && data && <p className="text-xs text-rose-500 mt-3 font-mono">{err}</p>}
        </div>
      )}
    </section>
  )
}

/* —— 3. Subscriptions —— */

function SubscriptionsSection({
  isDark,
  border,
  subtle,
}: {
  isDark: boolean
  border: string
  subtle: string
}) {
  const [rows, setRows] = useState<SubscriptionRow[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [form, setForm] = useState({
    name: '',
    url: '',
    cost_usd: '',
    billing: 'monthly' as 'monthly' | 'yearly',
    next_renewal: '',
  })

  const load = useCallback(() => {
    setLoading(true)
    setErr(null)
    apiJson<SubscriptionRow[]>('/v1/costs/subscriptions')
      .then((d) => {
        setRows(d)
        setErr(null)
      })
      .catch(() => {
        setRows(null)
        setErr('Could not load subscriptions.')
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const addSubscription = async () => {
    setSubmitting(true)
    try {
      await apiJson<SubscriptionRow>('/v1/costs/subscriptions', {
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
      load()
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
      load()
    } catch {
      setErr('Delete failed.')
    }
  }

  const monthlyDisplay = (r: SubscriptionRow) => {
    if (r.billing === 'yearly') {
      return (
        <span>
          ${(r.cost_usd / 12).toFixed(2)}
          <span className="opacity-50 text-[10px] ml-1">(yearly)</span>
        </span>
      )
    }
    return <>${r.cost_usd.toFixed(2)}</>
  }

  const daysClass = (d: number) => {
    if (d < 7) return isDark ? 'text-rose-400' : 'text-rose-600'
    if (d < 30) return isDark ? 'text-amber-400' : 'text-amber-700'
    return ''
  }

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest">Subscriptions</p>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className={`inline-flex items-center gap-1.5 text-[10px] font-mono uppercase px-3 py-1.5 rounded-lg border ${border} ${isDark ? 'hover:bg-white/10' : 'hover:bg-[#141414]/10'}`}
        >
          <Plus className="w-3.5 h-3.5" />
          Add
        </button>
      </div>
      {loading && <SectionSkeleton isDark={isDark} border={border} />}
      {!loading && err && !rows && (
        <div className={`rounded-2xl border p-6 ${border} ${subtle}`}>
          <SectionError message={err} isDark={isDark} />
        </div>
      )}
      {!loading && rows && (
        <div className={`rounded-2xl border overflow-hidden ${border} ${subtle}`}>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className={`text-[9px] font-mono uppercase opacity-50 border-b ${border}`}>
                  <th className="p-3">Name</th>
                  <th className="p-3">Monthly cost</th>
                  <th className="p-3">Billing</th>
                  <th className="p-3">Renewal</th>
                  <th className="p-3">Days until</th>
                  <th className="p-3">Login</th>
                  <th className="p-3 w-10" />
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={7} className="p-6 text-center text-xs opacity-50 font-mono">
                      No subscriptions yet.
                    </td>
                  </tr>
                )}
                {rows.map((r) => (
                  <tr key={r.id} className={`border-b last:border-0 ${border}`}>
                    <td className="p-3 font-medium">{r.name}</td>
                    <td className="p-3 font-mono tabular-nums">{monthlyDisplay(r)}</td>
                    <td className="p-3 text-xs capitalize">{r.billing}</td>
                    <td className="p-3 font-mono text-xs">{r.next_renewal}</td>
                    <td className={`p-3 font-mono text-xs ${daysClass(r.days_until_renewal)}`}>
                      {r.days_until_renewal}
                    </td>
                    <td className="p-3">
                      {r.url ? (
                        <a
                          href={r.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={`inline-flex p-1.5 rounded-lg ${isDark ? 'hover:bg-white/10' : 'hover:bg-[#141414]/10'}`}
                          aria-label={`Open ${r.name}`}
                        >
                          <ExternalLink className="w-4 h-4 opacity-70" />
                        </a>
                      ) : (
                        <span className="opacity-25">—</span>
                      )}
                    </td>
                    <td className="p-3">
                      <button
                        type="button"
                        onClick={() => remove(r.id)}
                        className="p-1.5 rounded-lg text-rose-500/80 hover:bg-rose-500/10"
                        aria-label="Delete"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {err && rows && <p className="text-xs text-rose-500 p-3 font-mono border-t border-white/10">{err}</p>}
        </div>
      )}

      <AnimatePresence>
        {modalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 bg-black/60 backdrop-blur-sm"
              onClick={() => !submitting && setModalOpen(false)}
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.96, y: 8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96, y: 8 }}
              className={`relative w-full max-w-md rounded-2xl border p-6 shadow-2xl ${border} ${isDark ? 'bg-[#0F0F0F]' : 'bg-[#E4E3E0]'}`}
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="font-serif italic text-xl mb-4">Add subscription</h3>
              <div className="space-y-3">
                <label className="text-[9px] font-mono uppercase opacity-50 block">
                  Name
                  <input
                    value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                    className={`mt-1 w-full px-3 py-2 rounded-lg border text-sm bg-transparent ${border}`}
                  />
                </label>
                <label className="text-[9px] font-mono uppercase opacity-50 block">
                  URL (optional)
                  <input
                    value={form.url}
                    onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
                    className={`mt-1 w-full px-3 py-2 rounded-lg border text-sm bg-transparent ${border}`}
                  />
                </label>
                <label className="text-[9px] font-mono uppercase opacity-50 block">
                  Cost USD
                  <input
                    type="number"
                    step="0.01"
                    value={form.cost_usd}
                    onChange={(e) => setForm((f) => ({ ...f, cost_usd: e.target.value }))}
                    className={`mt-1 w-full px-3 py-2 rounded-lg border text-sm bg-transparent ${border}`}
                  />
                </label>
                <label className="text-[9px] font-mono uppercase opacity-50 block">
                  Billing
                  <select
                    value={form.billing}
                    onChange={(e) => setForm((f) => ({ ...f, billing: e.target.value as 'monthly' | 'yearly' }))}
                    className={`mt-1 w-full px-3 py-2 rounded-lg border text-sm bg-transparent ${border}`}
                  >
                    <option value="monthly">monthly</option>
                    <option value="yearly">yearly</option>
                  </select>
                </label>
                <label className="text-[9px] font-mono uppercase opacity-50 block">
                  Next renewal
                  <input
                    type="date"
                    value={form.next_renewal}
                    onChange={(e) => setForm((f) => ({ ...f, next_renewal: e.target.value }))}
                    className={`mt-1 w-full px-3 py-2 rounded-lg border text-sm bg-transparent ${border}`}
                  />
                </label>
              </div>
              <div className="flex gap-2 mt-6">
                <button
                  type="button"
                  disabled={submitting || !form.name.trim() || !form.next_renewal}
                  onClick={addSubscription}
                  className={`flex-1 py-2.5 rounded-lg text-xs font-bold font-mono uppercase ${isDark ? 'bg-emerald-500 text-[#0A0A0A]' : 'bg-[#141414] text-[#E4E3E0]'} disabled:opacity-40`}
                >
                  {submitting ? 'Saving…' : 'Save'}
                </button>
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => setModalOpen(false)}
                  className={`px-4 py-2.5 rounded-lg text-xs font-mono uppercase border ${border}`}
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

/* —— 4. Power —— */

function PowerSection({
  isDark,
  border,
  subtle,
}: {
  isDark: boolean
  border: string
  subtle: string
}) {
  const [data, setData] = useState<PowerPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [editingRate, setEditingRate] = useState(false)
  const [rateInput, setRateInput] = useState('')
  const [savingRate, setSavingRate] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setErr(null)
    apiJson<PowerPayload>('/v1/costs/power')
      .then((d) => {
        setData(d)
        setRateInput(String(d.rate_per_kwh))
        setErr(null)
      })
      .catch(() => {
        setData(null)
        setErr('Could not load power data.')
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const saveRate = async () => {
    setSavingRate(true)
    try {
      const v = parseFloat(rateInput)
      await apiJson<{ rate_per_kwh: number }>('/v1/costs/power/rate', {
        method: 'POST',
        body: JSON.stringify({ rate_per_kwh: v }),
      })
      setEditingRate(false)
      load()
    } catch {
      setErr('Failed to update rate.')
    } finally {
      setSavingRate(false)
    }
  }

  const nodeOrder = ['Brain', 'Gateway', 'Endpoint', 'Sandbox']

  return (
    <section>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest flex items-center gap-2">
          <Cpu className="w-3.5 h-3.5" />
          Node power consumption
        </p>
        {!loading && data && (
          <div className="flex items-center gap-2">
            {!editingRate && (
              <button
                type="button"
                onClick={() => {
                  setEditingRate(true)
                  setRateInput(String(data.rate_per_kwh))
                }}
                className={`inline-flex items-center gap-1.5 text-[10px] font-mono uppercase px-2 py-1 rounded-lg border ${border}`}
              >
                <Pencil className="w-3 h-3" />
                ${data.rate_per_kwh.toFixed(4)}/kWh
              </button>
            )}
            {editingRate && (
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  step="0.0001"
                  value={rateInput}
                  onChange={(e) => setRateInput(e.target.value)}
                  className={`w-28 px-2 py-1 rounded-lg border text-xs font-mono bg-transparent ${border}`}
                />
                <button
                  type="button"
                  disabled={savingRate}
                  onClick={saveRate}
                  className={`p-1.5 rounded-lg ${isDark ? 'bg-emerald-500 text-[#0A0A0A]' : 'bg-[#141414] text-[#E4E3E0]'}`}
                >
                  <Check className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditingRate(false)
                    setRateInput(String(data.rate_per_kwh))
                  }}
                  className="p-1.5 rounded-lg border border-white/10"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            )}
          </div>
        )}
      </div>
      {loading && <SectionSkeleton isDark={isDark} border={border} />}
      {!loading && err && !data && (
        <div className={`rounded-2xl border p-6 ${border} ${subtle}`}>
          <SectionError message={err} isDark={isDark} />
        </div>
      )}
      {!loading && data && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {nodeOrder.map((name) => {
              const n = data.nodes.find((x) => x.name === name)
              if (!n) return null
              const live = name === 'Brain'
              return (
                <div key={name} className={`rounded-2xl border p-4 ${border} ${subtle}`}>
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-bold font-mono uppercase">{name}</span>
                    {live && (
                      <span className="flex items-center gap-1.5 text-[9px] font-mono uppercase text-emerald-500">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                        live
                      </span>
                    )}
                  </div>
                  <dl className="space-y-1 text-xs font-mono">
                    <div className="flex justify-between opacity-80">
                      <dt>Watts</dt>
                      <dd className="tabular-nums">{n.watts.toFixed(1)}</dd>
                    </div>
                    <div className="flex justify-between opacity-80">
                      <dt>kWh/mo</dt>
                      <dd className="tabular-nums">{n.kwh_monthly.toFixed(2)}</dd>
                    </div>
                    <div className="flex justify-between font-bold pt-1 border-t border-white/10">
                      <dt>$/mo</dt>
                      <dd className="tabular-nums">${n.cost_monthly.toFixed(2)}</dd>
                    </div>
                  </dl>
                </div>
              )
            })}
          </div>
          <div className={`rounded-xl border px-4 py-3 flex justify-between items-center ${border} ${isDark ? 'bg-white/[0.04]' : 'bg-[#141414]/5'}`}>
            <span className="text-[10px] font-mono uppercase opacity-50">Total</span>
            <span className="font-mono text-sm font-bold tabular-nums">
              {data.total_watts.toFixed(1)} W · ${data.total_cost_monthly.toFixed(2)}/mo
            </span>
          </div>
          {err && data && <SectionError message={err} isDark={isDark} />}
        </div>
      )}
    </section>
  )
}

/* —— 5. Forge —— */

function ForgeSection({ isDark, border, subtle }: { isDark: boolean; border: string; subtle: string }) {
  const [forgeMonthly, setForgeMonthly] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setOffline(false)
    apiJson<CostsSummary>('/v1/costs/summary')
      .then((d) => {
        if (alive) {
          setForgeMonthly(d.forge_monthly_usd)
          setOffline(false)
        }
      })
      .catch(() => {
        if (alive) {
          setForgeMonthly(null)
          setOffline(true)
        }
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  const forgeUrl = 'http://100.124.172.14:5001'

  return (
    <section>
      <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3 flex items-center gap-2">
        <Factory className="w-3.5 h-3.5" />
        Forge pipeline costs
      </p>
      {loading && <SectionSkeleton isDark={isDark} border={border} />}
      {!loading && offline && (
        <div className={`rounded-2xl border p-6 flex flex-wrap items-center gap-3 ${border} ${subtle}`}>
          <span className="text-[9px] font-mono uppercase px-2 py-0.5 rounded-full border border-amber-500/50 text-amber-500 bg-amber-500/10">
            Forge offline
          </span>
          <span className="text-xs opacity-60 font-mono">Summary unavailable.</span>
        </div>
      )}
      {!loading && !offline && forgeMonthly !== null && (
        <div className={`rounded-2xl border p-6 ${border} ${subtle}`}>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-[10px] font-mono uppercase opacity-50">Monthly total (Forge)</p>
              <p className="text-3xl font-bold font-mono tabular-nums mt-1">${forgeMonthly.toFixed(2)}</p>
            </div>
            <a
              href={forgeUrl}
              target="_blank"
              rel="noopener noreferrer"
              className={`inline-flex items-center gap-2 text-xs font-mono uppercase px-4 py-2 rounded-lg border ${border} ${isDark ? 'hover:bg-white/10' : 'hover:bg-[#141414]/10'}`}
            >
              <ExternalLink className="w-3.5 h-3.5" />
              Forge dashboard
            </a>
          </div>
        </div>
      )}
    </section>
  )
}

/* —— Page —— */

export default function CostCenter() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/5' : 'bg-[#141414]/5'

  return (
    <div className="space-y-10 max-w-5xl">
      <div>
        <h1 className="font-serif italic text-3xl flex items-center gap-2">
          <DollarSign className="w-7 h-7 opacity-80" />
          Cost Center
        </h1>
        <p className="text-[10px] font-mono uppercase opacity-50 mt-1">Spend · Power · Subscriptions · Forge</p>
      </div>

      <MonthlyOverviewSection isDark={isDark} border={border} subtle={subtle} />
      <CreditBalanceSection isDark={isDark} border={border} subtle={subtle} />
      <SubscriptionsSection isDark={isDark} border={border} subtle={subtle} />
      <PowerSection isDark={isDark} border={border} subtle={subtle} />
      <ForgeSection isDark={isDark} border={border} subtle={subtle} />
    </div>
  )
}
