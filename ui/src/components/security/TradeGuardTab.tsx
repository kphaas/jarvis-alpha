import { motion } from 'framer-motion'
import { Activity, AlertTriangle, CheckCircle, LockKeyhole, Route, ShieldCheck } from 'lucide-react'
import type { SecurityAgentEvent, WardenAgent, WardenStatus } from '../../types/security'
import { SectionSkeleton, SectionUnavailable, relativeAccessedLabel, type SecurityThemeProps } from './utils'

interface TradeGuardTabProps extends SecurityThemeProps {
  wardenStatus: WardenStatus | null
  loadWarden: boolean
  errWarden: boolean
  agentEvents: SecurityAgentEvent[]
  loadAgentEvents: boolean
  errAgentEvents: boolean
}

function asStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function tradeGuardAgent(status: WardenStatus | null): WardenAgent | null {
  return status?.agents.find((agent) => agent.agent_id === 'trade_guard') ?? null
}

function labelize(value: string): string {
  return value.replaceAll('_', ' ')
}

function badgeClass(status: string): string {
  const normalized = status.toLowerCase()
  if (normalized === 'active' || normalized === 'pass' || normalized === 'routed') {
    return 'border-emerald-500/30 bg-emerald-500/15 text-emerald-400'
  }
  if (normalized === 'planned' || normalized === 'warn' || normalized === 'warning' || normalized === 'attention') {
    return 'border-amber-500/30 bg-amber-500/15 text-amber-300'
  }
  if (normalized === 'blocked' || normalized === 'fail' || normalized === 'critical' || normalized === 'error') {
    return 'border-rose-500/30 bg-rose-500/15 text-rose-400'
  }
  return 'border-zinc-500/30 bg-zinc-500/15 text-zinc-400'
}

function tradeGuardEvents(events: SecurityAgentEvent[]): SecurityAgentEvent[] {
  return events.filter((event) => {
    const eventType = event.event_type.toLowerCase()
    const title = event.title.toLowerCase()
    return (
      event.agent_id === 'trade_guard' ||
      eventType.includes('trade_guard') ||
      eventType.includes('trade guard') ||
      title.includes('trade guard')
    )
  })
}

export function TradeGuardTab({
  border,
  subtle,
  fg,
  muted,
  wardenStatus,
  loadWarden,
  errWarden,
  agentEvents,
  loadAgentEvents,
  errAgentEvents,
}: TradeGuardTabProps) {
  const tradeGuard = tradeGuardAgent(wardenStatus)
  const protectedDomains = asStrings(tradeGuard?.metadata.protected_domains)
  const monitors = asStrings(tradeGuard?.metadata.monitors)
  const controls = asStrings(tradeGuard?.metadata.controls)
  const plannedSkills = asStrings(tradeGuard?.metadata.planned_skills)
  const capabilities = asStrings(tradeGuard?.metadata.capabilities)
  const events = tradeGuardEvents(agentEvents)
  const owner = wardenStatus?.supervisor?.display_name ?? 'Warden'
  const remediation = String(tradeGuard?.metadata.remediation ?? 'approval_only')
  const enforcement = String(tradeGuard?.metadata.enforcement ?? 'planned_not_active')

  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-8">
      <section>
        <p className="mb-1 text-[10px] font-mono uppercase opacity-40 tracking-widest">
          Trade Guard foundation
        </p>
        {loadWarden && !wardenStatus ? (
          <SectionSkeleton border={border} subtle={subtle} />
        ) : errWarden || !wardenStatus || !tradeGuard ? (
          <SectionUnavailable border={border} subtle={subtle} />
        ) : (
          <div className={`rounded-2xl border ${border} ${subtle} p-5`}>
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="h-5 w-5 shrink-0 text-emerald-400" />
                  <p className={`text-2xl font-bold ${fg}`}>{tradeGuard.display_name}</p>
                  <span className={`rounded border px-2 py-0.5 text-[10px] font-mono uppercase ${badgeClass(tradeGuard.needs_attention ? 'attention' : tradeGuard.status)}`}>
                    {tradeGuard.needs_attention ? 'attention' : tradeGuard.status}
                  </span>
                </div>
                <p className={`mt-2 max-w-2xl text-sm ${fg}`}>{tradeGuard.purpose}</p>
                <p className={`mt-3 text-xs font-mono ${muted}`}>
                  owner {owner} · role {labelize(String(tradeGuard.metadata.warden_role ?? 'trading_safety_monitor'))} · risk {tradeGuard.risk_tier}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-2 text-center sm:min-w-56">
                <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-3 py-2">
                  <p className="text-lg font-bold font-mono text-emerald-400">{monitors.length}</p>
                  <p className={`text-[9px] font-mono uppercase ${muted}`}>monitors</p>
                </div>
                <div className="rounded-xl border border-rose-500/20 bg-rose-500/10 px-3 py-2">
                  <p className="text-lg font-bold font-mono text-rose-300">0</p>
                  <p className={`text-[9px] font-mono uppercase ${muted}`}>trade powers</p>
                </div>
              </div>
            </div>
            <div className={`mt-4 flex items-center gap-2 text-xs font-mono ${muted}`}>
              <Activity className="h-3.5 w-3.5" />
              Last run {tradeGuard.last_run_at ? relativeAccessedLabel(tradeGuard.last_run_at) : 'not recorded yet'} · enforcement {labelize(enforcement)}
            </div>
          </div>
        )}
      </section>

      {tradeGuard && (
        <section>
          <p className="mb-3 text-[10px] font-mono uppercase opacity-40 tracking-widest">
            Protected domains
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {protectedDomains.map((domain) => (
              <div key={domain} className={`rounded-2xl border ${border} ${subtle} p-4`}>
                <CheckCircle className="mb-3 h-4 w-4 text-emerald-400" />
                <p className="text-sm font-bold capitalize">{labelize(domain)}</p>
                <p className={`mt-1 text-[10px] font-mono uppercase ${muted}`}>trading boundary</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {tradeGuard && (
        <section>
          <p className="mb-3 text-[10px] font-mono uppercase opacity-40 tracking-widest">
            Planned monitors
          </p>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {monitors.map((monitor) => (
              <div key={monitor} className={`rounded-2xl border ${border} ${subtle} p-4`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-bold capitalize">{labelize(monitor)}</p>
                    <p className={`mt-1 text-xs ${muted}`}>Read-only trading safety review owned by Trade Guard and supervised by Warden.</p>
                  </div>
                  <span className={`shrink-0 rounded border px-2 py-1 text-[10px] font-mono uppercase ${badgeClass('planned')}`}>
                    planned
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {tradeGuard && (
        <section>
          <p className="mb-3 text-[10px] font-mono uppercase opacity-40 tracking-widest">
            Controls and approval boundary
          </p>
          <div className={`rounded-2xl border ${border} ${subtle} p-4`}>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div>
                <p className="text-sm font-bold">Blocked by design</p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {controls.map((control) => (
                    <span key={control} className="rounded border border-rose-500/20 bg-rose-500/10 px-2 py-1 text-[10px] font-mono text-rose-300">
                      {labelize(control)}
                    </span>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-sm font-bold">Capabilities</p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {capabilities.map((capability) => (
                    <span key={capability} className={`rounded border px-2 py-1 text-[10px] font-mono ${muted}`}>
                      {labelize(capability)}
                    </span>
                  ))}
                </div>
              </div>
            </div>
            <div className="mt-4">
              <p className={`mb-1 text-[10px] font-mono uppercase ${muted}`}>saved skills</p>
              <div className="flex flex-wrap gap-1.5">
                {plannedSkills.map((skill) => (
                  <span key={skill} className="rounded border border-sky-500/20 bg-sky-500/10 px-2 py-1 text-[10px] font-mono text-sky-300">
                    {skill}
                  </span>
                ))}
              </div>
            </div>
            <div className="mt-4 rounded-xl border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              <LockKeyhole className="mr-1 inline h-3.5 w-3.5" />
              Remediation is {labelize(remediation)}. Trade Guard cannot place orders, mutate broker state, or enforce fixes unless Warden routes an approval.
            </div>
          </div>
        </section>
      )}

      <section>
        <p className="mb-3 text-[10px] font-mono uppercase opacity-40 tracking-widest">
          Findings and events
        </p>
        {loadAgentEvents ? (
          <SectionSkeleton border={border} subtle={subtle} />
        ) : errAgentEvents ? (
          <SectionUnavailable border={border} subtle={subtle} />
        ) : events.length > 0 ? (
          <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
            <table className="w-full text-xs">
              <thead>
                <tr>
                  <th className="px-4 py-2 text-left font-mono uppercase opacity-40">Time</th>
                  <th className="px-2 py-2 text-left font-mono uppercase opacity-40">Severity</th>
                  <th className="px-2 py-2 text-left font-mono uppercase opacity-40">Event</th>
                  <th className="px-4 py-2 text-left font-mono uppercase opacity-40">Message</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {events.map((event) => (
                  <tr key={event.id}>
                    <td className="px-4 py-2 font-mono whitespace-nowrap opacity-70">{event.created_at || '-'}</td>
                    <td className="px-2 py-2">
                      <span className={`rounded border px-2 py-0.5 text-[10px] font-mono uppercase ${badgeClass(event.severity)}`}>
                        {event.severity || '-'}
                      </span>
                    </td>
                    <td className="px-2 py-2 font-mono opacity-80">{event.event_type}</td>
                    <td className="px-4 py-2">
                      <p className="font-bold">{event.title}</p>
                      <p className={`mt-1 font-mono ${muted}`}>{event.message}</p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className={`rounded-2xl border ${border} ${subtle} p-8 text-center`}>
            <Route className="mx-auto h-8 w-8 text-emerald-400/60" />
            <p className={`mt-3 text-sm font-mono ${muted}`}>No Trade Guard findings recorded yet.</p>
          </div>
        )}
      </section>

      {tradeGuard?.needs_attention && (
        <div className={`rounded-2xl border ${border} ${subtle} p-4 flex items-center gap-3`}>
          <AlertTriangle className="h-5 w-5 text-amber-300" />
          <p className={`text-xs font-mono ${muted}`}>
            Trade Guard needs attention. Warden must route corrective work through approval before any remediation.
          </p>
        </div>
      )}
    </motion.div>
  )
}
