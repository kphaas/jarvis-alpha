import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Bot,
  Check,
  Cloud,
  ExternalLink,
  Pencil,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { apiJson } from '../lib/apiFetch'
import { useAppStore } from '../store'

/* —— Types —— */

interface CostsSummary {
  subscriptions_monthly_usd?: number
  credit: { balance_usd: number; spent_usd: number; pending_usd: number }
  perplexity?: { balance_usd: number; spent_usd: number }
  power_monthly_usd: number
  hardware_monthly_usd?: number
  true_monthly_tco: number
  forge_monthly_usd: number
  api: {
    anthropic: { total_usd: number; jarvis_core_usd?: number; jarvis_forge_usd?: number }
    gemini: { total_usd: number; source?: string }
    perplexity_mtd_usd?: number
  }
  budget?: Array<{ provider: string; monthly_limit_usd: number; mtd_usd: number; pct_used: number }>
  outcomes?: Array<{ session_type: string | null; run_count: number; avg_usd: number }>
  savings_vs_cloud_usd?: number
  local_routing_pct?: number
  generated_at: string
}

interface BudgetRow {
  provider: string
  monthly_limit_usd: number
  mtd_usd: number
  remaining_usd: number
  pct_used: number
}

interface OutcomeRow {
  session_type: string | null
  run_count: number
  total_usd: number
  avg_usd: number
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

interface HardwareNode {
  node_name: string
  cost_usd: number
  years: number
  monthly_usd: number
}

interface HardwarePayload {
  nodes: HardwareNode[]
  total_monthly_usd: number
}

interface PerplexityPayload {
  balance_usd: number
  spent_usd: number
  updated_at: string | null
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/* —— Shared —— */

function SectionSkeleton({ isDark, border }: { isDark: boolean; border: string }) {
  return (
    <div className={`animate-pulse rounded-3xl border p-8 ${border} ${isDark ? 'bg-white/[0.03]' : 'bg-white/60'}`}>
      <div className={`h-3 w-40 rounded-full ${isDark ? 'bg-white/10' : 'bg-[#141414]/10'}`} />
      <div className={`mt-6 h-32 rounded-2xl ${isDark ? 'bg-white/[0.04]' : 'bg-[#141414]/5'}`} />
    </div>
  )
}

function SectionError({ message, isDark }: { message: string; isDark: boolean }) {
  return (
    <p className={`text-xs font-medium ${isDark ? 'text-amber-400/90' : 'text-amber-700'}`}>{message}</p>
  )
}

function fmtMoney(n: number) {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

type LoadDeltaFn = (delta: number) => void

/* —— SVG Donut —— */

function donutSlicePath(
  cx: number,
  cy: number,
  rOut: number,
  rIn: number,
  a0: number,
  a1: number
): string {
  const x0o = cx + rOut * Math.cos(a0)
  const y0o = cy + rOut * Math.sin(a0)
  const x1o = cx + rOut * Math.cos(a1)
  const y1o = cy + rOut * Math.sin(a1)
  const x0i = cx + rIn * Math.cos(a1)
  const y0i = cy + rIn * Math.sin(a1)
  const x1i = cx + rIn * Math.cos(a0)
  const y1i = cy + rIn * Math.sin(a0)
  const large = a1 - a0 > Math.PI ? 1 : 0
  return [
    `M ${x0o} ${y0o}`,
    `A ${rOut} ${rOut} 0 ${large} 1 ${x1o} ${y1o}`,
    `L ${x0i} ${y0i}`,
    `A ${rIn} ${rIn} 0 ${large} 0 ${x1i} ${y1i}`,
    'Z',
  ].join(' ')
}

function DonutChart({
  slices,
  centerLabel,
  centerValue,
  isDark,
  size = 200,
}: {
  slices: { key: string; label: string; value: number; color: string }[]
  centerLabel: string
  centerValue: string
  isDark: boolean
  size?: number
}) {
  const total = slices.reduce((s, x) => s + Math.max(0, x.value), 0)
  const cx = size / 2
  const cy = size / 2
  const rOut = size * 0.38
  const rIn = size * 0.22
  let angle = -Math.PI / 2
  const paths: { d: string; color: string; key: string }[] = []
  if (total > 0) {
    for (const sl of slices) {
      const v = Math.max(0, sl.value)
      if (v <= 0) continue
      const span = (v / total) * Math.PI * 2
      const a0 = angle
      const a1 = angle + span
      paths.push({ d: donutSlicePath(cx, cy, rOut, rIn, a0, a1), color: sl.color, key: sl.key })
      angle = a1
    }
  }
  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} className="overflow-visible">
        {total <= 0 ? (
          <circle
            cx={cx}
            cy={cy}
            r={(rOut + rIn) / 2}
            fill="none"
            stroke={isDark ? 'rgba(255,255,255,0.08)' : 'rgba(20,20,20,0.08)'}
            strokeWidth={rOut - rIn}
          />
        ) : (
          paths.map((p) => <path key={p.key} d={p.d} fill={p.color} className="transition-opacity hover:opacity-90" />)
        )}
        <text
          x={cx}
          y={cy - 6}
          textAnchor="middle"
          className={`text-[10px] font-medium uppercase tracking-wider ${isDark ? 'fill-white/40' : 'fill-[#141414]/40'}`}
        >
          {centerLabel}
        </text>
        <text
          x={cx}
          y={cy + 14}
          textAnchor="middle"
          className={`text-sm font-semibold tabular-nums ${isDark ? 'fill-white' : 'fill-[#141414]'}`}
        >
          {centerValue}
        </text>
      </svg>
    </div>
  )
}

/* —— 1. Hero —— */

function HeroSection({
  isDark,
  border,
  subtle,
  refreshKey,
  onLoadDelta,
}: {
  isDark: boolean
  border: string
  subtle: string
  refreshKey: number
  onLoadDelta?: LoadDeltaFn
}) {
  const [data, setData] = useState<CostsSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let a = true
    onLoadDelta?.(1)
    setLoading(true)
    setErr(null)
    apiJson<CostsSummary>('/v1/costs/summary')
      .then((d) => {
        if (a) {
          setData(d)
          setErr(null)
        }
      })
      .catch(() => {
        if (a) {
          setData(null)
          setErr('Could not load summary.')
        }
      })
      .finally(() => {
        if (a) setLoading(false)
        onLoadDelta?.(-1)
      })
    return () => {
      a = false
    }
  }, [refreshKey, onLoadDelta])

  const monthMeta = useMemo(() => {
    const now = new Date()
    const y = now.getFullYear()
    const m = now.getMonth()
    const dim = new Date(y, m + 1, 0).getDate()
    const day = now.getDate()
    return { dim, day, pct: dim > 0 ? (day / dim) * 100 : 0 }
  }, [])

  const cardBase = `rounded-3xl border p-4 backdrop-blur-xl ${border} ${
    isDark ? 'bg-white/[0.04] shadow-[0_1px_0_rgba(255,255,255,0.06)_inset]' : 'bg-white/70 shadow-sm'
  }`

  const geminiCreditBal = data ? Math.max(0, 300 - (data.api?.gemini?.total_usd ?? 0)) : 0

  return (
    <section className="space-y-6">
      {loading && <SectionSkeleton isDark={isDark} border={border} />}
      {!loading && err && (
        <div className={`${cardBase} ${subtle}`}>
          <SectionError message={err} isDark={isDark} />
        </div>
      )}
      {!loading && !err && data && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 lg:gap-6">
            <div className={cardBase}>
              <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-emerald-500/90 mb-3">
                Estimated monthly
              </p>
              <p className="text-3xl font-semibold tracking-tight tabular-nums text-balance">
                {fmtMoney(data.true_monthly_tco ?? 0)}
              </p>
              <p className="mt-3 text-sm opacity-50">
                vs full cloud save{' '}
                <span className="font-medium text-emerald-500/90 tabular-nums">
                  {fmtMoney(data.savings_vs_cloud_usd ?? 0)}/mo
                </span>
              </p>
            </div>
            <div className={cardBase}>
              <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-sky-500/90 mb-3">
                CLOUD CREDITS
              </p>
              <div className="space-y-0 divide-y divide-white/10 dark:divide-white/10">
                <div className="flex justify-between items-center py-2.5 text-sm">
                  <span className="opacity-80">Anthropic</span>
                  <span className="font-mono tabular-nums">{fmtMoney(data.credit.balance_usd)}</span>
                </div>
                <div className="flex justify-between items-center py-2.5 text-sm">
                  <span className="opacity-80">Gemini</span>
                  <span className="font-mono tabular-nums">{fmtMoney(geminiCreditBal)}</span>
                </div>
                <div className="flex justify-between items-center py-2.5 text-sm">
                  <span className="opacity-80">Perplexity</span>
                  <span className="font-mono tabular-nums">{fmtMoney(data.perplexity?.balance_usd ?? 0)}</span>
                </div>
              </div>
            </div>
          </div>
          <div className={`rounded-2xl border px-5 py-4 ${border} ${isDark ? 'bg-white/[0.02]' : 'bg-white/50'}`}>
            <div className="flex justify-between text-[11px] font-medium uppercase tracking-wider opacity-40 mb-2">
              <span>Month progress</span>
              <span>
                Day {monthMeta.day} of {monthMeta.dim}
              </span>
            </div>
            <div className={`h-1 rounded-full overflow-hidden ${isDark ? 'bg-white/10' : 'bg-[#141414]/10'}`}>
              <div
                className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-400 transition-all duration-500"
                style={{ width: `${Math.min(100, monthMeta.pct)}%` }}
              />
            </div>
          </div>
        </>
      )}
    </section>
  )
}

/* —— 2. Pies —— */

function PieSection({
  isDark,
  border,
  subtle,
  refreshKey,
  onLoadDelta,
}: {
  isDark: boolean
  border: string
  subtle: string
  refreshKey: number
  onLoadDelta?: LoadDeltaFn
}) {
  const [data, setData] = useState<CostsSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let a = true
    onLoadDelta?.(1)
    setLoading(true)
    setErr(null)
    apiJson<CostsSummary>('/v1/costs/summary')
      .then((d) => {
        if (a) {
          setData(d)
          setErr(null)
        }
      })
      .catch(() => {
        if (a) {
          setData(null)
          setErr('Could not load charts.')
        }
      })
      .finally(() => {
        if (a) setLoading(false)
        onLoadDelta?.(-1)
      })
    return () => {
      a = false
    }
  }, [refreshKey, onLoadDelta])

  const alphaSlices = useMemo(() => {
    if (!data) return []
    const ant = data.api?.anthropic?.total_usd ?? 0
    const gem = data.api?.gemini?.total_usd ?? 0
    const pwr = data.power_monthly_usd ?? 0
    const hw = data.hardware_monthly_usd ?? 0
    return [
      { key: 'ant', label: 'Anthropic API', value: ant, color: '#d97757' },
      { key: 'gem', label: 'Gemini API', value: gem, color: '#4285f4' },
      { key: 'pwr', label: 'Power', value: pwr, color: '#f59e0b' },
      { key: 'hw', label: 'Hardware', value: hw, color: '#8b5cf6' },
    ]
  }, [data])

  const alphaTotal = alphaSlices.reduce((s, x) => s + x.value, 0)

  const wrap = `rounded-3xl border p-8 ${border} ${subtle} ${
    isDark ? 'bg-white/[0.03]' : 'bg-white/60'
  }`

  return (
    <section>
      {loading && <SectionSkeleton isDark={isDark} border={border} />}
      {!loading && err && (
        <div className={wrap}>
          <SectionError message={err} isDark={isDark} />
        </div>
      )}
      {!loading && !err && data && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className={wrap}>
            <p className="text-center text-xs font-semibold uppercase tracking-[0.25em] opacity-40 mb-6">Alpha</p>
            <DonutChart
              slices={alphaSlices}
              centerLabel="Total"
              centerValue={fmtMoney(alphaTotal)}
              isDark={isDark}
            />
            <ul className="mt-6 space-y-2 max-w-xs mx-auto">
              {alphaSlices.map((s) => (
                <li key={s.key} className="flex items-center justify-between text-sm gap-3">
                  <span className="flex items-center gap-2 min-w-0">
                    <span className="w-2 h-2 rounded-full shrink-0" style={{ background: s.color }} />
                    <span className="truncate opacity-80">{s.label}</span>
                  </span>
                  <span className="font-mono text-xs tabular-nums shrink-0">{fmtMoney(s.value)}</span>
                </li>
              ))}
            </ul>
          </div>
          <ForgePieHalf
            isDark={isDark}
            border={border}
            subtle={subtle}
            summary={data}
            refreshKey={refreshKey}
            onLoadDelta={onLoadDelta}
          />
        </div>
      )}
    </section>
  )
}

function ForgePieHalf({
  isDark,
  border,
  subtle,
  summary,
  refreshKey,
  onLoadDelta,
}: {
  isDark: boolean
  border: string
  subtle: string
  summary: CostsSummary
  refreshKey: number
  onLoadDelta?: LoadDeltaFn
}) {
  const [power, setPower] = useState<PowerPayload | null>(null)
  const [hw, setHw] = useState<HardwarePayload | null>(null)

  useEffect(() => {
    let a = true
    onLoadDelta?.(1)
    Promise.all([apiJson<PowerPayload>('/v1/costs/power'), apiJson<HardwarePayload>('/v1/costs/hardware')])
      .then(([p, h]) => {
        if (!a) return
        setPower(p)
        setHw(h)
      })
      .catch(() => {
        if (a) {
          setPower(null)
          setHw(null)
        }
      })
      .finally(() => {
        onLoadDelta?.(-1)
      })
    return () => {
      a = false
    }
  }, [refreshKey, onLoadDelta])

  const sbPower = power?.nodes.find((n) => n.name === 'Sandbox')?.cost_monthly ?? 0
  const sbHw = hw?.nodes.find((n) => n.node_name === 'Sandbox')?.monthly_usd ?? 0

  const slices = useMemo(() => {
    const forgeApi = summary.forge_monthly_usd ?? 0
    return [
      { key: 'fa', label: 'Forge API', value: forgeApi, color: '#a855f7' },
      { key: 'sp', label: 'Sandbox power', value: sbPower, color: '#fbbf24' },
      { key: 'sh', label: 'Sandbox hardware', value: sbHw, color: '#64748b' },
    ]
  }, [summary.forge_monthly_usd, sbPower, sbHw])

  const total = slices.reduce((s, x) => s + x.value, 0)
  const wrap = `rounded-3xl border p-8 ${border} ${subtle} ${isDark ? 'bg-white/[0.03]' : 'bg-white/60'}`

  return (
    <div className={wrap}>
      <p className="text-center text-xs font-semibold uppercase tracking-[0.25em] opacity-40 mb-6">Forge</p>
      <DonutChart slices={slices} centerLabel="Total" centerValue={fmtMoney(total)} isDark={isDark} />
      <ul className="mt-6 space-y-2 max-w-xs mx-auto">
        {slices.map((s) => (
          <li key={s.key} className="flex items-center justify-between text-sm gap-3">
            <span className="flex items-center gap-2 min-w-0">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ background: s.color }} />
              <span className="truncate opacity-80">{s.label}</span>
            </span>
            <span className="font-mono text-xs tabular-nums shrink-0">{fmtMoney(s.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/* —— 3. API spend —— */

function ApiSpendSection({
  isDark,
  border,
  subtle,
  refreshKey,
  onLoadDelta,
}: {
  isDark: boolean
  border: string
  subtle: string
  refreshKey: number
  onLoadDelta?: LoadDeltaFn
}) {
  const [summary, setSummary] = useState<CostsSummary | null>(null)
  const [budget, setBudget] = useState<BudgetRow[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [editProv, setEditProv] = useState<string | null>(null)
  const [limitInput, setLimitInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [pxEdit, setPxEdit] = useState(false)
  const [pxForm, setPxForm] = useState({ balance_usd: '', spent_usd: '' })
  const [pxSaving, setPxSaving] = useState(false)

  const load = useCallback(() => {
    onLoadDelta?.(1)
    setLoading(true)
    setErr(null)
    Promise.all([apiJson<CostsSummary>('/v1/costs/summary'), apiJson<BudgetRow[]>('/v1/costs/budget')])
      .then(([s, b]) => {
        setSummary(s)
        setBudget(b)
        if (s.perplexity) {
          setPxForm({
            balance_usd: String(s.perplexity.balance_usd),
            spent_usd: String(s.perplexity.spent_usd),
          })
        }
        setErr(null)
      })
      .catch(() => {
        setSummary(null)
        setBudget(null)
        setErr('Could not load budget or summary.')
      })
      .finally(() => {
        setLoading(false)
        onLoadDelta?.(-1)
      })
  }, [onLoadDelta])

  useEffect(() => {
    load()
  }, [refreshKey, load])

  const loadPx = useCallback(() => {
    onLoadDelta?.(1)
    apiJson<PerplexityPayload>('/v1/costs/perplexity')
      .then((p) => {
        setPxForm({ balance_usd: String(p.balance_usd), spent_usd: String(p.spent_usd) })
      })
      .catch(() => {})
      .finally(() => {
        onLoadDelta?.(-1)
      })
  }, [onLoadDelta])

  useEffect(() => {
    loadPx()
  }, [refreshKey, loadPx])

  const saveLimit = async (provider: string) => {
    setSaving(true)
    try {
      const v = parseFloat(limitInput)
      await apiJson(`/v1/costs/budget/${encodeURIComponent(provider)}`, {
        method: 'POST',
        body: JSON.stringify({ monthly_limit_usd: v }),
      })
      setEditProv(null)
      load()
    } catch {
      setErr('Failed to update limit.')
    } finally {
      setSaving(false)
    }
  }

  const savePx = async () => {
    setPxSaving(true)
    try {
      await apiJson<PerplexityPayload>('/v1/costs/perplexity', {
        method: 'POST',
        body: JSON.stringify({
          balance_usd: parseFloat(pxForm.balance_usd) || 0,
          spent_usd: parseFloat(pxForm.spent_usd) || 0,
        }),
      })
      setPxEdit(false)
      loadPx()
      load()
    } catch {
      setErr('Perplexity save failed.')
    } finally {
      setPxSaving(false)
    }
  }

  const wrap = `rounded-3xl border overflow-hidden ${border} ${subtle} ${isDark ? 'bg-white/[0.03]' : 'bg-white/60'}`

  return (
    <section>
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] opacity-40 mb-4">Cloud API spend</p>
      {loading && <SectionSkeleton isDark={isDark} border={border} />}
      {!loading && err && !summary && (
        <div className={`p-8 ${wrap}`}>
          <SectionError message={err} isDark={isDark} />
        </div>
      )}
      {!loading && summary && budget && (
        <div className={wrap}>
          <div className="divide-y divide-white/5">
            {/* Anthropic */}
            <div className="p-6 space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <Sparkles className="w-5 h-5 text-orange-400 shrink-0" />
                <span className="font-semibold">Anthropic</span>
                <span className="font-mono text-sm tabular-nums ml-auto">
                  MTD {fmtMoney(summary.api?.anthropic?.total_usd ?? 0)}
                </span>
              </div>
              <div className="pl-8 text-xs opacity-60 space-y-1">
                <p>
                  jarvis_core ·{' '}
                  <span className="font-mono tabular-nums">
                    {fmtMoney(summary.api?.anthropic?.jarvis_core_usd ?? 0)}
                  </span>
                </p>
                <p>
                  jarvis_forge ·{' '}
                  <span className="font-mono tabular-nums">
                    {fmtMoney(summary.api?.anthropic?.jarvis_forge_usd ?? 0)}
                  </span>
                </p>
              </div>
              {(() => {
                const b = budget.find((x) => x.provider === 'anthropic')
                if (!b) return null
                const pct = Math.min(100, b.pct_used)
                return (
                  <div className="pl-8 pt-2 space-y-2">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="opacity-50">Limit</span>
                      {editProv === 'anthropic' ? (
                        <>
                          <input
                            type="number"
                            value={limitInput}
                            onChange={(e) => setLimitInput(e.target.value)}
                            className={`w-24 px-2 py-1 rounded-lg border text-xs font-mono bg-transparent ${border}`}
                          />
                          <button
                            type="button"
                            disabled={saving}
                            onClick={() => saveLimit('anthropic')}
                            className="p-1 rounded-lg bg-emerald-500 text-[#0a0a0a]"
                          >
                            <Check className="w-4 h-4" />
                          </button>
                          <button type="button" onClick={() => setEditProv(null)} className="p-1 rounded-lg border border-white/10">
                            <X className="w-4 h-4" />
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            setEditProv('anthropic')
                            setLimitInput(String(b.monthly_limit_usd))
                          }}
                          className="inline-flex items-center gap-1 font-mono tabular-nums"
                        >
                          {fmtMoney(b.monthly_limit_usd)}
                          <Pencil className="w-3 h-3 opacity-40" />
                        </button>
                      )}
                      <span className="opacity-50 ml-2">Remaining {fmtMoney(b.remaining_usd)}</span>
                    </div>
                    <div className={`h-1.5 rounded-full overflow-hidden ${isDark ? 'bg-white/10' : 'bg-[#141414]/10'}`}>
                      <div className="h-full rounded-full bg-orange-400/90" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                )
              })()}
            </div>
            {/* Gemini */}
            <div className="p-6 space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <Bot className="w-5 h-5 text-blue-500 shrink-0" />
                <span className="font-semibold">Gemini</span>
                <span
                  className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border ${
                    summary.api?.gemini?.source === 'gcp_api'
                      ? 'border-blue-500/40 text-blue-400'
                      : 'border-white/15 opacity-60'
                  }`}
                >
                  {summary.api?.gemini?.source === 'gcp_api' ? 'GCP API' : 'GCP FREE TIER'}
                </span>
                <span className="font-mono text-sm tabular-nums ml-auto">
                  MTD {fmtMoney(summary.api?.gemini?.total_usd ?? 0)}
                </span>
              </div>
              {(() => {
                const b = budget.find((x) => x.provider === 'gemini')
                if (!b) return null
                const pct = Math.min(100, b.pct_used)
                return (
                  <div className="pl-8 space-y-2">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="opacity-50">Limit</span>
                      {editProv === 'gemini' ? (
                        <>
                          <input
                            type="number"
                            value={limitInput}
                            onChange={(e) => setLimitInput(e.target.value)}
                            className={`w-24 px-2 py-1 rounded-lg border text-xs font-mono bg-transparent ${border}`}
                          />
                          <button
                            type="button"
                            disabled={saving}
                            onClick={() => saveLimit('gemini')}
                            className="p-1 rounded-lg bg-emerald-500 text-[#0a0a0a]"
                          >
                            <Check className="w-4 h-4" />
                          </button>
                          <button type="button" onClick={() => setEditProv(null)} className="p-1 rounded-lg border border-white/10">
                            <X className="w-4 h-4" />
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            setEditProv('gemini')
                            setLimitInput(String(b.monthly_limit_usd))
                          }}
                          className="inline-flex items-center gap-1 font-mono tabular-nums"
                        >
                          {fmtMoney(b.monthly_limit_usd)}
                          <Pencil className="w-3 h-3 opacity-40" />
                        </button>
                      )}
                      <span className="opacity-50 ml-2">Remaining {fmtMoney(b.remaining_usd)}</span>
                    </div>
                    <div className={`h-1.5 rounded-full overflow-hidden ${isDark ? 'bg-white/10' : 'bg-[#141414]/10'}`}>
                      <div className="h-full rounded-full bg-blue-500/80" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                )
              })()}
            </div>
            {/* Perplexity */}
            <div className="p-6 space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <Cloud className="w-5 h-5 text-cyan-400 shrink-0" />
                <span className="font-semibold">Perplexity</span>
                <span className="font-mono text-sm tabular-nums ml-auto">
                  MTD {fmtMoney(summary.api?.perplexity_mtd_usd ?? 0)}
                </span>
              </div>
              <div className="pl-8 flex flex-wrap items-center gap-4 text-sm">
                <span className="opacity-60">
                  Credit {fmtMoney(parseFloat(pxForm.balance_usd) || 0)} · Spent {fmtMoney(parseFloat(pxForm.spent_usd) || 0)}
                </span>
                {!pxEdit ? (
                  <button type="button" onClick={() => setPxEdit(true)} className="p-1.5 rounded-lg border border-white/10">
                    <Pencil className="w-4 h-4" />
                  </button>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      type="number"
                      placeholder="balance"
                      value={pxForm.balance_usd}
                      onChange={(e) => setPxForm((f) => ({ ...f, balance_usd: e.target.value }))}
                      className={`w-24 px-2 py-1 rounded-lg border text-xs font-mono bg-transparent ${border}`}
                    />
                    <input
                      type="number"
                      placeholder="spent"
                      value={pxForm.spent_usd}
                      onChange={(e) => setPxForm((f) => ({ ...f, spent_usd: e.target.value }))}
                      className={`w-24 px-2 py-1 rounded-lg border text-xs font-mono bg-transparent ${border}`}
                    />
                    <button
                      type="button"
                      disabled={pxSaving}
                      onClick={savePx}
                      className="p-1.5 rounded-lg bg-emerald-500 text-[#0a0a0a]"
                    >
                      <Check className="w-4 h-4" />
                    </button>
                    <button type="button" onClick={() => setPxEdit(false)} className="p-1.5 rounded-lg border border-white/10">
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                )}
              </div>
              {(() => {
                const b = budget.find((x) => x.provider === 'perplexity')
                if (!b) return null
                const pct = Math.min(100, b.pct_used)
                return (
                  <div className="pl-8 space-y-2">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="opacity-50">Limit</span>
                      {editProv === 'perplexity' ? (
                        <>
                          <input
                            type="number"
                            value={limitInput}
                            onChange={(e) => setLimitInput(e.target.value)}
                            className={`w-24 px-2 py-1 rounded-lg border text-xs font-mono bg-transparent ${border}`}
                          />
                          <button
                            type="button"
                            disabled={saving}
                            onClick={() => saveLimit('perplexity')}
                            className="p-1 rounded-lg bg-emerald-500 text-[#0a0a0a]"
                          >
                            <Check className="w-4 h-4" />
                          </button>
                          <button type="button" onClick={() => setEditProv(null)} className="p-1 rounded-lg border border-white/10">
                            <X className="w-4 h-4" />
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            setEditProv('perplexity')
                            setLimitInput(String(b.monthly_limit_usd))
                          }}
                          className="inline-flex items-center gap-1 font-mono tabular-nums"
                        >
                          {fmtMoney(b.monthly_limit_usd)}
                          <Pencil className="w-3 h-3 opacity-40" />
                        </button>
                      )}
                      <span className="opacity-50 ml-2">Remaining {fmtMoney(b.remaining_usd)}</span>
                    </div>
                    <div className={`h-1.5 rounded-full overflow-hidden ${isDark ? 'bg-white/10' : 'bg-[#141414]/10'}`}>
                      <div className="h-full rounded-full bg-cyan-500/80" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                )
              })()}
            </div>
          </div>
          {err && summary && <p className="text-xs text-rose-500 p-4">{err}</p>}
        </div>
      )}
    </section>
  )
}

/* —— 4. Outcomes —— */

function OutcomeSection({
  isDark,
  border,
  subtle,
  refreshKey,
  onLoadDelta,
}: {
  isDark: boolean
  border: string
  subtle: string
  refreshKey: number
  onLoadDelta?: LoadDeltaFn
}) {
  const [rows, setRows] = useState<OutcomeRow[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let a = true
    onLoadDelta?.(1)
    setLoading(true)
    setErr(null)
    apiJson<OutcomeRow[]>('/v1/costs/outcomes')
      .then((d) => {
        if (a) {
          setRows(d)
          setErr(null)
        }
      })
      .catch(() => {
        if (a) {
          setRows(null)
          setErr('Could not load outcomes.')
        }
      })
      .finally(() => {
        if (a) setLoading(false)
        onLoadDelta?.(-1)
      })
    return () => {
      a = false
    }
  }, [refreshKey, onLoadDelta])

  const map = useMemo(() => {
    const m: Record<string, OutcomeRow> = {}
    for (const r of rows ?? []) {
      const k = (r.session_type || 'other').toLowerCase()
      m[k] = r
    }
    return m
  }, [rows])

  const cards = [
    { key: 'ask', title: 'Ask queries', row: map.ask },
    { key: 'overnight', title: 'Overnight runs', row: map.overnight },
    { key: 'forge', title: 'Forge features', row: map.forge },
  ]

  const cardCls = `rounded-3xl border p-6 ${border} ${subtle} ${isDark ? 'bg-white/[0.03]' : 'bg-white/60'}`

  return (
    <section>
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] opacity-40 mb-4">Cost per outcome</p>
      {loading && <SectionSkeleton isDark={isDark} border={border} />}
      {!loading && err && !rows && (
        <div className={`p-8 ${cardCls}`}>
          <SectionError message={err} isDark={isDark} />
        </div>
      )}
      {!loading && rows && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {cards.map((c) => (
            <div key={c.key} className={cardCls}>
              <p className="text-xs font-semibold uppercase tracking-wider opacity-50 mb-4">{c.title}</p>
              {!c.row || c.row.run_count === 0 ? (
                <p className="text-sm opacity-50 leading-relaxed">No data yet — costs logged as calls are made</p>
              ) : (
                <dl className="space-y-3">
                  <div>
                    <dt className="text-[10px] uppercase opacity-40">Runs</dt>
                    <dd className="text-2xl font-semibold tabular-nums">{c.row.run_count}</dd>
                  </div>
                  <div>
                    <dt className="text-[10px] uppercase opacity-40">Avg $/run</dt>
                    <dd className="text-lg font-mono tabular-nums">{fmtMoney(c.row.avg_usd)}</dd>
                  </div>
                  <div>
                    <dt className="text-[10px] uppercase opacity-40">Total this month</dt>
                    <dd className="text-lg font-mono tabular-nums">{fmtMoney(c.row.total_usd)}</dd>
                  </div>
                </dl>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

/* —— 5. Subscriptions + chart —— */

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

function SubscriptionSection({
  isDark,
  border,
  subtle,
  refreshKey,
  onLoadDelta,
}: {
  isDark: boolean
  border: string
  subtle: string
  refreshKey: number
  onLoadDelta?: LoadDeltaFn
}) {
  const [rows, setRows] = useState<SubscriptionRow[] | null>(null)
  const [loading, setLoading] = useState(true)
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

  const load = useCallback(() => {
    onLoadDelta?.(1)
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
      .finally(() => {
        setLoading(false)
        onLoadDelta?.(-1)
      })
  }, [onLoadDelta])

  useEffect(() => {
    load()
  }, [refreshKey, load])

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
      {loading && <SectionSkeleton isDark={isDark} border={border} />}
      {!loading && err && !rows && (
        <div className={`p-8 ${card}`}>
          <SectionError message={err} isDark={isDark} />
        </div>
      )}
      {!loading && rows && (
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
            {err && rows.length >= 0 && <p className="text-xs text-rose-500 p-4 border-t border-white/5">{err}</p>}
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

/* —— 6. Power + hardware —— */

function PowerSection({
  isDark,
  border,
  subtle,
  refreshKey,
  onLoadDelta,
}: {
  isDark: boolean
  border: string
  subtle: string
  refreshKey: number
  onLoadDelta?: LoadDeltaFn
}) {
  const [power, setPower] = useState<PowerPayload | null>(null)
  const [hw, setHw] = useState<HardwarePayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [editingRate, setEditingRate] = useState(false)
  const [rateInput, setRateInput] = useState('')
  const [savingRate, setSavingRate] = useState(false)
  const [live, setLive] = useState<any>(null)
  const [rate, setRate] = useState<number>(0.13)

  const load = useCallback(() => {
    onLoadDelta?.(1)
    setErr(null)
    Promise.all([apiJson<PowerPayload>('/v1/costs/power'), apiJson<HardwarePayload>('/v1/costs/hardware')])
      .then(([p, h]) => {
        setPower(p)
        setHw(h)
        setRateInput(String(p.rate_per_kwh))
        setRate(p.rate_per_kwh)
        setErr(null)
      })
      .catch(() => {
        setPower(null)
        setHw(null)
        setErr('Could not load power or hardware.')
      })
      .finally(() => {
        onLoadDelta?.(-1)
      })
  }, [onLoadDelta])

  useEffect(() => {
    setLoading(true)
    setErr(null)
    Promise.all([
      apiJson<any>('/v1/metrics/power/current').catch(() => null),
      apiJson<any>('/v1/costs/power').catch(() => null),
      apiJson<HardwarePayload>('/v1/costs/hardware').catch(() => null),
    ]).then(([liveData, costData, hwData]) => {
      setLive(liveData)
      setRate(costData?.rate_per_kwh ?? 0.13)
      if (costData) {
        setPower(costData as PowerPayload)
        setRateInput(String((costData as PowerPayload).rate_per_kwh))
      } else {
        setPower(null)
      }
      setHw(hwData)
      if (!costData || !hwData) setErr('Could not load power or hardware.')
      else setErr(null)
    }).finally(() => setLoading(false))
  }, [refreshKey])

  const saveRate = async () => {
    if (!power) return
    setSavingRate(true)
    try {
      await apiJson('/v1/costs/power/rate', {
        method: 'POST',
        body: JSON.stringify({ rate_per_kwh: parseFloat(rateInput) }),
      })
      setEditingRate(false)
      load()
    } catch {
      setErr('Rate update failed.')
    } finally {
      setSavingRate(false)
    }
  }

  const order = ['Brain', 'Gateway', 'Endpoint', 'Sandbox']
  const card = `rounded-3xl border overflow-hidden h-full flex flex-col ${border} ${subtle} ${
    isDark ? 'bg-white/[0.03]' : 'bg-white/60'
  }`

  const chartH = 180
  const chartW = 400
  const padL = 44
  const padB = 28
  const padT = 16
  const barAreaW = chartW - padL - 16
  const barAreaH = chartH - padB - padT
  const wattsList = power
    ? order.map((nodeName) => {
        const staticWatts = power.nodes.find((n) => n.name === nodeName)?.watts ?? 0
        return live?.nodes?.find((n: any) => n.node_name === nodeName)?.avg_watts_24h ?? staticWatts
      })
    : [0, 0, 0, 0]
  const maxW = Math.max(1, ...wattsList) * 1.1
  const barGap = 12
  const barW = (barAreaW - barGap * 3) / 4

  return (
    <section>
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] opacity-40 mb-4">Power + hardware (true TCO)</p>
      {loading && <SectionSkeleton isDark={isDark} border={border} />}
      {!loading && err && (!power || !hw) && (
        <div className={`p-8 ${card}`}>
          <SectionError message={err} isDark={isDark} />
        </div>
      )}
      {!loading && power && hw && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 lg:gap-6 items-stretch">
          <div className={card}>
            <div className="flex flex-wrap items-center justify-end gap-2 p-4 border-b border-white/5">
              {!editingRate ? (
                <button
                  type="button"
                  onClick={() => {
                    setEditingRate(true)
                    setRateInput(String(power?.rate_per_kwh ?? rate))
                  }}
                  className={`inline-flex items-center gap-2 text-xs font-mono px-3 py-1.5 rounded-full border ${border}`}
                >
                  <Pencil className="w-3.5 h-3.5" />
                  {(power?.rate_per_kwh ?? rate).toFixed(4)} $/kWh
                </button>
              ) : (
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    step="0.0001"
                    value={rateInput}
                    onChange={(e) => setRateInput(e.target.value)}
                    className={`w-28 px-3 py-1.5 rounded-xl border text-xs font-mono bg-transparent ${border}`}
                  />
                  <button
                    type="button"
                    disabled={savingRate}
                    onClick={saveRate}
                    className="p-1.5 rounded-xl bg-emerald-500 text-[#0a0a0a]"
                  >
                    <Check className="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setEditingRate(false)
                      setRateInput(String(power?.rate_per_kwh ?? rate))
                    }}
                    className="p-1.5 rounded-xl border border-white/10"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
            <div className="overflow-x-auto flex-1">
              <table className="w-full text-xs min-w-[280px]">
                <thead>
                  <tr className={`text-[9px] font-semibold uppercase opacity-40 border-b ${border}`}>
                    <th className="text-left p-3">Node</th>
                    <th className="text-right p-3">Watts</th>
                    <th className="text-right p-3">Power $/mo</th>
                    <th className="text-right p-3">Hardware $/mo</th>
                    <th className="text-right p-3">True $/mo</th>
                  </tr>
                </thead>
                <tbody>
                  {order.map((name) => {
                    const pn = power.nodes.find((n) => n.name === name)
                    const hn = hw.nodes.find((n) => n.node_name === name)
                    const pCost = pn?.cost_monthly ?? 0
                    const hCost = hn?.monthly_usd ?? 0
                    const displayWatts =
                      live?.nodes?.find((n: any) => n.node_name === name)?.avg_watts_24h ?? pn?.watts
                    const showLiveDot =
                      live?.nodes?.find((n: any) => n.node_name === name)?.has_live_data === true
                    const showEst =
                      live?.nodes?.find((n: any) => n.node_name === name)?.source === 'static'
                    return (
                      <tr key={name} className={`border-b border-white/5 ${border}`}>
                        <td className="p-3 font-medium">
                          <div className="flex items-center gap-2 flex-wrap">
                            {name}
                            {showLiveDot && (
                              <span className="flex items-center gap-1 text-[9px] font-semibold uppercase text-emerald-500">
                                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                                live
                              </span>
                            )}
                            {showEst && <span className="text-[9px] opacity-40 font-normal">est.</span>}
                          </div>
                        </td>
                        <td className="p-3 text-right font-mono tabular-nums">
                          {typeof displayWatts === 'number' ? `${displayWatts.toFixed(1)}` : '—'}
                        </td>
                        <td className="p-3 text-right font-mono tabular-nums">{fmtMoney(pCost)}</td>
                        <td className="p-3 text-right font-mono tabular-nums">{fmtMoney(hCost)}</td>
                        <td className="p-3 text-right font-mono font-semibold tabular-nums">
                          {fmtMoney(pCost + hCost)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot>
                  <tr className={`font-semibold ${isDark ? 'bg-white/[0.04]' : 'bg-[#141414]/5'}`}>
                    <td className="p-3">Total</td>
                    <td className="p-3 text-right font-mono tabular-nums">{power.total_watts.toFixed(1)}</td>
                    <td className="p-3 text-right font-mono tabular-nums">{fmtMoney(power.total_cost_monthly)}</td>
                    <td className="p-3 text-right font-mono tabular-nums">{fmtMoney(hw.total_monthly_usd)}</td>
                    <td className="p-3 text-right font-mono tabular-nums">
                      {fmtMoney(power.total_cost_monthly + hw.total_monthly_usd)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
            {err && <p className="text-xs text-rose-500 p-3 border-t border-white/5">{err}</p>}
          </div>

          <div className={card}>
            <div className="p-4 border-b border-white/5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.2em] opacity-50">LIVE POWER DRAW</p>
              <p className="text-[10px] opacity-40 mt-1">24h avg</p>
            </div>
            <div className="p-4 flex-1 flex items-center justify-center">
              <svg width="100%" viewBox={`0 0 ${chartW} ${chartH}`} className="max-w-full" style={{ maxHeight: chartH }}>
                <line
                  x1={padL}
                  y1={chartH - padB}
                  x2={chartW - 8}
                  y2={chartH - padB}
                  stroke={isDark ? 'rgba(255,255,255,0.12)' : 'rgba(20,20,20,0.15)'}
                  strokeWidth={1}
                />
                <line
                  x1={padL}
                  y1={padT}
                  x2={padL}
                  y2={chartH - padB}
                  stroke={isDark ? 'rgba(255,255,255,0.12)' : 'rgba(20,20,20,0.15)'}
                  strokeWidth={1}
                />
                <text
                  x={8}
                  y={padT + 4}
                  className={`text-[9px] font-mono ${isDark ? 'fill-white/35' : 'fill-[#141414]/45'}`}
                >
                  {maxW.toFixed(0)}W
                </text>
                <text
                  x={8}
                  y={chartH - padB}
                  className={`text-[9px] font-mono ${isDark ? 'fill-white/35' : 'fill-[#141414]/45'}`}
                >
                  0
                </text>
                {order.map((name, i) => {
                  const w = wattsList[i] ?? 0
                  const h = (w / maxW) * barAreaH
                  const x = padL + i * (barW + barGap)
                  const y = chartH - padB - h
                  const fill = name === 'Brain' ? '#22c55e' : '#f59e0b'
                  return (
                    <g key={name}>
                      <rect x={x} y={y} width={barW} height={Math.max(h, 0)} rx={4} fill={fill} opacity={0.9} />
                      <text
                        x={x + barW / 2}
                        y={y - 6}
                        textAnchor="middle"
                        className={`text-[10px] font-mono font-semibold ${isDark ? 'fill-white/80' : 'fill-[#141414]'}`}
                      >
                        {w.toFixed(1)}
                      </text>
                      <text
                        x={x + barW / 2}
                        y={chartH - padB + 14}
                        textAnchor="middle"
                        className={`text-[9px] font-medium ${isDark ? 'fill-white/40' : 'fill-[#141414]/50'}`}
                      >
                        {name}
                      </text>
                    </g>
                  )
                })}
              </svg>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

/* —— 7. Forge —— */

function ForgeSection({
  isDark,
  border,
  subtle,
  refreshKey,
  onLoadDelta,
}: {
  isDark: boolean
  border: string
  subtle: string
  refreshKey: number
  onLoadDelta?: LoadDeltaFn
}) {
  const [summary, setSummary] = useState<CostsSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(false)

  useEffect(() => {
    let a = true
    onLoadDelta?.(1)
    setLoading(true)
    setErr(false)
    apiJson<CostsSummary>('/v1/costs/summary')
      .then((d) => {
        if (a) {
          setSummary(d)
          setErr(false)
        }
      })
      .catch(() => {
        if (a) {
          setSummary(null)
          setErr(true)
        }
      })
      .finally(() => {
        if (a) setLoading(false)
        onLoadDelta?.(-1)
      })
    return () => {
      a = false
    }
  }, [refreshKey, onLoadDelta])

  const card = `rounded-3xl border p-8 ${border} ${subtle} ${isDark ? 'bg-white/[0.03]' : 'bg-white/60'}`

  return (
    <section>
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] opacity-40 mb-4">Forge pipeline</p>
      {loading && <SectionSkeleton isDark={isDark} border={border} />}
      {!loading && err && (
        <div className={card}>
          <span className="text-[10px] font-semibold uppercase tracking-wide px-3 py-1 rounded-full border border-amber-500/40 text-amber-500">
            Forge offline
          </span>
        </div>
      )}
      {!loading && !err && summary && (
        <div className={card}>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-xs opacity-50 mb-2">Monthly total</p>
              <p className="text-4xl font-semibold tabular-nums tracking-tight">
                {fmtMoney(summary.forge_monthly_usd ?? 0)}
              </p>
            </div>
            <a
              href="https://jarvis-forge.tail40ed36.ts.net:5001"
              target="_blank"
              rel="noopener noreferrer"
              className={`inline-flex items-center gap-2 text-sm font-medium px-5 py-2.5 rounded-full border ${border} hover:opacity-90`}
            >
              <ExternalLink className="w-4 h-4" />
              Forge dashboard
            </a>
          </div>
        </div>
      )}
    </section>
  )
}

/* —— Savings card —— */

function SavingsCard({
  isDark,
  border,
  refreshKey,
  onLoadDelta,
}: {
  isDark: boolean
  border: string
  refreshKey: number
  onLoadDelta?: LoadDeltaFn
}) {
  const [data, setData] = useState<CostsSummary | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let a = true
    onLoadDelta?.(1)
    apiJson<CostsSummary>('/v1/costs/summary')
      .then((d) => {
        if (a) setData(d)
      })
      .catch(() => {
        if (a) setData(null)
      })
      .finally(() => {
        if (a) setLoading(false)
        onLoadDelta?.(-1)
      })
    return () => {
      a = false
    }
  }, [refreshKey, onLoadDelta])

  const savings = data?.savings_vs_cloud_usd ?? 0
  const pct = data?.local_routing_pct
  const hasPct = typeof pct === 'number' && pct > 0

  if (loading || savings <= 0) return null
  if (!hasPct) return null

  return (
    <div
      className={`rounded-3xl border p-6 ${border} ${
        isDark ? 'bg-emerald-500/10 border-emerald-500/25' : 'bg-emerald-50 border-emerald-200/80'
      }`}
    >
      <p className="text-sm font-medium text-emerald-600 dark:text-emerald-400">
        Estimated savings vs full cloud this month:{' '}
        <span className="font-semibold tabular-nums">{fmtMoney(savings)}</span>
      </p>
      <p className="text-xs opacity-70 mt-2">Based on {pct}% local routing</p>
    </div>
  )
}

/* —— Page —— */

export default function CostCenter() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/[0.08]' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/[0.02]' : 'bg-white/40'

  const [refreshKey, setRefreshKey] = useState(0)
  const loadCountRef = useRef(0)
  const [, bump] = useState(0)
  const onLoadDelta = useCallback((d: number) => {
    loadCountRef.current = Math.max(0, loadCountRef.current + d)
    bump((x) => x + 1)
  }, [])
  const spinning = loadCountRef.current > 0

  const doRefresh = useCallback(() => {
    setRefreshKey((k) => k + 1)
  }, [])

  useEffect(() => {
    const id = window.setInterval(doRefresh, 3600000)
    return () => window.clearInterval(id)
  }, [doRefresh])

  return (
    <div className="space-y-16 max-w-6xl pb-24">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-4xl sm:text-5xl font-semibold tracking-tight">Cost Center</h1>
        <button
          type="button"
          onClick={doRefresh}
          className={`inline-flex items-center gap-2 px-3 py-2 rounded-xl border text-xs font-mono uppercase tracking-wide ${border} ${
            isDark ? 'hover:bg-white/5' : 'hover:bg-[#141414]/5'
          }`}
        >
          <RefreshCw className={`w-4 h-4 ${spinning ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </header>

      <SavingsCard isDark={isDark} border={border} refreshKey={refreshKey} onLoadDelta={onLoadDelta} />
      <HeroSection
        isDark={isDark}
        border={border}
        subtle={subtle}
        refreshKey={refreshKey}
        onLoadDelta={onLoadDelta}
      />
      <PieSection
        isDark={isDark}
        border={border}
        subtle={subtle}
        refreshKey={refreshKey}
        onLoadDelta={onLoadDelta}
      />
      <ApiSpendSection
        isDark={isDark}
        border={border}
        subtle={subtle}
        refreshKey={refreshKey}
        onLoadDelta={onLoadDelta}
      />
      <OutcomeSection
        isDark={isDark}
        border={border}
        subtle={subtle}
        refreshKey={refreshKey}
        onLoadDelta={onLoadDelta}
      />
      <SubscriptionSection
        isDark={isDark}
        border={border}
        subtle={subtle}
        refreshKey={refreshKey}
        onLoadDelta={onLoadDelta}
      />
      <PowerSection
        isDark={isDark}
        border={border}
        subtle={subtle}
        refreshKey={refreshKey}
        onLoadDelta={onLoadDelta}
      />
      <ForgeSection
        isDark={isDark}
        border={border}
        subtle={subtle}
        refreshKey={refreshKey}
        onLoadDelta={onLoadDelta}
      />
    </div>
  )
}
