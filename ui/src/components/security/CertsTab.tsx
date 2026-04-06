import { motion } from 'framer-motion'
import type { CertRow } from '../../types/security'
import { SectionSkeleton, SectionUnavailable, certDayTextClass, certBarPct, certBarColor, type SecurityThemeProps } from './utils'

interface CertsTabProps extends SecurityThemeProps {
  certs: CertRow[] | null
  sortedCerts: CertRow[]
  loadCerts: boolean
  errCerts: boolean
}

export function CertsTab({ isDark, border, subtle, certs, sortedCerts, loadCerts, errCerts }: CertsTabProps) {
  return (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
          <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
            TLS certificates
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
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </motion.div>
  );
}
