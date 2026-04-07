import { ArrowLeft, FileText } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { useBriefingByBatchRunId, useTheme } from '../hooks'
import { formatRelativeTime } from '../lib/time'

function outcomeBadgeClass(outcome: string): string {
  const value = outcome.toLowerCase()
  if (value === 'pass' || value === 'ok') return 'border-emerald-500/30 text-emerald-500'
  if (value === 'fail' || value === 'error') return 'border-rose-500/30 text-rose-500'
  if (value === 'skip' || value === 'pending') return 'border-amber-500/30 text-amber-500'
  return 'border-white/20 opacity-70'
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const rem = seconds % 60
  return rem === 0 ? `${minutes}m` : `${minutes}m ${rem}s`
}

export default function BriefingDetail() {
  const navigate = useNavigate()
  const { batchRunId } = useParams<{ batchRunId: string }>()
  const { border, subtle, muted, isDark } = useTheme()
  const { data: briefing, isLoading, error } = useBriefingByBatchRunId(batchRunId)

  const panel = isDark ? 'bg-[#0F0F0F]' : 'bg-white'
  const rowEven = isDark ? 'bg-white/[0.03]' : 'bg-zinc-50/80'

  return (
    <div className="space-y-6 max-w-6xl">
      <section>
        <div className={`p-4 rounded-2xl border ${border} ${subtle} space-y-3`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => navigate('/')}
              className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-mono ${border} hover:opacity-90 transition-opacity`}
            >
              <ArrowLeft className="w-4 h-4" />
              Briefings
            </button>
            <div className="flex items-center gap-2">
              <FileText className="w-3.5 h-3.5 opacity-40" />
              <span className={`text-xs font-mono uppercase ${muted}`}>Briefing Detail</span>
            </div>
          </div>

          {isLoading && <p className="text-sm opacity-40">Loading...</p>}
          {!isLoading && error && <p className="text-xs text-rose-500">Failed to load</p>}
          {!isLoading && !error && briefing === null && <p className="text-sm opacity-40">No data yet</p>}
          {!isLoading && !error && briefing && (
            <div className="space-y-6">
              <div className="flex flex-wrap items-center gap-3">
                <span className={`text-xs font-mono font-bold uppercase px-2 py-1 rounded-md border ${border}`}>
                  {briefing.source.toUpperCase()}
                </span>
                <span className="text-xs font-mono opacity-70">{briefing.batch_run_id}</span>
                <span className="text-sm opacity-70">{formatRelativeTime(briefing.started_at)}</span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                <div className={`p-4 rounded-2xl border ${border} ${subtle}`}>
                  <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-2">Pass</p>
                  <p className="text-xl font-bold text-emerald-500">{briefing.summary.pass}</p>
                </div>
                <div className={`p-4 rounded-2xl border ${border} ${subtle}`}>
                  <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-2">Fail</p>
                  <p className="text-xl font-bold text-rose-500">{briefing.summary.fail}</p>
                </div>
                <div className={`p-4 rounded-2xl border ${border} ${subtle}`}>
                  <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-2">Skip</p>
                  <p className="text-xl font-bold text-amber-500">{briefing.summary.skip}</p>
                </div>
                <div className={`p-4 rounded-2xl border ${border} ${subtle}`}>
                  <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-2">Total Cost</p>
                  <p className="text-sm font-bold">
                    ${briefing.summary.total_cost_usd.toFixed(2)}{' '}
                    <span className="opacity-40">of ${(briefing.summary.per_batch_usd ?? 0).toFixed(2)}</span>
                  </p>
                </div>
              </div>

              <section>
                <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">Per-Feature Results</p>
                <div className={`overflow-hidden rounded-xl border ${border} ${panel}`}>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[920px] border-collapse text-left text-sm">
                      <thead>
                        <tr className={`border-b ${border} ${isDark ? 'bg-black/20' : 'bg-zinc-100'}`}>
                          <th className={`px-3 py-2.5 text-[10px] font-mono uppercase tracking-wider ${muted}`}>Feature ID</th>
                          <th className={`px-3 py-2.5 text-[10px] font-mono uppercase tracking-wider ${muted}`}>Outcome</th>
                          <th className={`px-3 py-2.5 text-[10px] font-mono uppercase tracking-wider ${muted}`}>Cost</th>
                          <th className={`px-3 py-2.5 text-[10px] font-mono uppercase tracking-wider ${muted}`}>Iterations Used / Max</th>
                          <th className={`px-3 py-2.5 text-[10px] font-mono uppercase tracking-wider ${muted}`}>Duration</th>
                        </tr>
                      </thead>
                      <tbody>
                        {briefing.results.length === 0 ? (
                          <tr>
                            <td colSpan={5} className={`px-4 py-12 text-center ${muted}`}>
                              No results yet
                            </td>
                          </tr>
                        ) : (
                          briefing.results.map((result, idx) => (
                            <tr key={`${result.feature_id}-${idx}`} className={`border-b ${border} ${idx % 2 === 1 ? rowEven : ''}`}>
                              <td className="px-3 py-2 font-mono text-xs">{result.feature_id}</td>
                              <td className="px-3 py-2">
                                <span className={`text-xs font-mono font-bold uppercase px-2 py-1 rounded-md border ${outcomeBadgeClass(result.outcome)}`}>
                                  {result.outcome_display}
                                </span>
                              </td>
                              <td className="px-3 py-2 font-mono text-xs">${result.cost_usd.toFixed(2)}</td>
                              <td className="px-3 py-2 font-mono text-xs">
                                {result.iterations_used} / {result.iterations_max ?? '—'}
                              </td>
                              <td className="px-3 py-2 font-mono text-xs">{formatDuration(result.duration_seconds)}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </section>

              <section>
                <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">Briefing Markdown</p>
                <div className={`p-4 rounded-2xl border ${border} ${subtle}`}>
                  {briefing.markdown ? (
                    <pre className="text-xs font-mono whitespace-pre-wrap break-words">{briefing.markdown}</pre>
                  ) : (
                    <p className="text-sm opacity-40">No briefing markdown available</p>
                  )}
                </div>
              </section>

              <p className={`text-[10px] font-mono ${muted}`}>Created at {new Date(briefing.created_at).toLocaleString()}</p>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
