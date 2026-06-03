import { motion } from 'framer-motion'
import { Key, Lock, CheckCircle, XCircle, Loader2, Server, Radio, Bug, ShieldCheck } from 'lucide-react'
import type {
  JwtCheck,
  RlsStatus,
  Perimeter,
  HoneypotData,
  CertRow,
  WardenPostureScore,
  WardenPostureControl,
} from '../../types/security'
import { SectionSkeleton, R_SCORE, C_SCORE, certDayTextClass, type SecurityThemeProps } from './utils'

interface OverviewTabProps extends SecurityThemeProps {
  jwt: JwtCheck | null
  rls: RlsStatus | null
  perimeter: Perimeter | null
  certs: CertRow[] | null
  honeypotData: HoneypotData | null
  loadJwt: boolean
  loadRls: boolean
  loadPerimeter: boolean
  loadCerts: boolean
  loadChild: boolean
  loadHoneypot: boolean
  errJwt: boolean
  errRls: boolean
  errPerimeter: boolean
  errCerts: boolean
  errHoneypot: boolean
  displayScore: number
  reserved: number
  dashEarned: number
  strokeColor: string
  checksPassing: number
  checksTotal: number
  shortestCertDays: number | null
  postureScore?: WardenPostureScore
  setActiveTab: (tab: string) => void
}

function statusClass(status: string): string {
  if (status === 'pass') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
  if (status === 'warn') return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
  if (status === 'fail') return 'border-rose-500/30 bg-rose-500/10 text-rose-400'
  return 'border-zinc-500/30 bg-zinc-500/10 text-zinc-400'
}

function ownerLabel(control: WardenPostureControl): string {
  return control.owner_agent.replaceAll('_', ' ')
}

export function OverviewTab({
  isDark, border, subtle, fg, muted,
  jwt, rls, perimeter, certs, honeypotData,
  loadJwt, loadRls, loadPerimeter, loadCerts, loadChild, loadHoneypot,
  errJwt, errRls, errPerimeter, errCerts, errHoneypot,
  displayScore, reserved, dashEarned, strokeColor,
  checksPassing, checksTotal, shortestCertDays, postureScore, setActiveTab,
}: OverviewTabProps) {
  const topGaps = postureScore?.top_gaps ?? []
  return (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-8"
        >
          <section className="flex flex-col items-center gap-4">
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest self-start">
              Security posture score
            </p>
            {loadJwt &&
            loadPerimeter &&
            loadCerts &&
            loadRls &&
            loadChild &&
            loadHoneypot &&
            !jwt ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : (
              <div className="relative w-[200px] h-[200px] flex items-center justify-center">
                <svg width="200" height="200" className="-rotate-90">
                  <circle
                    cx="100"
                    cy="100"
                    r={R_SCORE}
                    fill="none"
                    stroke={isDark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.1)"}
                    strokeWidth="10"
                  />
                  <motion.circle
                    cx="100"
                    cy="100"
                    r={R_SCORE}
                    fill="none"
                    stroke={strokeColor}
                    strokeWidth="10"
                    strokeLinecap="round"
                    strokeDasharray={`${dashEarned} ${C_SCORE}`}
                    initial={{ strokeDashoffset: C_SCORE }}
                    animate={{ strokeDashoffset: C_SCORE - dashEarned }}
                    transition={{ duration: 0.9, ease: "easeOut" }}
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                  <span
                    className="text-4xl font-bold font-mono tabular-nums"
                    style={{ color: strokeColor }}
                  >
                    {displayScore}
                  </span>
                  <span className={`text-[9px] font-mono uppercase ${muted}`}>of 100</span>
                </div>
              </div>
            )}
            <p className={`text-xs font-mono ${muted} text-center`}>
              {checksTotal > 0
                ? `${checksPassing} of ${checksTotal} checks passing`
                : "Collecting check data…"}
            </p>
            {postureScore ? (
              <div className={`max-w-2xl text-center text-[10px] font-mono ${muted}`}>
                <p>
                  Warden model: {postureScore.model.replaceAll('_', ' ')} · {postureScore.basis.replaceAll('_', ' ')}
                </p>
                <p className="mt-1">
                  Aligned to SOC 2 CC6/CC7, CIS v8, and NIST CSF. Not a certification score.
                </p>
              </div>
            ) : (
              <p className={`text-[10px] font-mono ${muted} text-center max-w-md`}>
                <span className="opacity-70">{reserved} pts reserved</span> (secrets audit, key rotation, future checks) —{" "}
                <span className="text-zinc-500">locked</span>
              </p>
            )}
          </section>

          {postureScore && (
            <section>
              <div className="mb-3 flex items-center gap-2">
                <ShieldCheck className="w-3.5 h-3.5 opacity-40" />
                <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest">
                  Warden control gaps
                </p>
              </div>
              {topGaps.length === 0 ? (
                <div className={`rounded-2xl border ${border} ${subtle} p-4`}>
                  <p className="text-sm text-emerald-400">All weighted Warden controls are passing.</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {topGaps.map((control) => (
                    <button
                      key={control.id}
                      type="button"
                      onClick={() => setActiveTab("Warden")}
                      className={`rounded-2xl border ${border} ${subtle} p-4 text-left hover:opacity-95 transition-opacity`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-semibold">{control.title}</p>
                          <p className={`mt-1 text-xs ${muted}`}>{control.summary}</p>
                        </div>
                        <span className={`shrink-0 rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${statusClass(control.status)}`}>
                          {control.status}
                        </span>
                      </div>
                      <p className={`mt-3 text-[10px] font-mono uppercase ${muted}`}>
                        Owner: {ownerLabel(control)} · {control.earned}/{control.weight} pts
                      </p>
                    </button>
                  ))}
                </div>
              )}
            </section>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <motion.button
              type="button"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.05 }}
              onClick={() => setActiveTab("Identity")}
              className={`rounded-2xl border ${border} ${subtle} p-5 text-left hover:opacity-95 transition-opacity`}
            >
              <Key className="w-4 h-4 opacity-50 mb-3" />
              {loadJwt && !jwt ? (
                <Loader2 className="w-6 h-6 animate-spin opacity-30 my-2" />
              ) : errJwt || !jwt ? (
                <p className="text-sm opacity-40 font-mono">Unavailable</p>
              ) : (
                <>
                  <p className={`text-3xl font-bold font-mono ${fg}`}>
                    {jwt.passing}/{jwt.total}
                  </p>
                  <p className="text-[10px] font-mono uppercase opacity-40 mt-1">
                    JWT coverage
                  </p>
                  <div className="mt-2 flex justify-end">
                    {jwt.failing === 0 ? (
                      <CheckCircle className="w-5 h-5 text-emerald-400" />
                    ) : (
                      <XCircle className="w-5 h-5 text-rose-400" />
                    )}
                  </div>
                </>
              )}
            </motion.button>

            <motion.button
              type="button"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              onClick={() => setActiveTab("Identity")}
              className={`rounded-2xl border ${border} ${subtle} p-5 text-left hover:opacity-95 transition-opacity`}
            >
              <Server className="w-4 h-4 opacity-50 mb-3" />
              {loadRls && !rls ? (
                <Loader2 className="w-6 h-6 animate-spin opacity-30 my-2" />
              ) : errRls || !rls ? (
                <p className="text-sm opacity-40 font-mono">Unavailable</p>
              ) : (
                <>
                  <p className={`text-3xl font-bold font-mono ${fg}`}>
                    {rls.protected_tables ?? rls.rls_enabled}/{rls.total_tables}
                  </p>
                  <p className="text-[10px] font-mono uppercase opacity-40 mt-1">
                    RLS + FORCE coverage
                  </p>
                  <p className="text-xs font-mono opacity-50 mt-2">
                    {rls.total_tables
                      ? `${Math.round(((rls.protected_tables ?? rls.rls_enabled) / rls.total_tables) * 100)}% protected`
                      : "—"}
                  </p>
                </>
              )}
            </motion.button>

            <motion.button
              type="button"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.15 }}
              onClick={() => setActiveTab("Sweep")}
              className={`rounded-2xl border ${border} ${subtle} p-5 text-left hover:opacity-95 transition-opacity`}
            >
              <Lock className="w-4 h-4 opacity-50 mb-3" />
              {loadCerts && !certs ? (
                <Loader2 className="w-6 h-6 animate-spin opacity-30 my-2" />
              ) : errCerts || !certs?.length ? (
                <p className="text-sm opacity-40 font-mono">Unavailable</p>
              ) : (
                <>
                  <p className={`text-3xl font-bold font-mono ${certDayTextClass(shortestCertDays ?? 0)}`}>
                    {shortestCertDays}d
                  </p>
                  <p className="text-[10px] font-mono uppercase opacity-40 mt-1">
                    Sweep TLS shortest
                  </p>
                </>
              )}
            </motion.button>

            <motion.button
              type="button"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              onClick={() => setActiveTab("Network")}
              className={`rounded-2xl border ${border} ${subtle} p-5 text-left hover:opacity-95 transition-opacity`}
            >
              <Radio className="w-4 h-4 opacity-50 mb-3" />
              {loadPerimeter && !perimeter ? (
                <Loader2 className="w-6 h-6 animate-spin opacity-30 my-2" />
              ) : errPerimeter || !perimeter ? (
                <p className="text-sm opacity-40 font-mono">Unavailable</p>
              ) : (
                <>
                  <p className={`text-3xl font-bold font-mono ${fg}`}>
                    {perimeter.tailscale.node_count}
                  </p>
                  <p className="text-[10px] font-mono uppercase opacity-40 mt-1">
                    Network · Tailscale nodes
                  </p>
                  <p className="text-xs font-mono opacity-50 mt-2">
                    CORS {perimeter.cors.locked ? "locked" : "open"}
                  </p>
                </>
              )}
            </motion.button>

            <motion.button
              type="button"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.25 }}
              onClick={() => setActiveTab("Tripwire")}
              className={`rounded-2xl border ${border} ${subtle} p-5 text-left hover:opacity-95 transition-opacity`}
            >
              <Bug className="w-4 h-4 opacity-50 mb-3" />
              {loadHoneypot && !honeypotData ? (
                <Loader2 className="w-6 h-6 animate-spin opacity-30 my-2" />
              ) : errHoneypot || honeypotData === null ? (
                <p className="text-sm opacity-40 font-mono">Unavailable</p>
              ) : (
                <>
                  <p
                    className={`text-3xl font-bold font-mono tabular-nums ${
                      honeypotData.total === 0 ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    {honeypotData.total}
                  </p>
                  <p className={`text-xs font-mono ${muted} mt-0.5`}>hits detected</p>
                  <p className="text-[10px] font-mono uppercase opacity-40 mt-1">Tripwire</p>
                </>
              )}
            </motion.button>
          </div>
        </motion.div>
  );
}
