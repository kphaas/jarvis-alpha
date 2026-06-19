import { CheckCircle2, ExternalLink, ShieldCheck, XCircle } from 'lucide-react'
import type { BeaconEvidenceTransparency, BeaconEvidenceTransparencyItem } from '../../types/beacon'

interface Props {
  transparency?: BeaconEvidenceTransparency
  isDark: boolean
}

export function BeaconEvidenceTransparencyPanel({ transparency, isDark }: Props) {
  if (!transparency) return null

  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-white/5' : 'bg-white/50'
  const mutedPanel = isDark ? 'bg-black/20' : 'bg-white/40'
  const total = transparency.accepted_sources.length + transparency.rejected_sources.length

  return (
    <section className={`rounded-lg border p-4 ${border} ${panel}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Evidence transparency</p>
          <p className="mt-1 text-xs opacity-60">
            {transparency.accepted_sources.length} accepted · {transparency.rejected_sources.length} rejected · {total} reviewed
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <PolicyPill label="Official host" active={transparency.official_source_required} />
          <PolicyPill label="Freshness" active={transparency.freshness_required} />
        </div>
      </div>

      {transparency.required_source_hosts.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {transparency.required_source_hosts.slice(0, 6).map((host) => (
            <span key={host} className={`rounded border px-2 py-1 text-[10px] font-mono uppercase opacity-65 ${border}`}>
              {host}
            </span>
          ))}
        </div>
      )}

      <div className="mt-4 grid gap-3 xl:grid-cols-2">
        <EvidenceBucket
          title="Accepted evidence"
          empty="No accepted evidence."
          items={transparency.accepted_sources}
          border={border}
          panel={mutedPanel}
          accepted
        />
        <EvidenceBucket
          title="Rejected evidence"
          empty="No rejected evidence."
          items={transparency.rejected_sources}
          border={border}
          panel={mutedPanel}
        />
      </div>
    </section>
  )
}

function EvidenceBucket({
  title,
  empty,
  items,
  border,
  panel,
  accepted = false,
}: {
  title: string
  empty: string
  items: BeaconEvidenceTransparencyItem[]
  border: string
  panel: string
  accepted?: boolean
}) {
  const Icon = accepted ? CheckCircle2 : XCircle
  const iconTone = accepted ? 'text-emerald-500' : 'text-rose-500'

  return (
    <div className={`rounded-lg border p-3 ${border} ${panel}`}>
      <div className="flex items-center gap-2">
        <Icon className={`h-4 w-4 ${iconTone}`} />
        <h2 className="text-sm font-semibold">{title}</h2>
      </div>
      {items.length === 0 && <p className="mt-3 text-xs opacity-55">{empty}</p>}
      <div className="mt-3 space-y-3">
        {items.slice(0, 5).map((item, index) => (
          <EvidenceRow key={`${item.content_hash}-${item.source_url}-${index}`} item={item} border={border} accepted={accepted} />
        ))}
      </div>
    </div>
  )
}

function EvidenceRow({
  item,
  border,
  accepted,
}: {
  item: BeaconEvidenceTransparencyItem
  border: string
  accepted: boolean
}) {
  return (
    <article className={`rounded-lg border p-3 ${border}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap gap-2">
            <SourcePill label={item.source_quality.replaceAll('_', ' ')} />
            <SourcePill label={`${item.confidence} · ${item.source_score}`} />
            {accepted && item.source_rank && <SourcePill label={`rank ${item.source_rank}`} />}
          </div>
          <p className="mt-2 truncate text-sm font-semibold">{item.host}</p>
        </div>
        <a
          href={item.source_url}
          target="_blank"
          rel="noreferrer"
          className={`rounded-lg border p-2 transition hover:opacity-75 ${border}`}
          aria-label={`Open ${item.host}`}
        >
          <ExternalLink className="h-4 w-4" />
        </a>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        <Decision label="Official" value={officialLabel(item)} tone={officialTone(item)} />
        <Decision label="Claim" value={claimLabel(item)} tone={item.claim_supported ? 'good' : 'bad'} />
        <Decision label="Freshness" value={freshnessLabel(item)} tone={item.freshness_required ? 'warn' : 'neutral'} />
      </div>

      {!accepted && item.rejection_reasons.length > 0 && (
        <ReasonList title="Rejected because" reasons={item.rejection_reasons} />
      )}
      {!item.claim_supported && item.claim_support_reasons.length > 0 && (
        <ReasonList title="Claim support" reasons={item.claim_support_reasons.map((reason) => `claim_support:${reason}`)} />
      )}
      {item.quality_reasons.length > 0 && (
        <ReasonList title="Quality" reasons={item.quality_reasons.slice(0, 4)} muted />
      )}
    </article>
  )
}

function Decision({ label, value, tone }: { label: string; value: string; tone: 'good' | 'warn' | 'bad' | 'neutral' }) {
  const toneClass = {
    good: 'text-emerald-500',
    warn: 'text-amber-500',
    bad: 'text-rose-500',
    neutral: 'opacity-70',
  }[tone]
  return (
    <div>
      <p className="text-[10px] font-mono uppercase tracking-widest opacity-40">{label}</p>
      <p className={`mt-1 text-xs font-medium ${toneClass}`}>{value}</p>
    </div>
  )
}

function ReasonList({ title, reasons, muted = false }: { title: string; reasons: string[]; muted?: boolean }) {
  return (
    <div className="mt-3">
      <p className="text-[10px] font-mono uppercase tracking-widest opacity-40">{title}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {reasons.slice(0, 6).map((reason) => (
          <span key={reason} className={`inline-flex items-center gap-1 rounded border border-white/10 px-2 py-1 text-xs ${muted ? 'opacity-55' : 'opacity-75'}`}>
            <ShieldCheck className="h-3 w-3" />
            {humanReason(reason)}
          </span>
        ))}
      </div>
    </div>
  )
}

function PolicyPill({ label, active }: { label: string; active: boolean }) {
  const tone = active ? 'border-amber-500/30 text-amber-500' : 'border-white/10 opacity-55'
  return (
    <span className={`rounded border px-2 py-1 text-[10px] font-mono uppercase tracking-widest ${tone}`}>
      {label}: {active ? 'required' : 'optional'}
    </span>
  )
}

function SourcePill({ label }: { label: string }) {
  return (
    <span className="rounded border border-white/10 px-2 py-1 text-[10px] font-mono uppercase opacity-65">
      {label}
    </span>
  )
}

function officialLabel(item: BeaconEvidenceTransparencyItem) {
  if (!item.official_source_required) return 'Not required'
  return item.official_host_match ? 'Matched' : 'Mismatch'
}

function officialTone(item: BeaconEvidenceTransparencyItem): 'good' | 'warn' | 'bad' | 'neutral' {
  if (!item.official_source_required) return 'neutral'
  return item.official_host_match ? 'good' : 'bad'
}

function claimLabel(item: BeaconEvidenceTransparencyItem) {
  return item.claim_supported ? 'Supported' : 'Unsupported'
}

function freshnessLabel(item: BeaconEvidenceTransparencyItem) {
  const fetched = formatTimestamp(item.fetched_at)
  if (item.freshness_required) return fetched ? `Required · ${fetched}` : 'Required'
  return fetched || 'Optional'
}

function formatTimestamp(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function humanReason(reason: string) {
  return reason.replaceAll(':', ': ').replaceAll('_', ' ')
}
