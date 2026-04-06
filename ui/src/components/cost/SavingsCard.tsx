import { useEffect, useState } from 'react'
import { apiJson } from '../../lib/apiFetch'
import type { CostsSummary } from '../../types/costs'
import { fmtMoney } from '../../types/costs'

type LoadDeltaFn = (delta: number) => void

export function SavingsCard({
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
