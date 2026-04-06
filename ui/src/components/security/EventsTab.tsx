import { motion } from 'framer-motion'
import { Shield } from 'lucide-react'
import type { LogEntry } from '../../types/security'
import { SectionSkeleton, SectionUnavailable, type SecurityThemeProps } from './utils'

interface EventsTabProps extends SecurityThemeProps {
  logEntries: LogEntry[]
  loadLogs: boolean
  errLogs: boolean
}

export function EventsTab({ isDark, border, subtle, muted, logEntries, loadLogs, errLogs }: EventsTabProps) {
  return (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
          <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
            Recent auth & security events
          </p>
          {loadLogs ? (
            <SectionSkeleton border={border} subtle={subtle} />
          ) : errLogs ? (
            <SectionUnavailable border={border} subtle={subtle} />
          ) : logEntries.length === 0 ? (
            <div
              className={`rounded-2xl border ${border} ${subtle} p-10 flex flex-col items-center gap-3 text-center`}
            >
              <Shield className="w-10 h-10 text-emerald-400/60" />
              <p className={`text-sm font-mono ${muted}`}>No recent security events</p>
            </div>
          ) : (
            <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
              <table className="w-full text-xs">
                <thead>
                  <tr className={isDark ? "bg-white/5" : "bg-black/5"}>
                    <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                      Timestamp
                    </th>
                    <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                      Level
                    </th>
                    <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                      Service
                    </th>
                    <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                      Message
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {logEntries.map((e, i) => {
                    const lv = (e.level || "").toUpperCase();
                    let badgeClass =
                      "border-zinc-500/30 bg-zinc-500/15 text-zinc-400";
                    if (lv === "WARNING") {
                      badgeClass = "border-amber-500/30 bg-amber-500/15 text-amber-400";
                    }
                    if (lv === "ERROR" || lv === "CRITICAL") {
                      badgeClass = "border-rose-500/30 bg-rose-500/15 text-rose-400";
                    }
                    const pulse = lv === "CRITICAL" ? " animate-pulse" : "";
                    return (
                      <tr key={`${e.ts}-${i}`}>
                        <td className="px-4 py-2 font-mono whitespace-nowrap opacity-70">
                          {e.ts || "—"}
                        </td>
                        <td className="px-2 py-2">
                          <span
                            className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${badgeClass}${pulse}`}
                          >
                            {e.level || "—"}
                          </span>
                        </td>
                        <td className="px-2 py-2 font-mono opacity-80">{e.service}</td>
                        <td className="px-4 py-2 font-mono opacity-90 break-all max-w-md">
                          {e.message}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </motion.div>
  );
}
