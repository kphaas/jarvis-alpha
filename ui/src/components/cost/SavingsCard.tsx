import { useCostsSummary } from '../../hooks/useCosts'
import { fmtMoney } from '../../types/costs'

export function SavingsCard({
  isDark,
  border,
}: {
  isDark: boolean
  border: string
}) {
  const { data, isLoading } = useCostsSummary()

  const savings = data?.savings_vs_cloud_usd ?? 0
  const pct = data?.local_routing_pct
  const hasPct = typeof pct === 'number' && pct > 0

  if (isLoading || savings <= 0) return null
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
