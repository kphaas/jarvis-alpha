import { ArrowRight, FileText, RefreshCw } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useLatestBriefing, useTheme } from '../hooks'
import { formatRelativeTime } from '../lib/time'

function formatMoney(value: number | undefined): string {
  return `$${(value ?? 0).toFixed(2)}`
}

export default function Briefing() {
  const navigate = useNavigate()
  const { border, subtle, muted, isDark } = useTheme()
  const { data: briefing, isLoading, error, refetch, isFetching } = useLatestBriefing()
  const panel = isDark ? 'bg-[#0F0F0F]' : 'bg-white'

  return (
    <div className="space-y-6 max-w-5xl">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-serif italic text-3xl">Briefing</h1>
          <p className="text-[10px] font-mono uppercase opacity-50 mt-1">Latest overnight summary</p>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 py-2 text-xs font-mono ${border} hover:opacity-90 transition-opacity`}
        >
          <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      <section className={`p-4 rounded-2xl border ${border} ${subtle}`}>
        <div className="flex items-center gap-2 mb-4">
          <FileText className="w-4 h-4 opacity-40" />
          <p className={`text-xs font-mono uppercase ${muted}`}>Current Briefing</p>
        </div>

        {isLoading && <div className={`h-28 rounded-xl animate-pulse ${isDark ? 'bg-white/5' : 'bg-[#141414]/5'}`} />}
        {!isLoading && error && <p className="text-sm text-rose-500">Failed to load briefing</p>}
        {!isLoading && !error && briefing === null && <p className="text-sm opacity-40">No briefings yet</p>}
        {!isLoading && !error && briefing && (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-3">
              <span className={`text-xs font-mono font-bold uppercase px-2 py-1 rounded-md border ${border}`}>
                {briefing.source}
              </span>
              <span className="text-xs font-mono opacity-70">{briefing.batch_run_id}</span>
              <span className="text-sm opacity-70">{formatRelativeTime(briefing.started_at)}</span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
              <div className={`p-4 rounded-2xl border ${border} ${panel}`}>
                <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-2">Pass</p>
                <p className="text-xl font-bold text-emerald-500">{briefing.summary.pass}</p>
              </div>
              <div className={`p-4 rounded-2xl border ${border} ${panel}`}>
                <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-2">Fail</p>
                <p className="text-xl font-bold text-rose-500">{briefing.summary.fail}</p>
              </div>
              <div className={`p-4 rounded-2xl border ${border} ${panel}`}>
                <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-2">Skip</p>
                <p className="text-xl font-bold text-amber-500">{briefing.summary.skip}</p>
              </div>
              <div className={`p-4 rounded-2xl border ${border} ${panel}`}>
                <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-2">Cost</p>
                <p className="text-sm font-bold">
                  {formatMoney(briefing.summary.total_cost_usd)}{' '}
                  <span className="opacity-40">of {formatMoney(briefing.summary.per_batch_usd)}</span>
                </p>
              </div>
            </div>

            <div className={`p-4 rounded-2xl border ${border} ${panel}`}>
              {briefing.markdown ? (
                <pre className="text-xs font-mono whitespace-pre-wrap break-words max-h-[420px] overflow-auto">{briefing.markdown}</pre>
              ) : (
                <p className="text-sm opacity-40">No briefing markdown available</p>
              )}
            </div>

            <button
              type="button"
              onClick={() => navigate(`/briefings/${briefing.batch_run_id}`)}
              className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 py-2 text-xs font-mono ${border} hover:opacity-90 transition-opacity`}
            >
              Open Detail
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        )}
      </section>
    </div>
  )
}
