import { useCallback, useEffect, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { useAppStore } from '../store'
import {
  HeroSection,
  PieSection,
  ApiSpendSection,
  OutcomeSection,
  SubscriptionSection,
  PowerSection,
  ForgeSection,
  SavingsCard,
} from '../components/cost'

type LoadDeltaFn = (delta: number) => void

export default function CostCenter() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/[0.08]' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/[0.02]' : 'bg-white/40'

  const [refreshKey, setRefreshKey] = useState(0)
  const loadCountRef = useRef(0)
  const [, bump] = useState(0)
  const onLoadDelta = useCallback<LoadDeltaFn>((d) => {
    loadCountRef.current = Math.max(0, loadCountRef.current + d)
    bump((x) => x + 1)
  }, [])
  const spinning = loadCountRef.current > 0

  const doRefresh = useCallback(() => {
    setRefreshKey((k) => k + 1)
  }, [])

  useEffect(() => {
    const id = window.setInterval(doRefresh, 3600000)
    return () => window.clearInterval(id)
  }, [doRefresh])

  return (
    <div className="space-y-16 max-w-6xl pb-24">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-4xl sm:text-5xl font-semibold tracking-tight">Cost Center</h1>
        <button
          type="button"
          onClick={doRefresh}
          className={`inline-flex items-center gap-2 px-3 py-2 rounded-xl border text-xs font-mono uppercase tracking-wide ${border} ${
            isDark ? 'hover:bg-white/5' : 'hover:bg-[#141414]/5'
          }`}
        >
          <RefreshCw className={`w-4 h-4 ${spinning ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </header>

      <SavingsCard isDark={isDark} border={border} refreshKey={refreshKey} onLoadDelta={onLoadDelta} />
      <HeroSection isDark={isDark} border={border} subtle={subtle} refreshKey={refreshKey} onLoadDelta={onLoadDelta} />
      <PieSection isDark={isDark} border={border} subtle={subtle} refreshKey={refreshKey} onLoadDelta={onLoadDelta} />
      <ApiSpendSection isDark={isDark} border={border} subtle={subtle} refreshKey={refreshKey} onLoadDelta={onLoadDelta} />
      <OutcomeSection isDark={isDark} border={border} subtle={subtle} refreshKey={refreshKey} onLoadDelta={onLoadDelta} />
      <SubscriptionSection isDark={isDark} border={border} subtle={subtle} refreshKey={refreshKey} onLoadDelta={onLoadDelta} />
      <PowerSection isDark={isDark} border={border} subtle={subtle} refreshKey={refreshKey} onLoadDelta={onLoadDelta} />
      <ForgeSection isDark={isDark} border={border} subtle={subtle} refreshKey={refreshKey} onLoadDelta={onLoadDelta} />
    </div>
  )
}
