import { type ReactNode } from 'react'
import { useTheme } from '../../hooks/useTheme'

type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral'

const VARIANT_CLASSES: Record<BadgeVariant, { dark: string; light: string }> = {
  success: {
    dark: 'border-emerald-500/30 bg-emerald-500/15 text-emerald-400',
    light: 'border-emerald-600/30 bg-emerald-500/10 text-emerald-700',
  },
  warning: {
    dark: 'border-amber-500/30 bg-amber-500/15 text-amber-400',
    light: 'border-amber-600/30 bg-amber-500/10 text-amber-700',
  },
  error: {
    dark: 'border-rose-500/30 bg-rose-500/15 text-rose-400',
    light: 'border-rose-600/30 bg-rose-500/10 text-rose-700',
  },
  info: {
    dark: 'border-blue-500/30 bg-blue-500/15 text-blue-400',
    light: 'border-blue-600/30 bg-blue-500/10 text-blue-700',
  },
  neutral: {
    dark: 'border-zinc-500/30 bg-zinc-500/15 text-zinc-400',
    light: 'border-zinc-500/30 bg-zinc-500/10 text-zinc-600',
  },
}

export function StatusBadge({
  children,
  variant = 'neutral',
  pulse = false,
  className = '',
}: {
  children: ReactNode
  variant?: BadgeVariant
  pulse?: boolean
  className?: string
}) {
  const { isDark } = useTheme()
  const colors = isDark ? VARIANT_CLASSES[variant].dark : VARIANT_CLASSES[variant].light
  return (
    <span
      className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${colors} ${pulse ? 'animate-pulse' : ''} ${className}`}
    >
      {children}
    </span>
  )
}
