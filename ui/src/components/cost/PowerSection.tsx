import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Check, Pencil, X } from 'lucide-react'
import { apiJson } from '../../lib/apiFetch'
import { useCostsPower, usePowerLive } from '../../hooks/useCosts'
import { SectionSkeleton } from '../shared/SectionSkeleton'
import { SectionError } from '../shared/SectionError'
import { fmtMoney } from '../../types/costs'

export function PowerSection({
  isDark,
  border,
  subtle,
}: {
  isDark: boolean
  border: string
  subtle: string
}) {
  const qc = useQueryClient()
  const costsPower = useCostsPower()
  const power = costsPower.data?.power ?? null
  const hw = costsPower.data?.hardware ?? null
  const liveQuery = usePowerLive()
  const live = liveQuery.data
  const loading = costsPower.isLoading
  const [err, setErr] = useState<string | null>(null)
  const [editingRate, setEditingRate] = useState(false)
  const [rateInput, setRateInput] = useState('')
  const [savingRate, setSavingRate] = useState(false)

  const saveRate = async () => {
    if (!power) return
    setSavingRate(true)
    try {
      await apiJson('/v1/costs/power/rate', {
        method: 'POST',
        body: JSON.stringify({ rate_per_kwh: parseFloat(rateInput) }),
      })
      setEditingRate(false)
      await qc.invalidateQueries({ queryKey: ['costs', 'power'] })
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
      {loading && <SectionSkeleton />}
      {!loading && (err || costsPower.error) && (!power || !hw) && (
        <div className={`p-8 ${card}`}>
          <SectionError message={err ?? 'Could not load power or hardware.'} />
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
                    setRateInput(String(power?.rate_per_kwh ?? 0.13))
                  }}
                  className={`inline-flex items-center gap-2 text-xs font-mono px-3 py-1.5 rounded-full border ${border}`}
                >
                  <Pencil className="w-3.5 h-3.5" />
                  {(power?.rate_per_kwh ?? 0.13).toFixed(4)} $/kWh
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
                      setRateInput(String(power?.rate_per_kwh ?? 0.13))
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
            {(err || costsPower.error || liveQuery.error) && (
              <p className="text-xs text-rose-500 p-3 border-t border-white/5">{err ?? 'Could not load power or hardware.'}</p>
            )}
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
