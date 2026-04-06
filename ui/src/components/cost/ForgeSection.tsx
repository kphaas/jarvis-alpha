import { useEffect, useState } from 'react'
import { ExternalLink } from 'lucide-react'
import { apiJson } from '../../lib/apiFetch'
import { SectionSkeleton } from '../shared/SectionSkeleton'
import type { CostsSummary } from '../../types/costs'
import { fmtMoney } from '../../types/costs'

type LoadDeltaFn = (delta: number) => void

export function ForgeSection({
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
      {loading && <SectionSkeleton />}
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
