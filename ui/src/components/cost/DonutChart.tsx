import { useMemo } from 'react'

export interface DonutSlice {
  key: string
  label: string
  value: number
  color: string
}

function donutSlicePath(
  cx: number, cy: number, rOut: number, rIn: number, a0: number, a1: number
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

export function DonutChart({
  slices,
  centerLabel,
  centerValue,
  isDark,
  size = 150,
}: {
  slices: DonutSlice[]
  centerLabel: string
  centerValue: string
  isDark: boolean
  size?: number
}) {
  const cx = size / 2
  const cy = size / 2
  const rOut = size * 0.38
  const rIn = size * 0.22

  const paths = useMemo(() => {
    const total = slices.reduce((s, x) => s + Math.max(0, x.value), 0)
    if (total <= 0) return []
    const result: { d: string; color: string; key: string }[] = []
    let angle = -Math.PI / 2
    for (const sl of slices) {
      const v = Math.max(0, sl.value)
      if (v <= 0) continue
      const span = (v / total) * Math.PI * 2
      result.push({
        d: donutSlicePath(cx, cy, rOut, rIn, angle, angle + span),
        color: sl.color,
        key: sl.key,
      })
      angle += span
    }
    return result
  }, [slices, cx, cy, rOut, rIn])

  const total = slices.reduce((s, x) => s + Math.max(0, x.value), 0)

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
          paths.map((p) => (
            <path key={p.key} d={p.d} fill={p.color} className="transition-opacity hover:opacity-90" />
          ))
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
