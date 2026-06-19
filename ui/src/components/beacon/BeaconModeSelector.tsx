import { BEACON_MODES } from './modeConfig'
import type { BeaconFocusMode } from '../../types/beacon'

interface Props {
  value: BeaconFocusMode
  onChange: (value: BeaconFocusMode) => void
  isDark: boolean
}

export function BeaconModeSelector({ value, onChange, isDark }: Props) {
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  return (
    <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
      {BEACON_MODES.map((mode) => {
        const active = value === mode.key
        return (
          <button
            key={mode.key}
            type="button"
            onClick={() => onChange(mode.key)}
            className={`min-h-16 rounded-lg border px-3 py-2 text-left transition ${
              active
                ? isDark
                  ? 'border-emerald-400 bg-emerald-400/15 text-emerald-100'
                  : 'border-[#141414] bg-[#141414] text-[#E4E3E0]'
                : `${border} ${isDark ? 'bg-white/5 hover:bg-white/10' : 'bg-white/45 hover:bg-white/70'}`
            }`}
          >
            <span className="block text-sm font-semibold">{mode.label}</span>
            <span className={`mt-1 block text-xs ${active ? 'opacity-80' : 'opacity-55'}`}>
              {mode.description}
            </span>
          </button>
        )
      })}
    </div>
  )
}
