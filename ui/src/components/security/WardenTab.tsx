import { motion } from 'framer-motion'
import { AlertTriangle, CheckCircle, Clock, ShieldCheck, Wrench } from 'lucide-react'
import type { WardenStatus } from '../../types/security'
import { SectionSkeleton, SectionUnavailable, relativeAccessedLabel, type SecurityThemeProps } from './utils'

interface WardenTabProps extends SecurityThemeProps {
  wardenStatus: WardenStatus | null
  loadWarden: boolean
  errWarden: boolean
}

function statusClass(needsAttention: boolean, enabled: boolean): string {
  if (!enabled) return 'border-zinc-500/30 bg-zinc-500/15 text-zinc-400'
  if (needsAttention) return 'border-amber-500/30 bg-amber-500/15 text-amber-300'
  return 'border-emerald-500/30 bg-emerald-500/15 text-emerald-400'
}

function controlStatusClass(status: string): string {
  if (status === 'pass') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
  if (status === 'warn') return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
  if (status === 'fail') return 'border-rose-500/30 bg-rose-500/10 text-rose-400'
  return 'border-zinc-500/30 bg-zinc-500/10 text-zinc-400'
}

function roleLabel(value: unknown): string {
  if (typeof value !== 'string' || !value) return 'security'
  return value.replaceAll('_', ' ')
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

export function WardenTab({
  border, subtle, fg, muted, wardenStatus, loadWarden, errWarden,
}: WardenTabProps) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-8">
      <section>
        <p className="mb-1 text-[10px] font-mono uppercase opacity-40 tracking-widest">
          Warden command
        </p>
        {loadWarden && !wardenStatus ? (
          <SectionSkeleton border={border} subtle={subtle} />
        ) : errWarden || !wardenStatus ? (
          <SectionUnavailable border={border} subtle={subtle} />
        ) : (
          <div className={`rounded-2xl border ${border} ${subtle} p-5`}>
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="w-5 h-5 text-emerald-400 shrink-0" />
                  <p className={`text-2xl font-bold ${fg}`}>
                    {wardenStatus.supervisor?.display_name ?? 'Warden'}
                  </p>
                </div>
                <p className={`mt-2 max-w-2xl text-sm ${muted}`}>
                  {wardenStatus.supervisor?.purpose ?? 'Security agent coordinator.'}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-2 text-center">
                <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-3 py-2">
                  <p className="text-lg font-bold font-mono text-emerald-400">{wardenStatus.counts.enabled}</p>
                  <p className={`text-[9px] font-mono uppercase ${muted}`}>enabled</p>
                </div>
                <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2">
                  <p className="text-lg font-bold font-mono text-amber-300">{wardenStatus.counts.attention}</p>
                  <p className={`text-[9px] font-mono uppercase ${muted}`}>attention</p>
                </div>
              </div>
            </div>
            <div className={`mt-4 flex items-center gap-2 text-xs font-mono ${muted}`}>
              <Wrench className="w-3.5 h-3.5" />
              Active hardening: {(wardenStatus.active_hardening ?? wardenStatus.next_hardening).replaceAll('_', ' ')}
            </div>
            {wardenStatus.posture_score && (
              <div className={`mt-4 rounded-xl border ${border} p-3`}>
                <p className="text-xs font-mono uppercase opacity-50">
                  Warden posture score
                </p>
                <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                  <div>
                    <p className="text-3xl font-bold font-mono">
                      {wardenStatus.posture_score.score}
                      <span className={`ml-1 text-xs font-normal ${muted}`}>/100</span>
                    </p>
                    <p className={`mt-1 text-xs ${muted}`}>
                      {wardenStatus.posture_score.controls_passing}/{wardenStatus.posture_score.controls_total} controls passing
                    </p>
                  </div>
                  <p className={`max-w-xl text-xs ${muted}`}>
                    Industry-aligned to SOC 2 CC6/CC7, CIS v8, and NIST CSF. This is not a certification score.
                  </p>
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      {wardenStatus?.posture_score && (
        <section>
          <p className="mb-3 text-[10px] font-mono uppercase opacity-40 tracking-widest">
            Weighted controls
          </p>
          <div className="grid grid-cols-1 gap-3">
            {wardenStatus.posture_score.controls.map((control) => (
              <div key={control.id} className={`rounded-2xl border ${border} ${subtle} p-4`}>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <p className="text-sm font-bold">{control.title}</p>
                    <p className={`mt-1 text-sm ${fg}`}>{control.summary}</p>
                    <p className={`mt-2 text-xs font-mono ${muted}`}>
                      {control.category} · owner {control.owner_agent.replaceAll('_', ' ')} · {control.earned}/{control.weight} pts
                    </p>
                  </div>
                  <span className={`shrink-0 rounded border px-2 py-1 text-[10px] font-mono uppercase ${controlStatusClass(control.status)}`}>
                    {control.status}
                  </span>
                </div>
                {control.framework_refs.length > 0 && (
                  <p className={`mt-3 text-[10px] font-mono ${muted}`}>
                    {control.framework_refs.join(' · ')}
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {wardenStatus && (
        <section>
          <p className="mb-3 text-[10px] font-mono uppercase opacity-40 tracking-widest">
            Managed agents
          </p>
          <div className="grid grid-cols-1 gap-3">
            {wardenStatus.agents.map((agent) => (
              <div key={agent.agent_id} className={`rounded-2xl border ${border} ${subtle} p-4`}>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      {agent.needs_attention ? (
                        <AlertTriangle className="w-4 h-4 text-amber-300 shrink-0" />
                      ) : (
                        <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0" />
                      )}
                      <p className="font-bold text-sm">{agent.display_name}</p>
                      <span className={`rounded border px-2 py-0.5 text-[10px] font-mono font-bold ${statusClass(agent.needs_attention, agent.enabled)}`}>
                        {agent.enabled ? agent.status : 'disabled'}
                      </span>
                    </div>
                    <p className={`mt-2 text-sm ${fg}`}>{agent.purpose}</p>
                    <p className={`mt-2 text-xs font-mono ${muted}`}>
                      {roleLabel(agent.metadata.warden_role)} · risk {agent.risk_tier} · cadence {agent.cadence ?? 'manual'}
                    </p>
                  </div>
                  <div className={`shrink-0 text-xs font-mono ${muted}`}>
                    <Clock className="mr-1 inline h-3.5 w-3.5" />
                    {agent.last_run_at ? relativeAccessedLabel(agent.last_run_at) : 'No run'}
                  </div>
                </div>
                {agent.agent_id === 'network_watchdog' && (
                  <div className="mt-3 rounded-xl border border-sky-500/20 bg-sky-500/10 px-3 py-2 text-xs font-mono text-sky-300">
                    Monitors UniFi TLS pinning.
                  </div>
                )}
                {agent.agent_id === 'tripwire' && (
                  <div className="mt-3 rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs font-mono text-amber-300">
                    Owns honeypot trap monitoring and alert escalation.
                  </div>
                )}
                {agent.agent_id === 'ledger' && (
                  <div className="mt-3 rounded-xl border border-violet-500/20 bg-violet-500/10 px-3 py-2 text-xs font-mono text-violet-300">
                    Packages security events, access changes, Cloudflare drift, and key rotations into tamper-evident reports.
                  </div>
                )}
                {stringList(agent.metadata.capabilities).length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {stringList(agent.metadata.capabilities).map((capability) => (
                      <span key={capability} className={`rounded border px-2 py-1 text-[10px] font-mono ${muted}`}>
                        {capability.replaceAll('_', ' ')}
                      </span>
                    ))}
                  </div>
                )}
                {stringList(agent.metadata.planned_skills).length > 0 && (
                  <div className="mt-3">
                    <p className={`mb-1 text-[10px] font-mono uppercase ${muted}`}>saved skills</p>
                    <div className="flex flex-wrap gap-1.5">
                      {stringList(agent.metadata.planned_skills).map((skill) => (
                        <span key={skill} className="rounded border border-sky-500/20 bg-sky-500/10 px-2 py-1 text-[10px] font-mono text-sky-300">
                          {skill}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
    </motion.div>
  )
}
