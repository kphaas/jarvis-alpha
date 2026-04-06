import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
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

export default function CostCenter() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/[0.08]' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/[0.02]' : 'bg-white/40'
  const qc = useQueryClient()
  const [spinning, setSpinning] = useState(false)

  const doRefresh = async () => {
    setSpinning(true)
    try {
      await qc.invalidateQueries({ queryKey: ['costs'] })
    } finally {
      setSpinning(false)
    }
  }

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

      <SavingsCard isDark={isDark} border={border} />
      <HeroSection isDark={isDark} border={border} subtle={subtle} />
      <PieSection isDark={isDark} border={border} subtle={subtle} />
      <ApiSpendSection isDark={isDark} border={border} subtle={subtle} />
      <OutcomeSection isDark={isDark} border={border} subtle={subtle} />
      <SubscriptionSection isDark={isDark} border={border} subtle={subtle} />
      <PowerSection isDark={isDark} border={border} subtle={subtle} />
      <ForgeSection isDark={isDark} border={border} subtle={subtle} />
    </div>
  )
}
