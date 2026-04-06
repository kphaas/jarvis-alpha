import { useEffect, useMemo, useState } from 'react'
import { apiJson } from '../../lib/apiFetch'
import { SectionSkeleton } from '../shared/SectionSkeleton'
import { SectionError } from '../shared/SectionError'
import type { CostsSummary } from '../../types/costs'
import { fmtMoney } from '../../types/costs'

type LoadDeltaFn = (delta: number) => void

export function HeroSection({
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
      {loading && <SectionSkeleton />}
      {!loading && err && (
        <div className={`${cardBase} ${subtle}`}>
          <SectionError message={err} />
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
