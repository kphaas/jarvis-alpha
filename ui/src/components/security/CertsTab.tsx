import { motion } from 'framer-motion'
import { Activity, CheckCircle, Clock, Loader2, Play, Radio, Router, ShieldCheck, Wifi } from 'lucide-react'
import type { CertRow, WardenStatus } from '../../types/security'
import { SectionSkeleton, SectionUnavailable, certDayTextClass, certBarPct, certBarColor, type SecurityThemeProps } from './utils'

interface SweepTabProps extends SecurityThemeProps {
  certs: CertRow[] | null
  sortedCerts: CertRow[]
  loadCerts: boolean
  errCerts: boolean
  wardenStatus: WardenStatus | null
  loadWarden: boolean
  errWarden: boolean
  runLoading: boolean
  runError: string | null
  onRun: () => void
}

const responsibilityIcons = [ShieldCheck, Wifi, Activity, Router]

function labelize(value: string): string {
  return value.replaceAll('_', ' ')
}

function renewalModeLabel(value: unknown): string {
  if (typeof value !== 'string' || !value) return 'node local'
  return labelize(value)
}

export function SweepTab({
  isDark, border, subtle, fg, muted,
  certs, sortedCerts, loadCerts, errCerts,
  wardenStatus, loadWarden, errWarden,
  runLoading, runError, onRun,
}: SweepTabProps) {
  const sweep = wardenStatus?.agents.find((agent) => agent.agent_id === 'sweep' || agent.agent_id === 'network_watchdog') ?? null
  const monitors = Array.isArray(sweep?.metadata.monitors)
    ? sweep?.metadata.monitors.filter((item): item is string => typeof item === 'string')
    : []
  const completedHardenings = Array.isArray(sweep?.metadata.completed_hardenings)
    ? sweep?.metadata.completed_hardenings.filter((item): item is string => typeof item === 'string')
    : []
  const certRenewal = (
    sweep?.metadata.cert_renewal && typeof sweep.metadata.cert_renewal === 'object'
      ? sweep.metadata.cert_renewal as Record<string, unknown>
      : {}
  )
  const shortestCertDays = certs?.length ? Math.min(...certs.map((cert) => cert.days_remaining)) : null

  return (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-8">
          <section>
            <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest">
                  Sweep network guard
                </p>
                <p className={`mt-1 max-w-2xl text-sm ${muted}`}>
                  Service TLS, UniFi trust, WAN health, and new-device monitoring.
                </p>
              </div>
              <button
                type="button"
                onClick={onRun}
                disabled={runLoading}
                className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border px-4 py-2 text-xs font-bold transition-opacity ${border} ${subtle} hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50`}
              >
                {runLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                Run now
              </button>
            </div>
            {loadWarden && !wardenStatus ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errWarden || !wardenStatus || !sweep ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : (
              <div className={`rounded-2xl border ${border} ${subtle} p-5`}>
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Radio className="h-5 w-5 text-sky-400" />
                      <p className={`text-2xl font-bold ${fg}`}>{sweep.display_name}</p>
                      <span className={`rounded border px-2 py-0.5 text-[10px] font-mono uppercase ${
                        sweep.needs_attention
                          ? 'border-amber-500/30 bg-amber-500/15 text-amber-300'
                          : 'border-emerald-500/30 bg-emerald-500/15 text-emerald-400'
                      }`}>
                        {sweep.needs_attention ? 'attention' : sweep.status}
                      </span>
                    </div>
                    <p className={`mt-2 max-w-2xl text-sm ${fg}`}>{sweep.purpose}</p>
                    <p className={`mt-3 text-xs font-mono ${muted}`}>
                      Cadence {sweep.cadence ?? 'manual'} · risk {sweep.risk_tier} · owner Warden
                    </p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-center sm:min-w-56">
                    <div className="rounded-xl border border-sky-500/20 bg-sky-500/10 px-3 py-2">
                      <p className="text-lg font-bold font-mono text-sky-400">{monitors.length}</p>
                      <p className={`text-[9px] font-mono uppercase ${muted}`}>monitors</p>
                    </div>
                    <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-3 py-2">
                      <p className="text-lg font-bold font-mono text-emerald-400">
                        {shortestCertDays === null ? '—' : `${shortestCertDays}d`}
                      </p>
                      <p className={`text-[9px] font-mono uppercase ${muted}`}>shortest cert</p>
                    </div>
                  </div>
                </div>
                {runError && (
                  <div className="mt-4 rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                    {runError}
                  </div>
                )}
              </div>
            )}
          </section>

          <section>
            <p className="mb-3 text-[10px] font-mono uppercase opacity-40 tracking-widest">
              Sweep responsibilities
            </p>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {monitors.map((monitor, index) => {
                const Icon = responsibilityIcons[index % responsibilityIcons.length]
                return (
                  <div key={monitor} className={`rounded-2xl border ${border} ${subtle} p-4`}>
                    <div className="flex items-start gap-3">
                      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-sky-400" />
                      <div className="min-w-0">
                        <p className="text-sm font-bold capitalize">{labelize(monitor)}</p>
                        <p className={`mt-1 text-xs ${muted}`}>
                          {monitor === 'service_tls_certs' && 'Renews and tracks Alpha service certificates on each node.'}
                          {monitor === 'unifi_tls_pin' && 'Verifies the UniFi controller with public-key pinning.'}
                          {monitor === 'wan_health' && 'Checks WAN status, latency, ISP state, and gateway health.'}
                          {monitor === 'new_clients' && 'Detects new UniFi clients so unknown devices are surfaced.'}
                          {monitor === 'unknown_device_quarantine' && 'Recommends review/quarantine for unknown devices without changing UniFi state.'}
                          {monitor === 'unifi_firmware_drift' && 'Detects gateway, switch, and AP firmware updates from UniFi inventory.'}
                          {monitor === 'wan_failover_health' && 'Checks whether UniFi reports a ready secondary WAN or failover path.'}
                          {![
                            'service_tls_certs',
                            'unifi_tls_pin',
                            'wan_health',
                            'new_clients',
                            'unknown_device_quarantine',
                            'unifi_firmware_drift',
                            'wan_failover_health',
                          ].includes(monitor) && 'Tracked by Sweep and reported to Warden.'}
                        </p>
                      </div>
                    </div>
                  </div>
                )
              })}
              {monitors.length === 0 && (
                <div className={`rounded-2xl border ${border} ${subtle} p-4`}>
                  <p className={`text-sm ${muted}`}>Sweep monitor inventory is unavailable.</p>
                </div>
              )}
            </div>
          </section>

          <section>
            <p className="mb-3 text-[10px] font-mono uppercase opacity-40 tracking-widest">
              TLS renewal ownership
            </p>
            <div className={`rounded-2xl border ${border} ${subtle} p-4`}>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                <div>
                  <p className={`text-[10px] font-mono uppercase ${muted}`}>mode</p>
                  <p className="mt-1 text-sm font-bold capitalize">{renewalModeLabel(certRenewal.mode)}</p>
                </div>
                <div>
                  <p className={`text-[10px] font-mono uppercase ${muted}`}>threshold</p>
                  <p className="mt-1 text-sm font-bold">
                    {typeof certRenewal.threshold_days === 'number' ? `${certRenewal.threshold_days} days` : '30 days'}
                  </p>
                </div>
                <div>
                  <p className={`text-[10px] font-mono uppercase ${muted}`}>launch job</p>
                  <p className="mt-1 truncate text-sm font-mono">
                    {typeof certRenewal.launch_label === 'string' ? certRenewal.launch_label : 'com.jarvis.alpha.sweep-cert-renewal.*'}
                  </p>
                </div>
              </div>
              {completedHardenings.length > 0 && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {completedHardenings.map((item) => (
                    <span key={item} className="inline-flex items-center gap-1 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-1 text-[10px] font-mono text-emerald-400">
                      <CheckCircle className="h-3 w-3" />
                      {labelize(item)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </section>

          <section>
          <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
            Service TLS certificates
          </p>
          {loadCerts && !certs ? (
            <SectionSkeleton border={border} subtle={subtle} />
          ) : errCerts || !certs?.length ? (
            <SectionUnavailable border={border} subtle={subtle} />
          ) : (
            <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
              <table className="w-full text-xs">
                <thead>
                  <tr className={isDark ? "bg-white/5" : "bg-black/5"}>
                    <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                      Node
                    </th>
                    <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                      Domain
                    </th>
                    <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                      Expires
                    </th>
                    <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                      Days
                    </th>
                    <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                      Status
                    </th>
                    <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                      Source
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {sortedCerts.map((c) => (
                    <tr key={`${c.node}-${c.domain}`}>
                      <td className="px-4 py-3 font-mono capitalize">{c.node}</td>
                      <td className="px-2 py-3 font-mono opacity-90">{c.domain}</td>
                      <td className="px-2 py-3 font-mono opacity-70">
                        {c.expires ? new Date(c.expires).toLocaleDateString() : "—"}
                      </td>
                      <td className="px-2 py-3">
                        <span className={`font-mono font-bold ${certDayTextClass(c.days_remaining)}`}>
                          {c.days_remaining}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-col gap-1 min-w-[140px]">
                          <span className="text-[10px] font-mono uppercase opacity-60">
                            {c.status}
                          </span>
                          <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
                            <div
                              className="h-full rounded-full transition-all"
                              style={{
                                width: `${certBarPct(c.days_remaining)}%`,
                                backgroundColor: certBarColor(c.days_remaining),
                              }}
                            />
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[10px] font-mono uppercase ${
                          c.source === 'tls'
                            ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                            : c.source === 'disk'
                              ? 'border-sky-500/30 bg-sky-500/10 text-sky-400'
                              : 'border-zinc-500/30 bg-zinc-500/10 text-zinc-400'
                        }`}>
                          <Clock className="h-3 w-3" />
                          {c.source}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          </section>
        </motion.div>
  );
}

export const CertsTab = SweepTab
