import { useMemo, useState } from 'react'
import { Database, RefreshCw, X } from 'lucide-react'
import type { PrivacyTargetCategory } from '../../types/privacy'
import { TARGET_CATEGORIES } from '../../types/privacy'
import type { PrivacyTargetsState } from '../../hooks/usePrivacyTargets'
import { StatusLine } from './PrivacyFields'
import { PrivacyTargetCard } from './PrivacyTargetCard'

type CategoryFilter = 'all' | PrivacyTargetCategory

export function PrivacyTargetRegistry({
  targets,
  subjectId,
  border,
  panel,
  muted,
  isDark,
  okClass,
  warnClass,
  errorClass,
}: {
  targets: PrivacyTargetsState
  subjectId: string | null
  border: string
  panel: string
  muted: string
  isDark: boolean
  okClass: string
  warnClass: string
  errorClass: string
}) {
  const [category, setCategory] = useState<CategoryFilter>('all')
  const filteredTargets = useMemo(
    () => targets.targets.filter((target) => category === 'all' || target.category === category),
    [category, targets.targets],
  )
  const statusText = subjectId
    ? `${targets.selectedCount} selected`
    : `${targets.targets.length} targets`

  return (
    <section className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-sky-400" />
          <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>Target Registry</h2>
        </div>
        <div className="flex items-center gap-2">
          {targets.selectedCount > 0 && (
            <button
              type="button"
              onClick={targets.clearSelection}
              className={`inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border ${border}`}
              aria-label="Clear selected targets"
            >
              <X className="h-4 w-4" />
            </button>
          )}
          <button
            type="button"
            onClick={() => targets.refreshTargets()}
            disabled={targets.refreshLoading}
            className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm transition disabled:opacity-40 ${border}`}
          >
            <RefreshCw className={`h-4 w-4 ${targets.refreshLoading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
        <button
          type="button"
          onClick={() => setCategory('all')}
          className={`min-h-11 rounded-lg border px-2 text-xs font-mono uppercase ${border} ${category === 'all' ? 'bg-emerald-500 text-[#0A0A0A]' : ''}`}
        >
          All
        </button>
        {TARGET_CATEGORIES.map((item) => (
          <button
            key={item.value}
            type="button"
            onClick={() => setCategory(item.value)}
            className={`min-h-11 rounded-lg border px-2 text-xs font-mono uppercase ${border} ${category === item.value ? 'bg-emerald-500 text-[#0A0A0A]' : ''}`}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="mt-4 space-y-3">
        {targets.error && <StatusLine icon="error" className={errorClass} text="Target registry unavailable" />}
        {targets.refreshError && <StatusLine icon="error" className={errorClass} text="Target refresh failed" />}
        {targets.refreshResult && (
          <StatusLine icon="ok" className={okClass} text={`${targets.refreshResult.count} targets refreshed`} />
        )}
        {!targets.error && !targets.isLoading && targets.targets.length === 0 && (
          <StatusLine icon="error" className={warnClass} text="No targets loaded" />
        )}
        {targets.isLoading && <div className={`h-28 animate-pulse rounded-lg ${isDark ? 'bg-white/5' : 'bg-[#141414]/5'}`} />}
        {!targets.isLoading && filteredTargets.map((target) => (
          <PrivacyTargetCard
            key={target.id}
            target={target}
            selected={targets.selectedIds.includes(target.id)}
            onToggle={() => targets.toggleTarget(target)}
            border={border}
            panel={isDark ? 'bg-[#0A0A0A]/60' : 'bg-[#E4E3E0]/60'}
            muted={muted}
            isDark={isDark}
          />
        ))}
      </div>

      <div className={`mt-4 rounded-lg border px-3 py-2 text-[10px] font-mono uppercase tracking-widest ${targets.selectedCount > 0 ? okClass : warnClass}`}>
        {statusText}
      </div>
    </section>
  )
}
