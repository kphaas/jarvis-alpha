import { motion } from 'framer-motion'
import { AlertTriangle, CheckCircle, Clock, Loader2, Play, XCircle } from 'lucide-react'
import type { PorchlightCheck, PorchlightReport } from '../../types/security'
import { SectionSkeleton, SectionUnavailable, relativeAccessedLabel, type SecurityThemeProps } from './utils'

interface PorchlightTabProps extends SecurityThemeProps {
  report: PorchlightReport | null
  loadPorchlight: boolean
  errPorchlight: boolean
  runLoading: boolean
  runError: string | null
  onRun: () => void
}

function statusClass(status: string): string {
  if (status === 'pass') return 'border-emerald-500/30 bg-emerald-500/15 text-emerald-400'
  if (status === 'warn') return 'border-amber-500/30 bg-amber-500/15 text-amber-300'
  return 'border-rose-500/30 bg-rose-500/15 text-rose-400'
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'pass') return <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0" />
  if (status === 'warn') return <AlertTriangle className="w-4 h-4 text-amber-300 shrink-0" />
  return <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function proofEntries(value: unknown): Array<[string, string]> {
  return Object.entries(asRecord(value)).map(([key, raw]) => {
    if (Array.isArray(raw)) return [key, raw.join(', ')]
    if (typeof raw === 'string') {
      const parsed = Date.parse(raw)
      return [key, Number.isNaN(parsed) ? raw : new Date(parsed).toLocaleString()]
    }
    return [key, String(raw)]
  })
}

function PorchlightProof({ check, muted }: { check: PorchlightCheck; muted: string }) {
  const metadata = asRecord(check.metadata)
  const tokenRecent = check.name === 'token_rotation_logs' ? proofEntries(metadata.recent) : []
  const loadedByNode = check.name === 'security_launchagents' ? proofEntries(metadata.loaded_by_node) : []
  const skippedRemote = proofEntries(metadata.skipped_remote)
  const proof = tokenRecent.length ? tokenRecent : loadedByNode

  if (!proof.length && !skippedRemote.length) return null

  return (
    <div className={`mt-3 grid grid-cols-1 gap-2 text-[11px] font-mono ${muted}`}>
      {proof.length > 0 && (
        <div className="rounded-xl border border-white/10 bg-black/10 px-3 py-2">
          <p className="mb-1 text-[9px] uppercase opacity-50">remote proof</p>
          <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
            {proof.map(([node, value]) => (
              <div key={node} className="min-w-0">
                <span className="font-bold opacity-80">{node}</span>
                <span className="opacity-50"> · </span>
                <span className="break-words">{value}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {skippedRemote.length > 0 && (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-amber-200">
          <p className="mb-1 text-[9px] uppercase opacity-70">not probed</p>
          {skippedRemote.map(([node, value]) => (
            <div key={node}>{node} · {value}</div>
          ))}
        </div>
      )}
    </div>
  )
}

export function PorchlightTab({
  border, subtle, fg, muted,
  report, loadPorchlight, errPorchlight, runLoading, runError, onRun,
}: PorchlightTabProps) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-8">
      <section>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between mb-4">
          <div>
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-1">
              Porchlight security sweep
            </p>
            <p className={`text-xs font-mono ${muted}`}>
              Read-only posture checks with Mattermost alerts for dangerous findings.
            </p>
          </div>
          <button
            type="button"
            onClick={onRun}
            disabled={runLoading}
            className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border ${border} ${subtle} px-4 py-2 text-xs font-mono font-bold hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50`}
          >
            {runLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            {runLoading ? 'Running' : 'Run now'}
          </button>
        </div>

        {runError && (
          <div className="mb-4 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-xs font-mono text-rose-300">
            {runError}
          </div>
        )}

        {loadPorchlight && !report ? (
          <SectionSkeleton border={border} subtle={subtle} />
        ) : errPorchlight || !report ? (
          <SectionUnavailable border={border} subtle={subtle} />
        ) : (
          <div className={`rounded-2xl border ${border} ${subtle} p-5`}>
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                <StatusIcon status={report.status} />
                <div>
                  <p className={`text-2xl font-bold font-mono ${fg}`}>{report.status.toUpperCase()}</p>
                  <p className={`text-xs font-mono ${muted}`}>
                    Severity {report.severity} · {relativeAccessedLabel(report.generated_at)}
                  </p>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-3 py-2">
                  <p className="text-lg font-bold font-mono text-emerald-400">{report.counts.passing}</p>
                  <p className={`text-[9px] font-mono uppercase ${muted}`}>pass</p>
                </div>
                <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2">
                  <p className="text-lg font-bold font-mono text-amber-300">{report.counts.warning}</p>
                  <p className={`text-[9px] font-mono uppercase ${muted}`}>warn</p>
                </div>
                <div className="rounded-xl border border-rose-500/20 bg-rose-500/10 px-3 py-2">
                  <p className="text-lg font-bold font-mono text-rose-400">{report.counts.failing}</p>
                  <p className={`text-[9px] font-mono uppercase ${muted}`}>fail</p>
                </div>
              </div>
            </div>
            <div className={`mt-4 flex items-center gap-2 text-xs font-mono ${muted}`}>
              <Clock className="w-3.5 h-3.5" />
              Generated {new Date(report.generated_at).toLocaleString()}
            </div>
          </div>
        )}
      </section>

      {report && (
        <section>
          <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
            Checks
          </p>
          <div className="grid grid-cols-1 gap-3">
            {report.checks.map((check) => (
              <div key={check.name} className={`rounded-2xl border ${border} ${subtle} p-4`}>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <StatusIcon status={check.status} />
                      <p className="font-bold text-sm">{check.name}</p>
                    </div>
                    <p className={`mt-2 text-sm ${fg}`}>{check.summary}</p>
                    {check.detail && (
                      <p className={`mt-2 text-xs font-mono leading-relaxed ${muted}`}>{check.detail}</p>
                    )}
                    <PorchlightProof check={check} muted={muted} />
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    <span className={`rounded border px-2 py-0.5 text-[10px] font-mono font-bold ${statusClass(check.status)}`}>
                      {check.status}
                    </span>
                    <span className={`rounded border px-2 py-0.5 text-[10px] font-mono font-bold ${statusClass(check.status)}`}>
                      {check.severity}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </motion.div>
  )
}
