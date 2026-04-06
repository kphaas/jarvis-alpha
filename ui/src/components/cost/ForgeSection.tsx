import { ExternalLink } from 'lucide-react'
import { useCostsSummary } from '../../hooks/useCosts'
import { SectionSkeleton } from '../shared/SectionSkeleton'
import { fmtMoney } from '../../types/costs'

export function ForgeSection({
  isDark,
  border,
  subtle,
}: {
  isDark: boolean
  border: string
  subtle: string
}) {
  const { data: summary, isLoading, error } = useCostsSummary()
  const err = Boolean(error)

  const card = `rounded-3xl border p-8 ${border} ${subtle} ${isDark ? 'bg-white/[0.03]' : 'bg-white/60'}`

  return (
    <section>
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] opacity-40 mb-4">Forge pipeline</p>
      {isLoading && <SectionSkeleton />}
      {!isLoading && err && (
        <div className={card}>
          <span className="text-[10px] font-semibold uppercase tracking-wide px-3 py-1 rounded-full border border-amber-500/40 text-amber-500">
            Forge offline
          </span>
        </div>
      )}
      {!isLoading && !err && summary && (
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
