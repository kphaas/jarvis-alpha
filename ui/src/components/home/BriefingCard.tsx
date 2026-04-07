import { FileText } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useLatestBriefing } from '../../hooks'
import { formatRelativeTime } from '../../lib/time'

interface BriefingCardProps {
  border: string
  subtle: string
}

export function BriefingCard({ border, subtle }: BriefingCardProps) {
  const navigate = useNavigate()
  const { data: latestBriefing, isLoading, error } = useLatestBriefing()

  return (
    <section>
      <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">Last Briefing</p>
      <div className={`p-4 rounded-2xl border ${border} ${subtle}`}>
        <div className="flex items-center gap-2 mb-3">
          <FileText className="w-3.5 h-3.5 opacity-40" />
          <p className="text-[10px] font-mono uppercase opacity-40">Latest run summary</p>
        </div>
        {isLoading && <p className="text-sm opacity-40">Loading...</p>}
        {!isLoading && error && <p className="text-xs text-rose-500">Failed to load</p>}
        {!isLoading && !error && latestBriefing === null && <p className="text-sm opacity-40">No briefings yet</p>}
        {!isLoading && !error && latestBriefing && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className={`text-xs font-mono font-bold px-2 py-1 rounded-md border ${border}`}>
                {latestBriefing.source.toUpperCase()}
              </span>
              <span className="text-sm opacity-70">{formatRelativeTime(latestBriefing.started_at)}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-mono font-bold px-2 py-1 rounded-md border border-emerald-500/30 text-emerald-500">
                pass {latestBriefing.summary.pass}
              </span>
              <span className="text-xs font-mono font-bold px-2 py-1 rounded-md border border-rose-500/30 text-rose-500">
                fail {latestBriefing.summary.fail}
              </span>
              <span className="text-xs font-mono font-bold px-2 py-1 rounded-md border border-amber-500/30 text-amber-500">
                skip {latestBriefing.summary.skip}
              </span>
            </div>
            <p className="text-sm">
              ${latestBriefing.summary.total_cost_usd.toFixed(2)}{' '}
              <span className="opacity-40">of ${(latestBriefing.summary.per_batch_usd ?? 0).toFixed(2)} budget</span>
            </p>
            <button
              type="button"
              onClick={() => navigate(`/briefings/${latestBriefing.batch_run_id}`)}
              disabled={!latestBriefing}
              className="text-sm font-mono opacity-70 hover:opacity-100 transition-opacity disabled:opacity-40"
            >
              View full briefing →
            </button>
          </div>
        )}
      </div>
    </section>
  )
}
