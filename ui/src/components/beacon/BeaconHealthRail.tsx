import { AlertTriangle, CheckCircle2, Database, Globe, ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import type { BeaconHealthPayload } from '../../types/beacon'

interface Props {
  health: BeaconHealthPayload | null
  loading: boolean
  error: boolean
  isDark: boolean
}

export function BeaconHealthRail({ health, loading, error, isDark }: Props) {
  const gateway = health?.checks.gateway
  const quality = health?.checks.quality_canary
  const evidence = health?.checks.recent_evidence
  const metadata = gateway?.metadata ?? {}
  const providerOrder = metadataStringList(metadata, 'provider_order')
  const primaryProvider = metadataString(metadata, 'primary_provider')
  const usableProviders = metadataNumber(metadata, 'usable_provider_count')
  const warning = metadataString(metadata, 'provider_warning_status')
  const qualityMeta = quality?.metadata ?? {}
  const canaryPassed = metadataNumber(qualityMeta, 'passed')
  const canaryFailed = metadataNumber(qualityMeta, 'failed')
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-white/5' : 'bg-white/50'

  if (loading) {
    return <div className={`h-32 animate-pulse rounded-lg border ${border} ${panel}`} />
  }

  if (error || !health) {
    return (
      <div className={`rounded-lg border border-amber-500/35 p-4 text-sm text-amber-500 ${panel}`}>
        Beacon health unavailable
      </div>
    )
  }

  return (
    <aside className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <RailCard
        icon={<Globe className="h-4 w-4" />}
        label="Provider route"
        value={providerOrder.length ? providerOrder.join(' > ') : 'unknown'}
        detail={primaryProvider ? `primary ${primaryProvider}` : gateway?.detail ?? 'not checked'}
        tone={gateway?.status ?? 'unavailable'}
        isDark={isDark}
      />
      <RailCard
        icon={<ShieldCheck className="h-4 w-4" />}
        label="Redundancy"
        value={`${usableProviders ?? 0} usable`}
        detail={warning ? warning.replaceAll('_', ' ') : 'routing healthy'}
        tone={warning ? 'warning' : 'ok'}
        isDark={isDark}
      />
      <RailCard
        icon={<CheckCircle2 className="h-4 w-4" />}
        label="Answer eval"
        value={canaryPassed != null ? `${canaryPassed} passing` : quality?.status ?? 'unknown'}
        detail={canaryFailed ? `${canaryFailed} failures` : quality?.detail ?? 'quality canary clean'}
        tone={quality?.status ?? 'unavailable'}
        isDark={isDark}
      />
      <RailCard
        icon={<Database className="h-4 w-4" />}
        label="Evidence"
        value={evidence?.status ?? 'unknown'}
        detail={`retention ${health.retention.evidence_retention_days}d`}
        tone={evidence?.status ?? 'unavailable'}
        isDark={isDark}
      />
    </aside>
  )
}

interface RailCardProps {
  icon: ReactNode
  label: string
  value: string
  detail: string
  tone: string
  isDark: boolean
}

function RailCard({ icon, label, value, detail, tone, isDark }: RailCardProps) {
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const toneClass = tone === 'ok'
    ? 'text-emerald-500'
    : tone === 'warning'
      ? 'text-amber-500'
      : 'text-rose-500'
  return (
    <div className={`rounded-lg border p-4 ${border} ${isDark ? 'bg-white/5' : 'bg-white/50'}`}>
      <div className="flex items-center justify-between gap-3">
        <span className="text-[10px] font-mono uppercase tracking-widest opacity-45">{label}</span>
        <span className={toneClass}>{tone === 'ok' ? icon : <AlertTriangle className="h-4 w-4" />}</span>
      </div>
      <p className="mt-3 truncate text-sm font-semibold">{value}</p>
      <p className="mt-1 truncate text-xs opacity-55">{detail}</p>
    </div>
  )
}

function metadataString(metadata: Record<string, unknown>, key: string): string | null {
  const value = metadata[key]
  return typeof value === 'string' && value ? value : null
}

function metadataNumber(metadata: Record<string, unknown>, key: string): number | null {
  const value = metadata[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function metadataStringList(metadata: Record<string, unknown>, key: string): string[] {
  const value = metadata[key]
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}
