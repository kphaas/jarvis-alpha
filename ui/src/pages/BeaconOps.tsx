import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { motion } from 'framer-motion'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  DollarSign,
  Gauge,
  Globe2,
  MousePointerClick,
  Quote,
  RefreshCw,
  Server,
  ShieldCheck,
} from 'lucide-react'
import { apiJson } from '../lib/apiFetch'
import { useAppStore } from '../store'

interface HelmBeaconProviderSummary {
  status: string
  provider_order: string[]
  configured_provider_count: number
  usable_provider_count: number
  required_provider_count: number
  provider_redundancy_ok: boolean
  provider_redundancy_status: string
  missing_provider_count: number
  provider_warning_status: string | null
  primary_provider: string | null
  primary_provider_usable: boolean | null
  budget_capped_provider_count: number
  budget_capped_backup_provider_count: number
}

interface HelmBeaconBrowserSummary {
  status: string
  runtime: string
  runtime_enabled: boolean
  playwright_version: string | null
  expected_playwright_version: string | null
  playwright_version_ok: boolean
  screenshot_store_ready: boolean
  timeout_ms: number
  max_runs_per_hour: number
}

interface HelmBeaconEvidenceSummary {
  status: string
  window_hours: number
  total: number
  succeeded: number
  failed: number
  blocked: number
  last_request: {
    id: string | null
    requester: string | null
    selected_tool: string | null
    status: string | null
    created_at: string | null
    updated_at: string | null
  } | null
}

interface HelmBeaconLatencySummary {
  window_hours: number
  sample_count: number
  avg_ms: number
  p95_ms: number
  max_ms: number
  slo_target_ms: number
  slow_request_count: number
  slo_met_percent: number
}

interface HelmBeaconCostSummary {
  status: string
  mode: string
  exact_cost_available: boolean
  window_hours: number
  beacon_request_count: number
  budget_capped_provider_count: number
  budget_capped_backup_provider_count: number
  primary_provider: string | null
  primary_provider_usable: boolean | null
  provider_warning_status: string | null
  detail: string
}

interface HelmBeaconDataSourceItem {
  id: string
  name: string
  domain: string
  pricing: string
  auth_type: string
  api_base_url: string | null
  last_verified: string | null
  on_hold: boolean
}

interface HelmBeaconDataSourceSummary {
  registry: string
  active_count: number
  on_hold_count: number
  data_sources: HelmBeaconDataSourceItem[]
  on_hold_data_source_ids: string[]
}

interface HelmBeaconCitationQualitySummary {
  window_hours: number
  status: string
  supported: number
  weak: number
  insufficient: number
  supported_rate_percent: number
  official_source_count: number
  rejected_citation_count: number
  prompt_injection_rejection_count: number
}

interface HelmBeaconApprovalSummary {
  pending_browser_approvals: number
  next_expires_at: string | null
  window_hours: number
  approved_24h: number
  denied_24h: number
  executed_24h: number
  expired_24h: number
  highest_pending_risk_tier: string | null
}

interface HelmBeaconQualityCanarySummary {
  status: string
  case_count: number
  passed: number
  failed: number
  age_hours: number
  stale_after_hours: number
  alert: {
    status: string
    reason: string
    severity: string
  }
}

interface HelmBeaconSummary {
  status: string
  checked_at: string
  provider: HelmBeaconProviderSummary
  browser: HelmBeaconBrowserSummary
  evidence: HelmBeaconEvidenceSummary
  latency: HelmBeaconLatencySummary
  cost: HelmBeaconCostSummary
  citation_quality: HelmBeaconCitationQualitySummary
  approvals: HelmBeaconApprovalSummary
  quality_canary: HelmBeaconQualityCanarySummary
  data_sources: HelmBeaconDataSourceSummary
}

interface HelmSummaryPayload {
  generated_at: string
  beacon: HelmBeaconSummary
}

type Tone = 'ok' | 'warning' | 'degraded' | 'unknown'

export default function BeaconOps() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const divider = isDark ? 'divide-white/10' : 'divide-[#141414]/10'
  const panel = isDark ? 'bg-white/5' : 'bg-white/55'
  const muted = isDark ? 'text-zinc-400' : 'text-zinc-600'
  const [payload, setPayload] = useState<HelmSummaryPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    apiJson<HelmSummaryPayload>('/v1/helm/summary')
      .then(setPayload)
      .catch((err) => {
        setPayload(null)
        setError(err instanceof Error ? err.message : 'Beacon Ops unavailable')
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    let alive = true
    apiJson<HelmSummaryPayload>('/v1/helm/summary')
      .then((data) => {
        if (alive) setPayload(data)
      })
      .catch((err) => {
        if (!alive) return
        setPayload(null)
        setError(err instanceof Error ? err.message : 'Beacon Ops unavailable')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  const beacon = payload?.beacon ?? null
  const latencyTone = useMemo(() => latencyStatus(beacon?.latency), [beacon])
  const citationTone = useMemo(
    () => normalizeTone(beacon?.citation_quality.status),
    [beacon],
  )
  const providerTone = useMemo(
    () => normalizeTone(beacon?.provider.status),
    [beacon],
  )
  const costTone = useMemo(() => normalizeTone(beacon?.cost.status), [beacon])
  const browserTone = useMemo(
    () => approvalsStatus(beacon?.approvals, beacon?.browser),
    [beacon],
  )

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className="max-w-7xl space-y-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Beacon Ops</h1>
          <p className={`mt-1 text-[10px] font-mono uppercase tracking-widest ${muted}`}>
            SLO dashboard - answer engine
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm transition ${border} ${panel} disabled:opacity-45`}
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <section className={`rounded-lg border p-4 text-sm text-rose-500 ${border} ${panel}`}>
          {error}
        </section>
      )}

      {loading && !beacon ? (
        <LoadingGrid isDark={isDark} />
      ) : beacon ? (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <MetricCard
              icon={Clock3}
              label="Answer Latency"
              value={formatMs(beacon.latency.p95_ms)}
              detail={`p95 target ${formatMs(beacon.latency.slo_target_ms)}`}
              tone={latencyTone}
              isDark={isDark}
            />
            <MetricCard
              icon={Server}
              label="Provider State"
              value={beacon.provider.provider_redundancy_status.replace(/_/g, ' ')}
              detail={`${beacon.provider.usable_provider_count}/${beacon.provider.required_provider_count} usable`}
              tone={providerTone}
              isDark={isDark}
            />
            <MetricCard
              icon={DollarSign}
              label="Cost Guard"
              value={beacon.cost.status}
              detail={`${beacon.cost.budget_capped_provider_count} provider cap`}
              tone={costTone}
              isDark={isDark}
            />
            <MetricCard
              icon={Quote}
              label="Citation Quality"
              value={`${beacon.citation_quality.supported_rate_percent}%`}
              detail={`${beacon.citation_quality.official_source_count} official source`}
              tone={citationTone}
              isDark={isDark}
            />
            <MetricCard
              icon={MousePointerClick}
              label="Browser Approvals"
              value={`${beacon.approvals.pending_browser_approvals} pending`}
              detail={beacon.approvals.highest_pending_risk_tier ?? 'no risk queue'}
              tone={browserTone}
              isDark={isDark}
            />
          </section>

          <section className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
            <Panel title="Latency SLO" icon={Gauge} isDark={isDark}>
              <div className="grid gap-3 sm:grid-cols-4">
                <KeyValue label="Sample" value={String(beacon.latency.sample_count)} muted={muted} />
                <KeyValue label="Avg" value={formatMs(beacon.latency.avg_ms)} muted={muted} />
                <KeyValue label="P95" value={formatMs(beacon.latency.p95_ms)} muted={muted} />
                <KeyValue label="Max" value={formatMs(beacon.latency.max_ms)} muted={muted} />
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <KeyValue label="Met" value={`${beacon.latency.slo_met_percent}%`} muted={muted} />
                <KeyValue label="Slow" value={String(beacon.latency.slow_request_count)} muted={muted} />
                <KeyValue label="Window" value={`${beacon.latency.window_hours}h`} muted={muted} />
              </div>
            </Panel>

            <Panel title="Provider Route" icon={Globe2} isDark={isDark}>
              <div className="flex flex-wrap gap-2">
                {beacon.provider.provider_order.length > 0 ? (
                  beacon.provider.provider_order.map((provider) => (
                    <StatusPill
                      key={provider}
                      label={provider}
                      tone={provider === beacon.provider.primary_provider ? 'ok' : 'unknown'}
                      isDark={isDark}
                    />
                  ))
                ) : (
                  <span className={`text-sm ${muted}`}>No providers reported</span>
                )}
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <KeyValue label="Primary" value={beacon.provider.primary_provider ?? 'none'} muted={muted} />
                <KeyValue
                  label="Primary usable"
                  value={formatNullableBool(beacon.provider.primary_provider_usable)}
                  muted={muted}
                />
                <KeyValue label="Configured" value={String(beacon.provider.configured_provider_count)} muted={muted} />
                <KeyValue label="Missing" value={String(beacon.provider.missing_provider_count)} muted={muted} />
              </div>
            </Panel>
          </section>

          <Panel title="Data Sources" icon={Server} isDark={isDark}>
            <div className="grid gap-3 sm:grid-cols-4">
              <KeyValue label="Registry" value={beacon.data_sources.registry} muted={muted} />
              <KeyValue label="Active APIs" value={String(beacon.data_sources.active_count)} muted={muted} />
              <KeyValue label="On hold" value={String(beacon.data_sources.on_hold_count)} muted={muted} />
              <KeyValue
                label="Held IDs"
                value={
                  beacon.data_sources.on_hold_data_source_ids.length > 0
                    ? beacon.data_sources.on_hold_data_source_ids.join(', ')
                    : 'none'
                }
                muted={muted}
              />
            </div>
            <div className={`mt-4 divide-y ${divider}`}>
              {beacon.data_sources.data_sources.length > 0 ? (
                beacon.data_sources.data_sources.map((source) => (
                  <div
                    key={source.id}
                    className="grid gap-2 py-3 text-sm sm:grid-cols-[1.1fr_0.8fr_0.9fr_1.4fr]"
                  >
                    <div className="min-w-0">
                      <div className="truncate font-semibold">{source.name}</div>
                      <div className={`truncate font-mono text-[10px] uppercase tracking-widest ${muted}`}>
                        {source.id}
                      </div>
                    </div>
                    <KeyValue label="Domain" value={source.domain} muted={muted} />
                    <KeyValue label="Access" value={`${source.pricing} / ${source.auth_type}`} muted={muted} />
                    <KeyValue label="API" value={source.api_base_url ?? 'not listed'} muted={muted} />
                  </div>
                ))
              ) : (
                <div className={`py-3 text-sm ${muted}`}>No Beacon data sources reported</div>
              )}
            </div>
          </Panel>

          <section className="grid gap-4 xl:grid-cols-3">
            <Panel title="Cost Guard" icon={DollarSign} isDark={isDark}>
              <div className="space-y-3">
                <KeyValue label="Mode" value={beacon.cost.mode.replace(/_/g, ' ')} muted={muted} />
                <KeyValue label="Exact cost" value={beacon.cost.exact_cost_available ? 'available' : 'not recorded'} muted={muted} />
                <KeyValue label="Requests" value={String(beacon.cost.beacon_request_count)} muted={muted} />
                <KeyValue label="Backup caps" value={String(beacon.cost.budget_capped_backup_provider_count)} muted={muted} />
              </div>
            </Panel>

            <Panel title="Citation Quality" icon={Quote} isDark={isDark}>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                <KeyValue label="Supported" value={String(beacon.citation_quality.supported)} muted={muted} />
                <KeyValue label="Weak" value={String(beacon.citation_quality.weak)} muted={muted} />
                <KeyValue label="Insufficient" value={String(beacon.citation_quality.insufficient)} muted={muted} />
                <KeyValue label="Rejected risk" value={String(beacon.citation_quality.rejected_citation_count)} muted={muted} />
                <KeyValue label="Prompt-injection rejected" value={String(beacon.citation_quality.prompt_injection_rejection_count)} muted={muted} />
              </div>
            </Panel>

            <Panel title="Browser Approval Queue" icon={ShieldCheck} isDark={isDark}>
              <div className="space-y-3">
                <KeyValue label="Pending" value={String(beacon.approvals.pending_browser_approvals)} muted={muted} />
                <KeyValue label="Approved 24h" value={String(beacon.approvals.approved_24h)} muted={muted} />
                <KeyValue label="Executed 24h" value={String(beacon.approvals.executed_24h)} muted={muted} />
                <KeyValue label="Denied 24h" value={String(beacon.approvals.denied_24h)} muted={muted} />
                <KeyValue label="Next expiry" value={formatDateTime(beacon.approvals.next_expires_at)} muted={muted} />
              </div>
            </Panel>
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <Panel title="Browser Runtime" icon={MousePointerClick} isDark={isDark}>
              <div className="grid gap-3 sm:grid-cols-2">
                <KeyValue label="Runtime" value={beacon.browser.runtime} muted={muted} />
                <KeyValue label="Enabled" value={beacon.browser.runtime_enabled ? 'yes' : 'no'} muted={muted} />
                <KeyValue label="Playwright" value={beacon.browser.playwright_version ?? 'unknown'} muted={muted} />
                <KeyValue label="Version ok" value={beacon.browser.playwright_version_ok ? 'yes' : 'no'} muted={muted} />
                <KeyValue label="Screenshots" value={beacon.browser.screenshot_store_ready ? 'ready' : 'not ready'} muted={muted} />
                <KeyValue label="Cap" value={`${beacon.browser.max_runs_per_hour}/h`} muted={muted} />
              </div>
            </Panel>

            <Panel title="Evidence Window" icon={Activity} isDark={isDark}>
              <div className="grid gap-3 sm:grid-cols-2">
                <KeyValue label="Total" value={String(beacon.evidence.total)} muted={muted} />
                <KeyValue label="Succeeded" value={String(beacon.evidence.succeeded)} muted={muted} />
                <KeyValue label="Failed" value={String(beacon.evidence.failed)} muted={muted} />
                <KeyValue label="Blocked" value={String(beacon.evidence.blocked)} muted={muted} />
                <KeyValue label="Last requester" value={beacon.evidence.last_request?.requester ?? 'none'} muted={muted} />
                <KeyValue label="Last tool" value={beacon.evidence.last_request?.selected_tool ?? 'none'} muted={muted} />
              </div>
            </Panel>
          </section>

          <section className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
            <Panel title="Quality Canary" icon={CheckCircle2} isDark={isDark}>
              <div className="grid gap-3 sm:grid-cols-2">
                <KeyValue label="Status" value={beacon.quality_canary.status} muted={muted} />
                <KeyValue label="Cases" value={String(beacon.quality_canary.case_count)} muted={muted} />
                <KeyValue label="Passed" value={String(beacon.quality_canary.passed)} muted={muted} />
                <KeyValue label="Failed" value={String(beacon.quality_canary.failed)} muted={muted} />
                <KeyValue label="Age" value={`${beacon.quality_canary.age_hours}h`} muted={muted} />
                <KeyValue label="Alert" value={beacon.quality_canary.alert.reason.replace(/_/g, ' ')} muted={muted} />
              </div>
            </Panel>

            <Panel title="Operator Action" icon={AlertTriangle} isDark={isDark}>
              <div className="flex flex-wrap gap-2">
                {operatorActions(beacon).map((action) => (
                  <StatusPill key={action.label} label={action.label} tone={action.tone} isDark={isDark} />
                ))}
              </div>
              <div className={`mt-4 text-xs font-mono uppercase tracking-widest ${muted}`}>
                Checked {formatDateTime(beacon.checked_at)} - generated {formatDateTime(payload?.generated_at)}
              </div>
            </Panel>
          </section>
        </>
      ) : null}
    </motion.div>
  )
}

function LoadingGrid({ isDark }: { isDark: boolean }) {
  const block = isDark ? 'bg-white/5' : 'bg-[#141414]/5'
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
      {Array.from({ length: 5 }).map((_, index) => (
        <div key={index} className={`h-28 animate-pulse rounded-lg ${block}`} />
      ))}
    </div>
  )
}

function Panel({
  title,
  icon: Icon,
  children,
  isDark,
}: {
  title: string
  icon: typeof Activity
  children: ReactNode
  isDark: boolean
}) {
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-white/5' : 'bg-white/55'
  return (
    <section className={`rounded-lg border p-4 ${border} ${panel}`}>
      <div className="mb-4 flex items-center gap-2">
        <Icon className="h-4 w-4 opacity-70" />
        <h2 className="text-sm font-semibold uppercase tracking-wide">{title}</h2>
      </div>
      {children}
    </section>
  )
}

function MetricCard({
  icon: Icon,
  label,
  value,
  detail,
  tone,
  isDark,
}: {
  icon: typeof Activity
  label: string
  value: string
  detail: string
  tone: Tone
  isDark: boolean
}) {
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-white/5' : 'bg-white/55'
  return (
    <section className={`min-h-32 rounded-lg border p-4 ${border} ${panel}`}>
      <div className="flex items-start justify-between gap-3">
        <Icon className="h-5 w-5 opacity-70" />
        <StatusDot tone={tone} />
      </div>
      <div className="mt-5 min-w-0">
        <p className="text-[10px] font-mono uppercase tracking-widest opacity-55">{label}</p>
        <p className="mt-1 truncate text-2xl font-semibold capitalize">{value}</p>
        <p className="mt-1 truncate text-xs opacity-60">{detail}</p>
      </div>
    </section>
  )
}

function KeyValue({ label, value, muted }: { label: string; value: string; muted: string }) {
  return (
    <div className="min-w-0">
      <div className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>{label}</div>
      <div className="mt-1 truncate text-sm font-semibold">{value}</div>
    </div>
  )
}

function StatusPill({ label, tone, isDark }: { label: string; tone: Tone; isDark: boolean }) {
  return (
    <span
      className={`inline-flex min-h-8 items-center gap-2 rounded-lg border px-2.5 text-xs font-mono uppercase ${toneClass(tone, isDark)}`}
    >
      <StatusDot tone={tone} />
      {label}
    </span>
  )
}

function StatusDot({ tone }: { tone: Tone }) {
  const color = {
    ok: 'bg-emerald-500',
    warning: 'bg-amber-500',
    degraded: 'bg-rose-500',
    unknown: 'bg-zinc-500',
  }[tone]
  return <span className={`h-2 w-2 rounded-full ${color}`} />
}

function normalizeTone(status: string | undefined | null): Tone {
  if (!status) return 'unknown'
  if (status === 'ok' || status === 'passed' || status === 'mixed') return 'ok'
  if (status === 'warning' || status === 'stale') return 'warning'
  if (status === 'degraded' || status === 'failed' || status === 'unavailable') return 'degraded'
  return 'unknown'
}

function latencyStatus(latency: HelmBeaconLatencySummary | undefined): Tone {
  if (!latency || latency.sample_count === 0) return 'unknown'
  if (latency.slow_request_count > 0 || latency.p95_ms > latency.slo_target_ms) return 'warning'
  return 'ok'
}

function approvalsStatus(
  approvals: HelmBeaconApprovalSummary | undefined,
  browser: HelmBeaconBrowserSummary | undefined,
): Tone {
  if (!approvals || !browser) return 'unknown'
  if (!browser.runtime_enabled || browser.status === 'degraded') return 'warning'
  if (approvals.pending_browser_approvals > 0) return 'warning'
  return 'ok'
}

function toneClass(tone: Tone, isDark: boolean): string {
  if (tone === 'ok') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-500'
  if (tone === 'warning') return 'border-amber-500/30 bg-amber-500/10 text-amber-500'
  if (tone === 'degraded') return 'border-rose-500/30 bg-rose-500/10 text-rose-500'
  return isDark
    ? 'border-white/10 bg-white/5 text-zinc-400'
    : 'border-[#141414]/10 bg-[#141414]/5 text-zinc-600'
}

function operatorActions(beacon: HelmBeaconSummary): Array<{ label: string; tone: Tone }> {
  const actions: Array<{ label: string; tone: Tone }> = []
  if (latencyStatus(beacon.latency) === 'warning') actions.push({ label: 'Latency watch', tone: 'warning' })
  if (beacon.provider.usable_provider_count < beacon.provider.required_provider_count) {
    actions.push({ label: 'Provider redundancy', tone: 'warning' })
  }
  if (beacon.cost.budget_capped_backup_provider_count > 0) {
    actions.push({ label: 'Backup capped', tone: 'warning' })
  }
  if (beacon.citation_quality.insufficient > 0) actions.push({ label: 'Citation gaps', tone: 'warning' })
  if (beacon.approvals.pending_browser_approvals > 0) actions.push({ label: 'Review browser queue', tone: 'warning' })
  if (beacon.quality_canary.failed > 0) actions.push({ label: 'Canary failed', tone: 'degraded' })
  if (actions.length === 0) actions.push({ label: 'No immediate action', tone: 'ok' })
  return actions
}

function formatMs(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)}s`
  return `${value}ms`
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return 'none'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function formatNullableBool(value: boolean | null): string {
  if (value === null) return 'unknown'
  return value ? 'yes' : 'no'
}
