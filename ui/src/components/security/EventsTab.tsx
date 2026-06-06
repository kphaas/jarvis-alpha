import { motion } from 'framer-motion'
import { AlertTriangle, Shield } from 'lucide-react'
import type { LogEntry, SecurityAgentEvent } from '../../types/security'
import { SectionSkeleton, SectionUnavailable, type SecurityThemeProps } from './utils'

interface EventsTabProps extends SecurityThemeProps {
  agentEvents: SecurityAgentEvent[]
  loadAgentEvents: boolean
  errAgentEvents: boolean
  logEntries: LogEntry[]
  loadLogs: boolean
  errLogs: boolean
}

function severityClass(severity: string): string {
  const value = severity.toLowerCase()
  if (value === 'critical' || value === 'error') {
    return 'border-rose-500/30 bg-rose-500/15 text-rose-400'
  }
  if (value === 'warning' || value === 'needs_input') {
    return 'border-amber-500/30 bg-amber-500/15 text-amber-400'
  }
  return 'border-emerald-500/30 bg-emerald-500/15 text-emerald-400'
}

export function EventsTab({
  isDark,
  border,
  subtle,
  muted,
  agentEvents,
  loadAgentEvents,
  errAgentEvents,
  logEntries,
  loadLogs,
  errLogs,
}: EventsTabProps) {
  const noEvents =
    !loadAgentEvents &&
    !loadLogs &&
    !errAgentEvents &&
    !errLogs &&
    agentEvents.length === 0 &&
    logEntries.length === 0

  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
      <section>
        <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
          Warden & security agent events
        </p>
        {loadAgentEvents ? (
          <SectionSkeleton border={border} subtle={subtle} />
        ) : errAgentEvents ? (
          <SectionUnavailable border={border} subtle={subtle} />
        ) : agentEvents.length > 0 ? (
          <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
            <table className="w-full text-xs">
              <thead>
                <tr className={isDark ? 'bg-white/5' : 'bg-black/5'}>
                  <th className="text-left px-4 py-2 font-mono uppercase opacity-40">Timestamp</th>
                  <th className="text-left px-2 py-2 font-mono uppercase opacity-40">Severity</th>
                  <th className="text-left px-2 py-2 font-mono uppercase opacity-40">Agent</th>
                  <th className="text-left px-2 py-2 font-mono uppercase opacity-40">Event</th>
                  <th className="text-left px-4 py-2 font-mono uppercase opacity-40">Message</th>
                  <th className="text-left px-2 py-2 font-mono uppercase opacity-40">Notify</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {agentEvents.map((event) => (
                  <tr key={event.id}>
                    <td className="px-4 py-2 font-mono whitespace-nowrap opacity-70">
                      {event.created_at || '-'}
                    </td>
                    <td className="px-2 py-2">
                      <span
                        className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${severityClass(
                          event.severity,
                        )}`}
                      >
                        {event.severity || '-'}
                      </span>
                    </td>
                    <td className="px-2 py-2 font-mono opacity-80">{event.agent_id}</td>
                    <td className="px-2 py-2 font-mono opacity-80">{event.event_type}</td>
                    <td className="px-4 py-2 font-mono opacity-90 max-w-md">
                      <div className="font-bold">{event.title}</div>
                      <div className="opacity-70 break-words">{event.message}</div>
                    </td>
                    <td className="px-2 py-2 font-mono opacity-80">{event.notification_status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section>
        <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
          Warning & error logs
        </p>
        {loadLogs ? (
          <SectionSkeleton border={border} subtle={subtle} />
        ) : errLogs ? (
          <SectionUnavailable border={border} subtle={subtle} />
        ) : logEntries.length > 0 ? (
          <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
            <table className="w-full text-xs">
              <thead>
                <tr className={isDark ? 'bg-white/5' : 'bg-black/5'}>
                  <th className="text-left px-4 py-2 font-mono uppercase opacity-40">Timestamp</th>
                  <th className="text-left px-2 py-2 font-mono uppercase opacity-40">Level</th>
                  <th className="text-left px-2 py-2 font-mono uppercase opacity-40">Service</th>
                  <th className="text-left px-4 py-2 font-mono uppercase opacity-40">Message</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {logEntries.map((entry, index) => {
                  const level = (entry.level || '').toUpperCase()
                  const badgeClass = severityClass(level === 'WARNING' ? 'warning' : level.toLowerCase())
                  const pulse = level === 'CRITICAL' ? ' animate-pulse' : ''
                  return (
                    <tr key={`${entry.ts}-${index}`}>
                      <td className="px-4 py-2 font-mono whitespace-nowrap opacity-70">
                        {entry.ts || '-'}
                      </td>
                      <td className="px-2 py-2">
                        <span
                          className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${badgeClass}${pulse}`}
                        >
                          {entry.level || '-'}
                        </span>
                      </td>
                      <td className="px-2 py-2 font-mono opacity-80">{entry.service}</td>
                      <td className="px-4 py-2 font-mono opacity-90 break-all max-w-md">
                        {entry.message}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      {noEvents ? (
        <div className={`rounded-2xl border ${border} ${subtle} p-10 flex flex-col items-center gap-3 text-center`}>
          <Shield className="w-10 h-10 text-emerald-400/60" />
          <p className={`text-sm font-mono ${muted}`}>No recent security events</p>
        </div>
      ) : errAgentEvents || errLogs ? (
        <div className={`rounded-2xl border ${border} ${subtle} p-4 flex items-center gap-3`}>
          <AlertTriangle className="w-5 h-5 text-amber-400" />
          <p className={`text-xs font-mono ${muted}`}>One event source is unavailable.</p>
        </div>
      ) : null}
    </motion.div>
  )
}
