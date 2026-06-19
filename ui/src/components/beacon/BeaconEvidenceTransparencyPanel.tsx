import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  ExternalLink,
  Layers3,
  ShieldCheck,
  XCircle,
} from 'lucide-react'
import type { BeaconEvidenceTransparency, BeaconEvidenceTransparencyItem } from '../../types/beacon'

interface Props {
  transparency?: BeaconEvidenceTransparency
  isDark: boolean
}

type TrustTone = 'good' | 'warn' | 'bad' | 'neutral'

interface TrustChip {
  label: string
  detail: string
  tone: TrustTone
  icon: 'check' | 'warn' | 'clock' | 'layers'
}

export function BeaconEvidenceTransparencyPanel({ transparency, isDark }: Props) {
  if (!transparency) return null

  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-white/5' : 'bg-white/50'
  const mutedPanel = isDark ? 'bg-black/20' : 'bg-white/40'
  const total = transparency.accepted_sources.length + transparency.rejected_sources.length
  const trustChips = buildTrustChips(transparency)

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

      <div className="mt-4">
        <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Why this answer is trustworthy</p>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
          {trustChips.map((chip) => (
            <TrustSummaryChip key={`${chip.label}-${chip.detail}`} chip={chip} border={border} />
          ))}
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
        {groupEvidence(items).slice(0, 6).map((group) => (
          <EvidenceGroup key={group.key} group={group} border={border} accepted={accepted} />
        ))}
      </div>
    </div>
  )
}

function TrustSummaryChip({ chip, border }: { chip: TrustChip; border: string }) {
  const Icon = {
    check: CheckCircle2,
    warn: AlertTriangle,
    clock: Clock3,
    layers: Layers3,
  }[chip.icon]
  const toneClass = {
    good: 'border-emerald-500/30 text-emerald-500',
    warn: 'border-amber-500/30 text-amber-500',
    bad: 'border-rose-500/30 text-rose-500',
    neutral: 'border-white/10 opacity-70',
  }[chip.tone]

  return (
    <div className={`rounded-lg border p-3 ${border}`}>
      <div className={`flex items-center gap-2 ${toneClass}`}>
        <Icon className="h-4 w-4 shrink-0" />
        <p className="truncate text-xs font-semibold">{chip.label}</p>
      </div>
      <p className="mt-1 text-xs leading-5 opacity-60">{chip.detail}</p>
    </div>
  )
}

function EvidenceGroup({
  group,
  border,
  accepted,
}: {
  group: EvidenceGroupModel
  border: string
  accepted: boolean
}) {
  return (
    <div className={`rounded-lg border p-3 ${border}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{group.host}</p>
          <p className="mt-1 text-[10px] font-mono uppercase tracking-widest opacity-45">
            {group.items.length} source{group.items.length === 1 ? '' : 's'} grouped
          </p>
        </div>
        <SourcePill label={group.quality.replaceAll('_', ' ')} />
      </div>
      <div className="mt-3 space-y-3">
        {group.items.slice(0, 4).map((item, index) => (
          <EvidenceRow
            key={`${item.content_hash}-${item.source_url}-${index}`}
            item={item}
            border={border}
            accepted={accepted}
          />
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

interface EvidenceGroupModel {
  key: string
  host: string
  quality: string
  items: BeaconEvidenceTransparencyItem[]
}

function groupEvidence(items: BeaconEvidenceTransparencyItem[]): EvidenceGroupModel[] {
  const grouped = new Map<string, EvidenceGroupModel>()
  for (const item of items) {
    const key = `${item.host}|${item.source_quality}`
    const existing = grouped.get(key)
    if (existing) {
      existing.items.push(item)
      continue
    }
    grouped.set(key, {
      key,
      host: item.host,
      quality: item.source_quality,
      items: [item],
    })
  }
  return Array.from(grouped.values()).sort((left, right) => {
    if (right.items.length !== left.items.length) return right.items.length - left.items.length
    return left.host.localeCompare(right.host)
  })
}

function buildTrustChips(transparency: BeaconEvidenceTransparency): TrustChip[] {
  const accepted = transparency.accepted_sources
  const rejected = transparency.rejected_sources
  const acceptedOfficialMatches = accepted.filter(
    (item) => item.official_host_match,
  ).length
  const unsupportedBlocked = rejected.filter((item) => !item.claim_supported).length
  const acceptedWithFetchedAt = accepted.filter((item) =>
    Boolean(item.fetched_at),
  ).length

  return [
    {
      label: accepted.length ? 'Evidence accepted' : 'No accepted evidence',
      detail: accepted.length
        ? `${accepted.length} cited source${accepted.length === 1 ? '' : 's'} can support the answer.`
        : 'Beacon will not present this as verified.',
      tone: accepted.length ? 'good' : 'bad',
      icon: accepted.length ? 'check' : 'warn',
    },
    {
      label: officialChipLabel(transparency, acceptedOfficialMatches),
      detail: officialChipDetail(transparency, acceptedOfficialMatches),
      tone: officialChipTone(transparency, acceptedOfficialMatches),
      icon: 'check',
    },
    {
      label: unsupportedBlocked ? 'Unsupported blocked' : 'Claims supported',
      detail: unsupportedBlocked
        ? `${unsupportedBlocked} claim${unsupportedBlocked === 1 ? '' : 's'} failed support checks and stayed out.`
        : 'Accepted claims passed citation-support checks.',
      tone: unsupportedBlocked ? 'warn' : 'good',
      icon: unsupportedBlocked ? 'warn' : 'check',
    },
    {
      label: freshnessChipLabel(transparency, acceptedWithFetchedAt),
      detail: freshnessChipDetail(transparency, acceptedWithFetchedAt),
      tone: freshnessChipTone(transparency, acceptedWithFetchedAt),
      icon: 'clock',
    },
    {
      label: rejected.length ? 'Rejections visible' : 'No rejected sources',
      detail: rejected.length
        ? `${rejected.length} rejected source${rejected.length === 1 ? '' : 's'} grouped with reasons.`
        : 'No source was excluded by the quality filter.',
      tone: rejected.length ? 'warn' : 'good',
      icon: rejected.length ? 'layers' : 'check',
    },
  ]
}

function officialChipLabel(transparency: BeaconEvidenceTransparency, matchCount: number) {
  if (!transparency.official_source_required) return 'Official optional'
  return matchCount ? 'Official matched' : 'Official missing'
}

function officialChipDetail(transparency: BeaconEvidenceTransparency, matchCount: number) {
  if (!transparency.official_source_required) return 'This query did not require an official host.'
  if (matchCount) {
    return `${matchCount} accepted source${matchCount === 1 ? '' : 's'} matched required hosts.`
  }
  return 'Required official hosts did not pass the quality filter.'
}

function officialChipTone(transparency: BeaconEvidenceTransparency, matchCount: number): TrustTone {
  if (!transparency.official_source_required) return 'neutral'
  return matchCount ? 'good' : 'bad'
}

function freshnessChipLabel(transparency: BeaconEvidenceTransparency, fetchedCount: number) {
  if (!transparency.freshness_required) return 'Freshness optional'
  return fetchedCount ? 'Freshness checked' : 'Freshness missing'
}

function freshnessChipDetail(transparency: BeaconEvidenceTransparency, fetchedCount: number) {
  if (!transparency.freshness_required) return 'The research plan did not require current evidence.'
  if (fetchedCount) {
    return `${fetchedCount} accepted source${fetchedCount === 1 ? '' : 's'} include fetch time.`
  }
  return 'No accepted source included a fetch timestamp.'
}

function freshnessChipTone(transparency: BeaconEvidenceTransparency, fetchedCount: number): TrustTone {
  if (!transparency.freshness_required) return 'neutral'
  return fetchedCount ? 'good' : 'warn'
}
