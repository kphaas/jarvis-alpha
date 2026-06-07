import { Check, ShieldAlert } from 'lucide-react'
import type { PrivacyTarget } from '../../types/privacy'
import { TARGET_METHOD_LABEL } from '../../types/privacy'

function flagClass(isDark: boolean, tone: 'warn' | 'soft') {
  if (tone === 'warn') {
    return isDark
      ? 'border-amber-400/25 bg-amber-500/10 text-amber-200'
      : 'border-amber-800/20 bg-amber-50 text-amber-900'
  }
  return isDark
    ? 'border-white/10 bg-white/5 text-white/70'
    : 'border-[#141414]/10 bg-[#141414]/5 text-[#4A4741]'
}

function responseWindow(days: number | null) {
  return days === null ? 'Response window unknown' : `About ${days} days`
}

export function PrivacyTargetCard({
  target,
  selected,
  onToggle,
  border,
  panel,
  muted,
  isDark,
}: {
  target: PrivacyTarget
  selected: boolean
  onToggle: () => void
  border: string
  panel: string
  muted: string
  isDark: boolean
}) {
  const riskFlags = [
    target.supports_minors ? 'Minors' : null,
    target.requires_sensitive_payload ? 'Sensitive' : null,
    target.requires_identity_document ? 'ID required' : null,
  ].filter(Boolean)

  return (
    <label
      className={`block cursor-pointer rounded-lg border p-3 transition focus-within:ring-2 focus-within:ring-emerald-700/25 dark:focus-within:ring-emerald-300/25 ${
        selected
          ? isDark
            ? 'border-emerald-300/60 bg-emerald-500/10'
            : 'border-emerald-900/25 bg-emerald-50'
          : `${border} ${panel}`
      }`}
    >
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          className="mt-1 h-5 w-5 accent-emerald-700 dark:accent-emerald-300"
          aria-label={`Select ${target.name}`}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{target.name}</p>
              <p className={`mt-1 text-sm ${muted}`}>
                {TARGET_METHOD_LABEL[target.opt_out_method]} · {target.jurisdiction} · {responseWindow(target.avg_response_days)}
              </p>
            </div>
            {selected && (
              <Check className="h-4 w-4 shrink-0 text-emerald-700 dark:text-emerald-300" />
            )}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <span className={`rounded-md border px-2 py-1 text-xs font-medium ${flagClass(isDark, 'soft')}`}>
              {target.category.replace('_', ' ')}
            </span>
            {riskFlags.map((flag) => (
              <span key={flag} className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium ${flagClass(isDark, 'warn')}`}>
                <ShieldAlert className="h-3 w-3" />
                {flag}
              </span>
            ))}
          </div>
        </div>
      </div>
    </label>
  )
}
