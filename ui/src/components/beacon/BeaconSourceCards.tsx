import { ExternalLink, ShieldCheck } from 'lucide-react'
import type { BeaconCitation, BeaconQualitySummary } from '../../types/beacon'

interface Props {
  citations: BeaconCitation[]
  quality: BeaconQualitySummary
  isDark: boolean
}

export function BeaconSourceCards({ citations, quality, isDark }: Props) {
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-white/5' : 'bg-white/50'

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Sources</p>
          <p className="mt-1 text-xs opacity-55">
            {quality.accepted_citation_count} accepted · {quality.rejected_citation_count} rejected
          </p>
        </div>
        <QualityPill status={quality.status} />
      </div>

      {citations.length === 0 && (
        <div className={`rounded-lg border p-4 text-sm opacity-60 ${border} ${panel}`}>
          No accepted citations returned.
        </div>
      )}

      <div className="grid gap-3 xl:grid-cols-2">
        {citations.map((citation, index) => (
          <article key={`${citation.content_hash}-${index}`} className={`rounded-lg border p-4 ${border} ${panel}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded border border-emerald-500/30 px-2 py-1 text-[10px] font-mono uppercase text-emerald-500">
                    #{citation.source_rank ?? index + 1}
                  </span>
                  <span className="rounded border border-cyan-500/30 px-2 py-1 text-[10px] font-mono uppercase text-cyan-500">
                    {citation.source_quality.replaceAll('_', ' ')}
                  </span>
                  <span className="rounded border border-white/10 px-2 py-1 text-[10px] font-mono uppercase opacity-65">
                    {citation.confidence} · {citation.source_score}
                  </span>
                </div>
                <p className="mt-3 truncate text-sm font-semibold">{citation.host}</p>
              </div>
              <a
                href={citation.source_url}
                target="_blank"
                rel="noreferrer"
                className={`rounded-lg border p-2 transition ${border} ${isDark ? 'hover:bg-white/10' : 'hover:bg-white/70'}`}
                aria-label={`Open ${citation.host}`}
              >
                <ExternalLink className="h-4 w-4" />
              </a>
            </div>

            <p className="mt-3 line-clamp-4 text-sm leading-6 opacity-80">{citation.citation_text}</p>

            {citation.quality_reasons.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {citation.quality_reasons.slice(0, 4).map((reason) => (
                  <span key={reason} className="inline-flex items-center gap-1 rounded border border-white/10 px-2 py-1 text-xs opacity-65">
                    <ShieldCheck className="h-3 w-3" />
                    {reason.replaceAll('_', ' ')}
                  </span>
                ))}
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  )
}

function QualityPill({ status }: { status: BeaconQualitySummary['status'] }) {
  const tone = status === 'supported'
    ? 'border-emerald-500/30 text-emerald-500'
    : status === 'weak'
      ? 'border-amber-500/30 text-amber-500'
      : 'border-rose-500/30 text-rose-500'
  return (
    <span className={`rounded border px-2 py-1 text-[10px] font-mono uppercase tracking-widest ${tone}`}>
      {status}
    </span>
  )
}
