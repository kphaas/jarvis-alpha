import { useTheme } from '../../hooks/useTheme'

export function SectionSkeleton({ className = '' }: { className?: string }) {
  const { isDark, border } = useTheme()
  return (
    <div className={`animate-pulse rounded-3xl border p-8 ${border} ${isDark ? 'bg-white/[0.03]' : 'bg-white/60'} ${className}`}>
      <div className={`h-3 w-40 rounded-full ${isDark ? 'bg-white/10' : 'bg-[#141414]/10'}`} />
      <div className={`mt-6 h-32 rounded-2xl ${isDark ? 'bg-white/[0.04]' : 'bg-[#141414]/5'}`} />
    </div>
  )
}
