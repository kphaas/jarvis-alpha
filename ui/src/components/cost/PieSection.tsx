import { useMemo } from 'react'
import { useCostsPower, useCostsSummary } from '../../hooks/useCosts'
import { SectionSkeleton } from '../shared/SectionSkeleton'
import { SectionError } from '../shared/SectionError'
import { DonutChart } from './DonutChart'
import type { CostsSummary } from '../../types/costs'
import { fmtMoney } from '../../types/costs'

export function PieSection({
  isDark,
  border,
  subtle,
}: {
  isDark: boolean
  border: string
  subtle: string
}) {
  const { data, isLoading, error } = useCostsSummary()
  const err = error ? 'Could not load charts.' : null

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

  const wrap = `rounded-2xl border p-5 ${border} ${subtle} ${
    isDark ? 'bg-white/[0.03]' : 'bg-white/60'
  }`

  return (
    <section>
      {isLoading && <SectionSkeleton />}
      {!isLoading && err && (
        <div className={wrap}>
          <SectionError message={err} />
        </div>
      )}
      {!isLoading && !err && data && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className={wrap}>
            <p className="text-center text-xs font-semibold uppercase tracking-[0.25em] opacity-40 mb-3">Alpha</p>
            <DonutChart
              slices={alphaSlices}
              centerLabel="Total"
              centerValue={fmtMoney(alphaTotal)}
              isDark={isDark}
            />
            <ul className="mt-4 space-y-1 max-w-xs mx-auto">
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
}: {
  isDark: boolean
  border: string
  subtle: string
  summary: CostsSummary
}) {
  const costsPower = useCostsPower()
  const power = costsPower.data?.power
  const hw = costsPower.data?.hardware

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
  const wrap = `rounded-2xl border p-5 ${border} ${subtle} ${isDark ? 'bg-white/[0.03]' : 'bg-white/60'}`

  return (
    <div className={wrap}>
      <p className="text-center text-xs font-semibold uppercase tracking-[0.25em] opacity-40 mb-3">Forge</p>
      <DonutChart slices={slices} centerLabel="Total" centerValue={fmtMoney(total)} isDark={isDark} />
      <ul className="mt-4 space-y-1 max-w-xs mx-auto">
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
