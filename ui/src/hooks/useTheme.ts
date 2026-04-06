import { useAppStore } from '../store'

export function useTheme() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/[0.08]' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/[0.02]' : 'bg-white/40'
  const muted = isDark ? 'text-zinc-500' : 'text-zinc-400'
  const fg = isDark ? 'text-white' : 'text-zinc-900'
  const text = isDark ? 'text-zinc-100' : 'text-zinc-800'

  const cardBase = (extra = '') =>
    `rounded-3xl border p-4 backdrop-blur-xl ${border} ${isDark ? 'bg-white/[0.04] shadow-[0_1px_0_rgba(255,255,255,0.06)_inset]' : 'bg-white/70 shadow-sm'} ${extra}`

  return { isDark, theme, border, subtle, muted, fg, text, cardBase }
}
