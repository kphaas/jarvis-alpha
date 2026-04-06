import { useTheme } from '../../hooks/useTheme'

export function SectionError({ message, className = '' }: { message: string; className?: string }) {
  const { isDark } = useTheme()
  return (
    <p className={`text-xs font-medium ${isDark ? 'text-amber-400/90' : 'text-amber-700'} ${className}`}>
      {message}
    </p>
  )
}
