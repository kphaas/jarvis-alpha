import { motion } from 'framer-motion'
import { CheckCircle, XCircle, Shield } from 'lucide-react'
import type { JwtCheck, RlsStatus, ChildProfileStatus } from '../../types/security'
import { SectionSkeleton, SectionUnavailable, type SecurityThemeProps } from './utils'

interface IdentityTabProps extends SecurityThemeProps {
  jwt: JwtCheck | null
  rls: RlsStatus | null
  child: ChildProfileStatus | null
  protectedTables: { table: string; rls: string; policy: string }[]
  unprotectedTables: { table: string; rls: string; policy: string }[]
  loadJwt: boolean
  loadRls: boolean
  loadChild: boolean
  errJwt: boolean
  errRls: boolean
  errChild: boolean
}

export function IdentityTab({
  isDark, border, subtle, muted,
  jwt, rls, child,
  protectedTables, unprotectedTables,
  loadJwt, loadRls, loadChild,
  errJwt, errRls, errChild,
}: IdentityTabProps) {
  return (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-8"
        >
          <section>
            <div className="flex items-center justify-between mb-3">
              <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest">
                JWT enforcement
              </p>
              {!loadJwt && jwt && (
                <span className="text-xs font-mono opacity-60">
                  {jwt.passing}/{jwt.total} routes enforced
                </span>
              )}
            </div>
            {loadJwt && !jwt ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errJwt || !jwt ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : (
              <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
                <table className="w-full text-xs">
                  <thead>
                    <tr className={isDark ? "bg-white/5" : "bg-black/5"}>
                      <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                        Route
                      </th>
                      <th className="text-center px-2 py-2 font-mono uppercase opacity-40">
                        Expected
                      </th>
                      <th className="text-center px-2 py-2 font-mono uppercase opacity-40">
                        Actual
                      </th>
                      <th className="text-center px-4 py-2 font-mono uppercase opacity-40">
                        Result
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {jwt.checks.map((c) => (
                      <tr key={c.route}>
                        <td className="px-4 py-2 font-mono">{c.route}</td>
                        <td className="px-2 py-2 text-center font-mono opacity-70">
                          {c.expected}
                        </td>
                        <td className="px-2 py-2 text-center font-mono">{c.actual}</td>
                        <td className="px-4 py-2 text-center">
                          {c.pass ? (
                            <CheckCircle className="w-4 h-4 text-emerald-400 inline-block" />
                          ) : (
                            <XCircle className="w-4 h-4 text-rose-400 inline-block" />
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section>
            <div className="flex items-center justify-between mb-3">
              <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest">
                RLS status
              </p>
              {!loadRls && rls && (
                <span className="text-xs font-mono opacity-60">
                  {rls.rls_enabled}/{rls.total_tables} tables with RLS
                </span>
              )}
            </div>
            {loadRls && !rls ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errRls || !rls ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : (
              <div className="space-y-6">
                <div>
                  <p className="text-[10px] font-mono uppercase opacity-50 mb-2">Protected</p>
                  <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
                    <table className="w-full text-xs">
                      <thead>
                        <tr className={isDark ? "bg-white/5" : "bg-black/5"}>
                          <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                            Table
                          </th>
                          <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                            RLS
                          </th>
                          <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                            Policy
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5">
                        {protectedTables.map((t) => (
                          <tr key={t.table}>
                            <td className="px-4 py-2 font-mono">{t.table}</td>
                            <td className="px-4 py-2">
                              <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/15 text-emerald-400">
                                enabled
                              </span>
                            </td>
                            <td className="px-4 py-2 font-mono opacity-80">{t.policy}</td>
                          </tr>
                        ))}
                        {protectedTables.length === 0 && (
                          <tr>
                            <td colSpan={3} className="px-4 py-4 text-center opacity-40 font-mono">
                              None
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
                <div>
                  <p className="text-[10px] font-mono uppercase opacity-50 mb-2">Unprotected</p>
                  <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
                    <table className="w-full text-xs">
                      <thead>
                        <tr className={isDark ? "bg-white/5" : "bg-black/5"}>
                          <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                            Table
                          </th>
                          <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                            RLS
                          </th>
                          <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                            Policy
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5">
                        {unprotectedTables.map((t) => (
                          <tr key={t.table}>
                            <td className="px-4 py-2 font-mono">{t.table}</td>
                            <td className="px-4 py-2">
                              <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border border-white/10 bg-white/5 text-zinc-400">
                                disabled
                              </span>
                            </td>
                            <td className="px-4 py-2 font-mono opacity-80">{t.policy}</td>
                          </tr>
                        ))}
                        {unprotectedTables.length === 0 && (
                          <tr>
                            <td colSpan={3} className="px-4 py-4 text-center opacity-40 font-mono">
                              None
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}
          </section>

          <section>
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
              Child profiles
            </p>
            {loadChild && !child ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errChild || !child ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {child.profiles.map((p) => (
                    <div
                      key={p.name}
                      className={`rounded-2xl border ${border} ${subtle} p-5 space-y-3`}
                    >
                      <div className="flex items-center gap-2">
                        <Shield className="w-4 h-4 text-emerald-400/80" />
                        <span className="font-bold">{p.name}</span>
                        <span className={`text-xs font-mono ${muted}`}>age {p.age}</span>
                      </div>
                      <div className="flex flex-wrap gap-2 text-[10px] font-mono">
                        <span
                          className={`px-2 py-0.5 rounded border ${
                            p.app_layer
                              ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-400"
                              : "border-rose-500/30 bg-rose-500/15 text-rose-400"
                          }`}
                        >
                          app_layer {p.app_layer ? "on" : "off"}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded border ${
                            p.db_layer
                              ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-400"
                              : "border-rose-500/30 bg-rose-500/15 text-rose-400"
                          }`}
                        >
                          db_layer {p.db_layer ? "on" : "off"}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded border ${
                            p.content_filter
                              ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-400"
                              : "border-rose-500/30 bg-rose-500/15 text-rose-400"
                          }`}
                        >
                          content_filter {p.content_filter ? "on" : "off"}
                        </span>
                      </div>
                      <p className={`text-xs ${muted} leading-relaxed`}>{p.notes}</p>
                    </div>
                  ))}
                </div>
                {child.overall !== "full" && (
                  <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200/90">
                    {child.recommendation}
                  </div>
                )}
              </div>
            )}
          </section>
        </motion.div>
  );
}
