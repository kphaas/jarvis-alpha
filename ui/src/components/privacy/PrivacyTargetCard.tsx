import { Check, ShieldAlert } from 'lucide-react'
import type { PrivacyTarget } from '../../types/privacy'
import { TARGET_METHOD_LABEL } from '../../types/privacy'

function flagClass(isDark: boolean, tone: 'warn' | 'soft') {
  if (tone === 'warn') {
    return isDark
      ? 'border-amber-400/25 bg-amber-500/10 text-amber-200'
      : 'border-amber-700/20 bg-amber-50 text-amber-800'
  }
  return isDark
    ? 'border-white/10 bg-white/5 text-white/65'
    : 'border-[#141414]/10 bg-[#141414]/5 text-[#141414]/65'
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
    target.requires_identity_document ? 'ID' : null,
  ].filter(Boolean)

  return (
    <label className={`block cursor-pointer rounded-lg border p-3 transition ${border} ${selected ? 'border-emerald-400/60 bg-emerald-500/10' : panel}`}>
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          className="mt-1 h-4 w-4 accent-emerald-500"
          aria-label={`Select ${target.name}`}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{target.name}</p>
              <p className={`truncate text-[10px] font-mono uppercase tracking-widest ${muted}`}>{target.id}</p>
            </div>
            {selected && <Check className="h-4 w-4 shrink-0 text-emerald-400" />}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <span className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${flagClass(isDark, 'soft')}`}>
              {target.category.replace('_', ' ')}
            </span>
            <span className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${flagClass(isDark, 'soft')}`}>
              {TARGET_METHOD_LABEL[target.opt_out_method]}
            </span>
            <span className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${flagClass(isDark, 'soft')}`}>
              {target.jurisdiction}
            </span>
            {riskFlags.map((flag) => (
              <span key={flag} className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${flagClass(isDark, 'warn')}`}>
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
