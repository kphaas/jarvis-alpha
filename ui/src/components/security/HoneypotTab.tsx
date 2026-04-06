import { motion } from 'framer-motion'
import { Shield } from 'lucide-react'
import type { HoneypotData } from '../../types/security'
import { SectionSkeleton, SectionUnavailable, relativeAccessedLabel, type SecurityThemeProps } from './utils'

const HONEYPOT_TRAP_CARDS: { path: string; trapType: string; description: string }[] = [
  { path: "/admin", trapType: "admin_panel", description: "Fake admin login panel" },
  { path: "/wp-login.php", trapType: "wordpress", description: "WordPress login decoy" },
  { path: "/.env", trapType: "env_file", description: "Fake environment file with dummy credentials" },
  { path: "/.git/config", trapType: "git_config", description: "Fake git repository config" },
  { path: "/phpmyadmin", trapType: "phpmyadmin", description: "phpMyAdmin login decoy" },
  { path: "/api/v1/debug", trapType: "debug_api", description: "Fake debug endpoint with dummy tokens" },
]

interface HoneypotTabProps extends SecurityThemeProps {
  honeypotData: HoneypotData | null
  loadHoneypot: boolean
  errHoneypot: boolean
}

export function HoneypotTab({ isDark, border, subtle, muted, honeypotData, loadHoneypot, errHoneypot }: HoneypotTabProps) {
  return (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-8"
        >
          <section>
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-4">
              Active honeypot traps
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {HONEYPOT_TRAP_CARDS.map((t) => (
                <div
                  key={t.path}
                  className={`rounded-2xl border ${border} ${subtle} p-5 space-y-2`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-mono font-bold text-sm break-all">{t.path}</p>
                    <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/15 text-emerald-400 shrink-0">
                      ARMED
                    </span>
                  </div>
                  <p className="text-[10px] font-mono uppercase opacity-50">{t.trapType}</p>
                  <p className={`text-xs ${muted} leading-relaxed`}>{t.description}</p>
                </div>
              ))}
            </div>
          </section>

          <section>
            <div className="flex items-center justify-between mb-3">
              <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest">
                Recent hits
              </p>
              {!loadHoneypot && honeypotData && (
                <span className="text-xs font-mono opacity-60">Total: {honeypotData.total}</span>
              )}
            </div>
            {loadHoneypot && !honeypotData ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errHoneypot || !honeypotData ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : honeypotData.events.length === 0 ? (
              <div
                className={`rounded-2xl border ${border} ${subtle} p-10 flex flex-col items-center gap-3 text-center`}
              >
                <Shield className="w-10 h-10 text-emerald-400/60" />
                <p className={`text-sm font-mono ${muted}`}>No suspicious activity detected</p>
              </div>
            ) : (
              <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
                <table className="w-full text-xs">
                  <thead>
                    <tr className={isDark ? "bg-white/5" : "bg-black/5"}>
                      <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                        Timestamp
                      </th>
                      <th className="text-left px-2 py-2 font-mono uppercase opacity-40">Path</th>
                      <th className="text-center px-2 py-2 font-mono uppercase opacity-40">
                        Method
                      </th>
                      <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                        Client IP
                      </th>
                      <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                        User agent
                      </th>
                      <th className="text-left px-4 py-2 font-mono uppercase opacity-40">Trap</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {honeypotData.events.map((ev, i) => {
                      const m = (ev.method || "GET").toUpperCase();
                      const methodBadge =
                        m === "POST"
                          ? isDark
                            ? "border-amber-500/30 bg-amber-500/15 text-amber-400"
                            : "border-amber-600/30 bg-amber-500/10 text-amber-700"
                          : isDark
                            ? "border-blue-500/30 bg-blue-500/15 text-blue-400"
                            : "border-blue-600/30 bg-blue-500/10 text-blue-700";
                      const ua =
                        ev.user_agent && ev.user_agent.length > 50
                          ? `${ev.user_agent.slice(0, 50)}…`
                          : ev.user_agent || "—";
                      return (
                        <tr key={`${ev.ts}-${ev.path}-${i}`}>
                          <td className="px-4 py-2 font-mono whitespace-nowrap opacity-80">
                            {relativeAccessedLabel(ev.ts)}
                          </td>
                          <td className="px-2 py-2 font-mono break-all max-w-[120px]">{ev.path}</td>
                          <td className="px-2 py-2 text-center">
                            <span
                              className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${methodBadge}`}
                            >
                              {m}
                            </span>
                          </td>
                          <td className="px-2 py-2 font-mono opacity-80">{ev.client_ip}</td>
                          <td className="px-2 py-2 font-mono opacity-70 max-w-[200px] break-all">
                            {ua}
                          </td>
                          <td className="px-4 py-2">
                            <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border border-zinc-500/30 bg-zinc-500/15 text-zinc-400">
                              {ev.trap_type}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </motion.div>
  );
}
