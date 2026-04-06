import { motion } from 'framer-motion'
import type { McpRegistry } from '../../types/security'
import { SectionSkeleton, SectionUnavailable, type SecurityThemeProps } from './utils'

interface McpTabProps extends SecurityThemeProps {
  mcpRegistry: McpRegistry | null
  loadMcp: boolean
  errMcp: boolean
}

export function McpTab({ isDark, border, subtle, fg, muted, mcpRegistry, loadMcp, errMcp }: McpTabProps) {
  return (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-8"
        >
          <section>
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-2">
              MCP server registry
            </p>
            {loadMcp && !mcpRegistry ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errMcp || !mcpRegistry ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : (
              <p className={`text-sm font-mono ${fg}`}>
                <span className="text-emerald-400 font-bold">{mcpRegistry.active}</span> active ·{" "}
                <span className="opacity-70">{mcpRegistry.planned}</span> planned ·{" "}
                <span className="opacity-50">{mcpRegistry.total}</span> total
              </p>
            )}
          </section>

          <section>
            {!loadMcp && mcpRegistry && (
              <div className="space-y-4">
                {mcpRegistry.servers.map((s) => {
                  let statusBadge =
                    "border-zinc-500/30 bg-zinc-500/15 text-zinc-400";
                  if (s.status === "active") {
                    statusBadge = "border-emerald-500/30 bg-emerald-500/15 text-emerald-400";
                  } else if (s.status === "error") {
                    statusBadge = "border-rose-500/30 bg-rose-500/15 text-rose-400";
                  }
                  const endpointBadge = isDark
                    ? "border-blue-500/30 bg-blue-500/15 text-blue-400"
                    : "border-blue-600/30 bg-blue-500/10 text-blue-700";
                  return (
                    <div
                      key={s.id}
                      className={`rounded-2xl border ${border} ${subtle} p-5 space-y-3`}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <p className="font-bold">{s.name}</p>
                          <p className={`text-xs ${muted} mt-1 leading-relaxed`}>{s.description}</p>
                        </div>
                        <div className="flex flex-wrap gap-2 shrink-0">
                          <span
                            className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${statusBadge}`}
                          >
                            {s.status}
                          </span>
                          <span
                            className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${endpointBadge}`}
                          >
                            {s.endpoint}
                          </span>
                        </div>
                      </div>
                      <p className="text-xs font-mono text-blue-400/90 hover:underline cursor-default">
                        {s.backlog_ref}
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {s.permissions.map((perm) => (
                          <span
                            key={perm}
                            className={`text-[9px] font-mono px-2 py-0.5 rounded border ${
                              isDark
                                ? "border-white/10 bg-white/5 text-zinc-400"
                                : "border-[#141414]/15 bg-[#141414]/5 text-zinc-600"
                            }`}
                          >
                            {perm}
                          </span>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </motion.div>
  );
}
