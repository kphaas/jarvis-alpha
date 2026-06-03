import { motion } from 'framer-motion'
import { Archive, CheckCircle, FileClock, Fingerprint, ShieldAlert } from 'lucide-react'
import type { WardenAgent, WardenStatus } from '../../types/security'
import { SectionSkeleton, SectionUnavailable, relativeAccessedLabel, type SecurityThemeProps } from './utils'

interface LedgerTabProps extends SecurityThemeProps {
  wardenStatus: WardenStatus | null
  loadWarden: boolean
  errWarden: boolean
}

function asStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function ledgerAgent(status: WardenStatus | null): WardenAgent | null {
  return status?.agents.find((agent) => agent.agent_id === 'ledger') ?? null
}

function labelize(value: string): string {
  return value.replaceAll('_', ' ')
}

export function LedgerTab({
  border, subtle, fg, muted, wardenStatus, loadWarden, errWarden,
}: LedgerTabProps) {
  const ledger = ledgerAgent(wardenStatus)
  const capabilities = asStrings(ledger?.metadata.capabilities)
  const evidenceSources = asStrings(ledger?.metadata.evidence_sources)

  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-8">
      <section>
        <p className="mb-1 text-[10px] font-mono uppercase opacity-40 tracking-widest">
          Ledger evidence agent
        </p>
        {loadWarden && !wardenStatus ? (
          <SectionSkeleton border={border} subtle={subtle} />
        ) : errWarden || !wardenStatus || !ledger ? (
          <SectionUnavailable border={border} subtle={subtle} />
        ) : (
          <div className={`rounded-2xl border ${border} ${subtle} p-5`}>
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Archive className="h-5 w-5 shrink-0 text-violet-400" />
                  <p className={`text-2xl font-bold ${fg}`}>{ledger.display_name}</p>
                  <span className={`rounded border px-2 py-0.5 text-[10px] font-mono uppercase ${
                    ledger.needs_attention
                      ? 'border-amber-500/30 bg-amber-500/15 text-amber-300'
                      : 'border-emerald-500/30 bg-emerald-500/15 text-emerald-400'
                  }`}>
                    {ledger.needs_attention ? 'attention' : ledger.status}
                  </span>
                </div>
                <p className={`mt-2 max-w-2xl text-sm ${fg}`}>{ledger.purpose}</p>
                <p className={`mt-3 text-xs font-mono ${muted}`}>
                  {String(ledger.metadata.report_mode ?? 'tamper_evident').replaceAll('_', ' ')} · risk {ledger.risk_tier} · remediation {String(ledger.metadata.remediation ?? 'evidence_only').replaceAll('_', ' ')}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-2 text-center sm:min-w-56">
                <div className="rounded-xl border border-violet-500/20 bg-violet-500/10 px-3 py-2">
                  <p className="text-lg font-bold font-mono text-violet-300">{capabilities.length}</p>
                  <p className={`text-[9px] font-mono uppercase ${muted}`}>capabilities</p>
                </div>
                <div className="rounded-xl border border-sky-500/20 bg-sky-500/10 px-3 py-2">
                  <p className="text-lg font-bold font-mono text-sky-300">{evidenceSources.length}</p>
                  <p className={`text-[9px] font-mono uppercase ${muted}`}>sources</p>
                </div>
              </div>
            </div>
            <div className={`mt-4 flex items-center gap-2 text-xs font-mono ${muted}`}>
              <FileClock className="h-3.5 w-3.5" />
              Last run {ledger.last_run_at ? relativeAccessedLabel(ledger.last_run_at) : 'not recorded yet'}
            </div>
          </div>
        )}
      </section>

      {ledger && (
        <section>
          <p className="mb-3 text-[10px] font-mono uppercase opacity-40 tracking-widest">
            Evidence coverage
          </p>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {capabilities.map((capability) => (
              <div key={capability} className={`rounded-2xl border ${border} ${subtle} p-4`}>
                <div className="flex items-start gap-3">
                  <Fingerprint className="mt-0.5 h-4 w-4 shrink-0 text-violet-400" />
                  <div className="min-w-0">
                    <p className="text-sm font-bold capitalize">{labelize(capability)}</p>
                    <p className={`mt-1 text-xs ${muted}`}>Saved as a Ledger reporting capability for Warden-reviewed evidence packages.</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {ledger && (
        <section>
          <p className="mb-3 text-[10px] font-mono uppercase opacity-40 tracking-widest">
            Evidence sources
          </p>
          <div className={`rounded-2xl border ${border} ${subtle} p-4`}>
            <div className="flex flex-wrap gap-2">
              {evidenceSources.map((source) => (
                <span key={source} className="inline-flex items-center gap-1 rounded-full border border-violet-500/25 bg-violet-500/10 px-2 py-1 text-[10px] font-mono text-violet-300">
                  <CheckCircle className="h-3 w-3" />
                  {source}
                </span>
              ))}
            </div>
            <div className="mt-4 rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              <ShieldAlert className="mr-1 inline h-3.5 w-3.5" />
              Ledger is report-only today. It does not rotate keys, change Cloudflare, or modify family access.
            </div>
          </div>
        </section>
      )}
    </motion.div>
  )
}
