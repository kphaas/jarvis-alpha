import { useEffect, useMemo, useState } from 'react'
import { apiJson } from '../../lib/apiFetch'
import { SectionSkeleton } from '../shared/SectionSkeleton'
import { SectionError } from '../shared/SectionError'
import { DonutChart } from './DonutChart'
import type { CostsSummary, PowerPayload, HardwarePayload } from '../../types/costs'
import { fmtMoney } from '../../types/costs'

type LoadDeltaFn = (delta: number) => void

export function PieSection({
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
      {loading && <SectionSkeleton />}
      {!loading && err && (
        <div className={wrap}>
          <SectionError message={err} />
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
