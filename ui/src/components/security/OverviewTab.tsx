import { motion } from 'framer-motion'
import { Key, Lock, CheckCircle, XCircle, Loader2, Server, Radio, Bug } from 'lucide-react'
import type { JwtCheck, RlsStatus, Perimeter, HoneypotData, CertRow } from '../../types/security'
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
  setActiveTab: (tab: string) => void
}

export function OverviewTab({
  isDark, border, subtle, fg, muted,
  jwt, rls, perimeter, certs, honeypotData,
  loadJwt, loadRls, loadPerimeter, loadCerts, loadChild, loadHoneypot,
  errJwt, errRls, errPerimeter, errCerts, errHoneypot,
  displayScore, reserved, dashEarned, strokeColor,
  checksPassing, checksTotal, shortestCertDays, setActiveTab,
}: OverviewTabProps) {
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
            <p className={`text-[10px] font-mono ${muted} text-center max-w-md`}>
              <span className="opacity-70">{reserved} pts reserved</span> (secrets audit, key rotation, future checks) —{" "}
              <span className="text-zinc-500">locked</span>
            </p>
          </section>

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
                    {rls.rls_enabled}/{rls.total_tables}
                  </p>
                  <p className="text-[10px] font-mono uppercase opacity-40 mt-1">
                    RLS coverage
                  </p>
                  <p className="text-xs font-mono opacity-50 mt-2">
                    {rls.total_tables
                      ? `${Math.round((rls.rls_enabled / rls.total_tables) * 100)}% protected`
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
              onClick={() => setActiveTab("Certs")}
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
                    TLS certs (shortest)
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
              onClick={() => setActiveTab("Honeypot")}
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
                  <p className="text-[10px] font-mono uppercase opacity-40 mt-1">Honeypot</p>
                </>
              )}
            </motion.button>
          </div>
        </motion.div>
  );
}
