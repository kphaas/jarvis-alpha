import { useEffect, useMemo, useState } from 'react'
import { apiJson } from '../../lib/apiFetch'
import { SectionSkeleton } from '../shared/SectionSkeleton'
import { SectionError } from '../shared/SectionError'
import type { OutcomeRow } from '../../types/costs'
import { fmtMoney } from '../../types/costs'

type LoadDeltaFn = (delta: number) => void

export function OutcomeSection({
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
      {loading && <SectionSkeleton />}
      {!loading && err && !rows && (
        <div className={`p-8 ${cardCls}`}>
          <SectionError message={err} />
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
