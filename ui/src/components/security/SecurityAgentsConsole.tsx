import {
  Activity,
  AlertTriangle,
  CheckCircle,
  Clock,
  Database,
  Eye,
  FileText,
  KeyRound,
  ListChecks,
  Radio,
  ShieldCheck,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import type {
  PorchlightCheck,
  PorchlightReport,
  SecurityAgentEvent,
  WardenAgent,
  WardenStatus,
} from '../../types/security'
import {
  SectionSkeleton,
  SectionUnavailable,
  relativeAccessedLabel,
  type SecurityThemeProps,
} from './utils'

interface SecurityAgentsConsoleProps extends SecurityThemeProps {
  wardenStatus: WardenStatus | null
  porchlightReport: PorchlightReport | null
  agentEvents: SecurityAgentEvent[]
  loadWarden: boolean
  loadPorchlight: boolean
  errWarden: boolean
  errPorchlight: boolean
  onSelectTab: (tab: string) => void
}

type ConsoleStatus = 'pass' | 'warn' | 'fail' | 'unavailable'

interface CoverageLane {
  id: string
  title: string
  detail: string
  tab: string
  icon: LucideIcon
  agents: string[]
  checks: string[]
}

const EXPECTED_PORCHLIGHT_CHECKS = 20
const PORCHLIGHT_STALE_AFTER_HOURS = 30

const coverageLanes: CoverageLane[] = [
  {
    id: 'detect',
    title: 'Detection',
    detail: 'Malware patterns, runtime exposure, honeypot and data-boundary signals.',
    tab: 'Porchlight',
    icon: Activity,
    agents: ['porchlight', 'tripwire', 'sentry'],
    checks: ['code_malware_scan', 'runtime_exposure'],
  },
  {
    id: 'exposure',
    title: 'Exposure',
    detail: 'Repo freshness, dependencies, TLS, Cloudflare, and public surface drift.',
    tab: 'Sweep',
    icon: Radio,
    agents: ['sweep', 'porchlight'],
    checks: [
      'malware_scan_repo_freshness',
      'dependency_cve_scan',
      'cloudflare_access',
      'cloudflare_access_policy_drift',
      'sweep_tls_report_intake',
    ],
  },
  {
    id: 'identity',
    title: 'Identity',
    detail: 'RLS, Postgres role posture, token rotation, and live secret verification.',
    tab: 'Identity',
    icon: KeyRound,
    agents: ['porchlight', 'keyturner'],
    checks: [
      'database_rls',
      'postgres_role_safety',
      'postgres_hba_safety',
      'secret_rotation',
      'secret_live_verification',
      'token_rotation_logs',
    ],
  },
  {
    id: 'integrity',
    title: 'Integrity',
    detail: 'Critical file hashes, backups, branch protection, and DB route review.',
    tab: 'Ledger',
    icon: Database,
    agents: ['ledger', 'porchlight'],
    checks: [
      'host_integrity',
      'backup_recovery',
      'github_branch_protection_drift',
      'route_db_access_review',
    ],
  },
  {
    id: 'response',
    title: 'Response',
    detail: 'Warden routing, ticket candidates, approvals, and event notifications.',
    tab: 'Warden',
    icon: ListChecks,
    agents: ['warden'],
    checks: [],
  },
]

function statusClass(status: ConsoleStatus, isDark: boolean): string {
  if (status === 'pass') {
    return isDark
      ? 'border-emerald-400/25 bg-emerald-500/10 text-emerald-200'
      : 'border-emerald-500/30 bg-emerald-50 text-emerald-800'
  }
  if (status === 'warn') {
    return isDark
      ? 'border-amber-400/30 bg-amber-500/10 text-amber-200'
      : 'border-amber-500/35 bg-amber-50 text-amber-800'
  }
  if (status === 'fail') {
    return isDark
      ? 'border-rose-400/30 bg-rose-500/10 text-rose-200'
      : 'border-rose-500/35 bg-rose-50 text-rose-800'
  }
  return isDark
    ? 'border-white/10 bg-white/5 text-white/45'
    : 'border-[#141414]/10 bg-[#141414]/5 text-[#141414]/55'
}

function statusIcon(status: ConsoleStatus): LucideIcon {
  if (status === 'pass') return CheckCircle
  if (status === 'fail') return XCircle
  return AlertTriangle
}

function tabForAgent(agentId: string): string {
  if (agentId === 'porchlight') return 'Porchlight'
  if (agentId === 'keyturner') return 'Keyturner'
  if (agentId === 'sweep' || agentId === 'network_watchdog') return 'Sweep'
  if (agentId === 'tripwire') return 'Tripwire'
  if (agentId === 'sentry') return 'Sentry'
  if (agentId === 'trade_guard') return 'Trade Guard'
  if (agentId === 'ledger') return 'Ledger'
  if (agentId === 'warden') return 'Warden'
  return 'Events'
}

function labelize(value: string | null | undefined): string {
  if (!value) return 'unknown'
  return value.replaceAll('_', ' ')
}

function ageHours(iso: string | null | undefined): number | null {
  if (!iso) return null
  const parsed = Date.parse(iso)
  if (Number.isNaN(parsed)) return null
  return Math.max(0, (Date.now() - parsed) / 3_600_000)
}

function latestEvent(events: SecurityAgentEvent[]): SecurityAgentEvent | null {
  return [...events].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0] ?? null
}

function checkMap(report: PorchlightReport | null): Map<string, PorchlightCheck> {
  return new Map(report?.checks.map((check) => [check.name, check]) ?? [])
}

function agentMap(wardenStatus: WardenStatus | null): Map<string, WardenAgent> {
  const agents = wardenStatus?.agents ?? []
  const entries = agents.flatMap((agent): Array<[string, WardenAgent]> => {
    if (agent.agent_id === 'sweep') return [[agent.agent_id, agent], ['network_watchdog', agent]]
    return [[agent.agent_id, agent]]
  })
  return new Map(entries)
}

function laneStatus(lane: CoverageLane, agents: Map<string, WardenAgent>, checks: Map<string, PorchlightCheck>): ConsoleStatus {
  const laneAgents = lane.agents.map((agentId) => agents.get(agentId)).filter(Boolean) as WardenAgent[]
  const laneChecks = lane.checks.map((checkName) => checks.get(checkName)).filter(Boolean) as PorchlightCheck[]
  if (laneAgents.length === 0 && laneChecks.length === 0) return 'unavailable'
  if (laneChecks.some((check) => check.status === 'fail')) return 'fail'
  if (laneAgents.some((agent) => agent.enabled && agent.needs_attention)) return 'warn'
  if (laneChecks.some((check) => check.status === 'warn')) return 'warn'
  const expectedEvidence = lane.agents.length + lane.checks.length
  if (laneAgents.length + laneChecks.length < expectedEvidence) return 'warn'
  return 'pass'
}

function agentStatus(agent: WardenAgent): ConsoleStatus {
  if (!agent.enabled) return 'unavailable'
  if (agent.last_run_status === 'failed') return 'fail'
  if (agent.needs_attention) return 'warn'
  return 'pass'
}

function statusLabel(status: ConsoleStatus): string {
  if (status === 'pass') return 'ok'
  if (status === 'warn') return 'watch'
  if (status === 'fail') return 'act'
  return 'waiting'
}

function runtimeLabel(agent: WardenAgent): string {
  if (!agent.enabled) return 'disabled'
  if (agent.last_run_status === 'failed') return 'failed'
  return agent.status
}

function reportCompletenessStatus(report: PorchlightReport | null): ConsoleStatus {
  if (!report) return 'unavailable'
  const completeness = report.checks.find((check) => check.name === 'porchlight_report_completeness')
  if (completeness && completeness.status !== 'pass') return 'fail'
  if (report.counts.checks < EXPECTED_PORCHLIGHT_CHECKS) return 'warn'
  return 'pass'
}

function reportFreshnessStatus(report: PorchlightReport | null): ConsoleStatus {
  const hours = ageHours(report?.generated_at)
  if (hours === null) return 'unavailable'
  if (hours > PORCHLIGHT_STALE_AFTER_HOURS) return 'warn'
  return 'pass'
}

function latestEventStatus(event: SecurityAgentEvent | null): ConsoleStatus {
  if (!event) return 'unavailable'
  const severity = event.severity.toLowerCase()
  if (severity === 'critical' || severity === 'error' || severity === 'fail') return 'fail'
  if (severity === 'warning' || severity === 'needs_input' || severity === 'high') return 'warn'
  return 'pass'
}

function proofLine(agent: WardenAgent): string {
  if (agent.last_event_title) return agent.last_event_title
  if (agent.last_run_status) return `last run ${agent.last_run_status}`
  return agent.enabled ? 'waiting for first event' : 'disabled'
}

export function SecurityAgentsConsole({
  isDark,
  border,
  subtle,
  fg,
  muted,
  wardenStatus,
  porchlightReport,
  agentEvents,
  loadWarden,
  loadPorchlight,
  errWarden,
  errPorchlight,
  onSelectTab,
}: SecurityAgentsConsoleProps) {
  const latest = latestEvent(agentEvents)
  const checks = checkMap(porchlightReport)
  const agents = agentMap(wardenStatus)
  const reportAge = ageHours(porchlightReport?.generated_at)
  const freshnessStatus = reportFreshnessStatus(porchlightReport)
  const completenessStatus = reportCompletenessStatus(porchlightReport)
  const runtimeStatus: ConsoleStatus = !wardenStatus
    ? 'unavailable'
    : wardenStatus.counts.attention > 0
      ? 'warn'
      : 'pass'
  const eventStatus = latestEventStatus(latest)

  if ((loadWarden && !wardenStatus) || (loadPorchlight && !porchlightReport)) {
    return <SectionSkeleton border={border} subtle={subtle} />
  }

  if ((errWarden || !wardenStatus) && (errPorchlight || !porchlightReport)) {
    return <SectionUnavailable border={border} subtle={subtle} />
  }

  const statusTiles = [
    {
      label: 'Full sweep',
      value: freshnessStatus === 'pass' ? 'Fresh' : freshnessStatus === 'warn' ? 'Stale' : 'Waiting',
      detail: porchlightReport
        ? `${relativeAccessedLabel(porchlightReport.generated_at)} · daily 07:35 Brain`
        : 'No Porchlight report loaded',
      icon: Clock,
      status: freshnessStatus,
      tab: 'Porchlight',
    },
    {
      label: 'Completeness',
      value: `${porchlightReport?.counts.checks ?? 0}/${EXPECTED_PORCHLIGHT_CHECKS}`,
      detail: completenessStatus === 'pass' ? 'Required checks observed' : 'Completeness guard needs review',
      icon: ShieldCheck,
      status: completenessStatus,
      tab: 'Porchlight',
    },
    {
      label: 'Agent runtime',
      value: `${wardenStatus?.counts.enabled ?? 0}/${wardenStatus?.counts.managed ?? 0}`,
      detail: `${wardenStatus?.counts.attention ?? 0} attention · 10m Warden`,
      icon: Eye,
      status: runtimeStatus,
      tab: 'Warden',
    },
    {
      label: 'Evidence stream',
      value: latest ? latest.notification_status : 'Waiting',
      detail: latest ? `${labelize(latest.agent_id)} · ${relativeAccessedLabel(latest.created_at)}` : 'No recent agent event',
      icon: FileText,
      status: eventStatus,
      tab: 'Events',
    },
  ]

  return (
    <section className={`rounded-xl border ${border} ${subtle} p-4`}>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
            Security agents console
          </p>
          <h2 className={`mt-1 text-lg font-semibold ${fg}`}>Observe, route, and prove agent work</h2>
          <p className={`mt-2 max-w-3xl text-sm leading-6 ${muted}`}>
            Warden correlates the agent crew, Porchlight supplies the posture sweep, and the event ledger keeps the proof trail.
          </p>
        </div>
        <div className={`rounded-lg border ${border} px-3 py-2 text-xs font-mono ${muted}`}>
          Report age: {reportAge === null ? 'unknown' : `${reportAge.toFixed(reportAge < 10 ? 1 : 0)}h`}
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        {statusTiles.map((tile) => {
          const Icon = tile.icon
          return (
            <button
              key={tile.label}
              type="button"
              onClick={() => onSelectTab(tile.tab)}
              className={`rounded-lg border p-3 text-left transition-colors hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-orange-400/40 ${statusClass(tile.status, isDark)}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[10px] font-mono uppercase opacity-70">{tile.label}</p>
                  <p className="mt-2 text-lg font-bold">{tile.value}</p>
                </div>
                <Icon className="h-4 w-4 shrink-0 opacity-80" />
              </div>
              <p className="mt-2 text-[11px] font-mono opacity-75">{tile.detail}</p>
            </button>
          )
        })}
      </div>

      <div className="mt-6 grid grid-cols-1 gap-3 xl:grid-cols-5">
        {coverageLanes.map((lane) => {
          const laneState = laneStatus(lane, agents, checks)
          const Icon = lane.icon
          const StateIcon = statusIcon(laneState)
          const laneAgents = lane.agents.map((agentId) => agents.get(agentId)).filter(Boolean) as WardenAgent[]
          const healthyAgents = laneAgents.filter((agent) => agentStatus(agent) === 'pass').length
          const laneChecks = lane.checks.map((checkName) => checks.get(checkName)).filter(Boolean) as PorchlightCheck[]
          const passingChecks = laneChecks.filter((check) => check.status === 'pass').length
          const evidencePassing = lane.checks.length ? passingChecks : healthyAgents
          const evidenceTotal = lane.checks.length || lane.agents.length
          const evidenceLabel = lane.checks.length ? 'checks' : 'agents'
          return (
            <button
              key={lane.id}
              type="button"
              onClick={() => onSelectTab(lane.tab)}
              className={`rounded-lg border ${border} ${isDark ? 'bg-black/10 hover:bg-white/5' : 'bg-white/60 hover:bg-white'} p-3 text-left transition-colors focus:outline-none focus:ring-2 focus:ring-orange-400/40`}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Icon className="h-4 w-4 text-orange-400" />
                  <p className={`text-sm font-bold ${fg}`}>{lane.title}</p>
                </div>
                <StateIcon className={`h-4 w-4 ${
                  laneState === 'pass' ? 'text-emerald-400' : laneState === 'fail' ? 'text-rose-400' : 'text-amber-300'
                }`} />
              </div>
              <p className={`mt-2 min-h-10 text-xs leading-5 ${muted}`}>{lane.detail}</p>
              <div className={`mt-3 flex items-center justify-between gap-2 text-[10px] font-mono uppercase ${muted}`}>
                <span>{evidencePassing}/{evidenceTotal} {evidenceLabel}</span>
                <span>{statusLabel(laneState)}</span>
              </div>
            </button>
          )
        })}
      </div>

      <div className="mt-6 overflow-x-auto rounded-lg border border-white/10">
        <table className="min-w-[920px] w-full text-xs">
          <thead className={isDark ? 'bg-white/5' : 'bg-black/5'}>
            <tr>
              <th className="px-3 py-2 text-left font-mono uppercase opacity-45">Agent</th>
              <th className="px-3 py-2 text-left font-mono uppercase opacity-45">Runtime</th>
              <th className="px-3 py-2 text-left font-mono uppercase opacity-45">Cadence</th>
              <th className="px-3 py-2 text-left font-mono uppercase opacity-45">Last proof</th>
              <th className="px-3 py-2 text-left font-mono uppercase opacity-45">Open</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {(wardenStatus?.agents ?? []).map((agent) => {
              const state = agentStatus(agent)
              return (
                <tr key={agent.agent_id}>
                  <td className="px-3 py-3">
                    <p className={`font-bold ${fg}`}>{agent.display_name}</p>
                    <p className={`mt-0.5 font-mono ${muted}`}>{labelize(agent.agent_id)}</p>
                  </td>
                  <td className="px-3 py-3">
                    <span className={`inline-flex rounded border px-2 py-1 text-[10px] font-mono uppercase ${statusClass(state, isDark)}`}>
                      {runtimeLabel(agent)}
                    </span>
                  </td>
                  <td className={`px-3 py-3 font-mono ${muted}`}>
                    {agent.cadence ?? 'manual'}
                  </td>
                  <td className="px-3 py-3">
                    <p className={`max-w-sm truncate font-mono ${fg}`}>{proofLine(agent)}</p>
                    <p className={`mt-0.5 font-mono ${muted}`}>
                      {agent.last_run_at ? relativeAccessedLabel(agent.last_run_at) : 'no run recorded'}
                    </p>
                  </td>
                  <td className="px-3 py-3">
                    <button
                      type="button"
                      onClick={() => onSelectTab(tabForAgent(agent.agent_id))}
                      className={`rounded-lg border ${border} px-3 py-2 font-mono transition-colors hover:opacity-80 focus:outline-none focus:ring-2 focus:ring-orange-400/40`}
                    >
                      {tabForAgent(agent.agent_id)}
                    </button>
                  </td>
                </tr>
              )
            })}
            {!wardenStatus?.agents?.length && (
              <tr>
                <td colSpan={5} className={`px-3 py-5 text-center font-mono ${muted}`}>
                  Warden agent inventory unavailable.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
