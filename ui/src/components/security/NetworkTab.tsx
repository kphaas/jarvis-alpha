import { motion } from 'framer-motion'
import { Users } from 'lucide-react'
import type { Perimeter, PortCheck } from '../../types/security'
import { SectionSkeleton, SectionUnavailable, type SecurityThemeProps } from './utils'

interface NetworkTabProps extends SecurityThemeProps {
  perimeter: Perimeter | null
  portsByNode: PortCheck[]
  loadPerimeter: boolean
  errPerimeter: boolean
}

export function NetworkTab({ isDark, border, subtle, fg, perimeter, portsByNode, loadPerimeter, errPerimeter }: NetworkTabProps) {
  return (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-8"
        >
          <section>
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
              CORS policy
            </p>
            {loadPerimeter && !perimeter ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errPerimeter || !perimeter ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : (
              <div className={`rounded-2xl border ${border} ${subtle} p-5 space-y-3`}>
                <div className="flex items-center gap-2">
                  {perimeter.cors.locked ? (
                    <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/15 text-emerald-400">
                      LOCKED
                    </span>
                  ) : (
                    <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border border-rose-500/30 bg-rose-500/15 text-rose-400">
                      OPEN
                    </span>
                  )}
                </div>
                <ul className="text-xs font-mono space-y-1 opacity-80">
                  {perimeter.cors.allowed_origins.map((o) => (
                    <li key={o}>{o}</li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          <section>
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
              Port scan
            </p>
            {loadPerimeter && !perimeter ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errPerimeter || !perimeter ? (
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
                        Port
                      </th>
                      <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                        Service
                      </th>
                      <th className="text-center px-2 py-2 font-mono uppercase opacity-40">
                        Reachable
                      </th>
                      <th className="text-center px-2 py-2 font-mono uppercase opacity-40">
                        Expected
                      </th>
                      <th className="text-center px-4 py-2 font-mono uppercase opacity-40">
                        Match
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {portsByNode.map((p) => {
                      const match = p.reachable === p.expected;
                      return (
                        <tr key={`${p.node}-${p.port}`}>
                          <td className="px-4 py-2 font-mono capitalize">{p.node}</td>
                          <td className="px-2 py-2 font-mono">{p.port}</td>
                          <td className="px-2 py-2 font-mono opacity-80">{p.service}</td>
                          <td className="px-2 py-2 text-center font-mono">
                            {p.reachable ? "yes" : "no"}
                          </td>
                          <td className="px-2 py-2 text-center font-mono">
                            {p.expected ? "yes" : "no"}
                          </td>
                          <td className="px-4 py-2 text-center">
                            {match ? (
                              <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/15 text-emerald-400">
                                MATCH
                              </span>
                            ) : (
                              <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border border-rose-500/30 bg-rose-500/15 text-rose-400">
                                MISMATCH
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section>
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
              Tailscale
            </p>
            {loadPerimeter && !perimeter ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errPerimeter || !perimeter ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : (
              <div className={`rounded-2xl border ${border} ${subtle} p-6 flex flex-col sm:flex-row sm:items-center gap-4`}>
                <div>
                  {perimeter.tailscale.active ? (
                    <span className="text-sm font-mono font-bold px-3 py-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/15 text-emerald-400">
                      ACTIVE
                    </span>
                  ) : (
                    <span className="text-sm font-mono font-bold px-3 py-1.5 rounded-lg border border-zinc-500/30 bg-zinc-500/15 text-zinc-400">
                      INACTIVE
                    </span>
                  )}
                </div>
                <div className={`font-mono text-sm ${fg}`}>
                  <Users className="w-4 h-4 inline mr-2 opacity-50" />
                  {perimeter.tailscale.node_count} nodes in tailnet
                </div>
              </div>
            )}
          </section>
        </motion.div>
  );
}
