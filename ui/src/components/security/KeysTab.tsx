import { motion } from 'framer-motion'
import { RotateCw, AlertTriangle, Shield, CheckCircle, XCircle, Loader2 } from 'lucide-react'
import type { KeyturnerStatus, RotatableKey, RotationResult, SecretAuditEvent } from '../../types/security'
import {
  SectionSkeleton, SectionUnavailable, relativeAccessedLabel,
  secretSourceBadgeClass, validateKeyFormat, type SecurityThemeProps,
} from './utils'

interface KeysTabProps extends SecurityThemeProps {
  rotatableKeys: RotatableKey[]
  secretsAuditEvents: SecretAuditEvent[]
  keyturnerStatus: KeyturnerStatus | null
  loadRotatableKeys: boolean
  loadSecretsAudit: boolean
  loadKeyturner: boolean
  errRotatableKeys: boolean
  errSecretsAudit: boolean
  errKeyturner: boolean
  rotatingKey: RotatableKey | null
  newKeyValue: string
  rotationLoading: boolean
  rotationResult: RotationResult | null
  formatError: string | null
  setRotatingKey: (key: RotatableKey | null) => void
  setNewKeyValue: (value: string) => void
  setFormatError: (error: string | null) => void
  setRotationResult: (result: RotationResult | null) => void
  closeRotationModal: () => void
  handleRotate: () => void
}

export function KeysTab({
  isDark, border, subtle, muted,
  rotatableKeys, secretsAuditEvents, keyturnerStatus,
  loadRotatableKeys, loadSecretsAudit, loadKeyturner,
  errRotatableKeys, errSecretsAudit, errKeyturner,
  rotatingKey, newKeyValue, rotationLoading, rotationResult, formatError,
  setRotatingKey, setNewKeyValue, setFormatError, setRotationResult,
  closeRotationModal, handleRotate,
}: KeysTabProps) {
  const keyturnerSummaryCards = keyturnerStatus ? [
    {
      title: 'OAuth health',
      value: `${keyturnerStatus.oauth_health.healthy}/${keyturnerStatus.oauth_health.managed}`,
      detail: `${keyturnerStatus.oauth_health.attention} need attention`,
      tone: keyturnerStatus.oauth_health.attention ? 'amber' : 'emerald',
    },
    {
      title: 'Rotation dry-run',
      value: `${keyturnerStatus.rotation_dry_run.runnable}`,
      detail: `${keyturnerStatus.rotation_dry_run.console_required} console · ${keyturnerStatus.rotation_dry_run.approval_gated} approval`,
      tone: keyturnerStatus.rotation_dry_run.blocked ? 'rose' : 'sky',
    },
    {
      title: 'Secrets forecast',
      value: `${keyturnerStatus.forecast.next_30_days}`,
      detail: `${keyturnerStatus.forecast.due} due · ${keyturnerStatus.forecast.next_7_days} next 7d`,
      tone: keyturnerStatus.forecast.due ? 'rose' : keyturnerStatus.forecast.next_7_days ? 'amber' : 'emerald',
    },
  ] : []
  const summaryToneClass = (tone: string) => {
    if (tone === 'rose') return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
    if (tone === 'amber') return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
    if (tone === 'sky') return 'border-sky-500/30 bg-sky-500/10 text-sky-300'
    return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  }

  return (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-8"
        >
          <section>
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-1">
              Keyturner rotation desk
            </p>
            <p className={`text-xs font-mono ${muted} mb-4`}>
              One agent owns approved key and password rotations; existing scripts remain the tested actuators.
            </p>
            <div className={`rounded-2xl border ${border} ${subtle} p-4 mb-4 text-xs leading-relaxed ${muted}`}>
              Keyturner handles cloud API keys, service tokens, admin PIN rotation, and manual DB-password
              rotation plans. Database passwords stay approval-gated because they require role changes,
              secret-file updates, service restarts, health checks, and rollback checkpoints.
            </div>
            {loadKeyturner && !keyturnerStatus ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errKeyturner || !keyturnerStatus ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : (
              <div className={`rounded-2xl border ${border} ${subtle} p-5 mb-4`}>
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-sm font-bold">{keyturnerStatus.display_name}</p>
                    <p className={`text-xs font-mono ${muted} mt-1`}>
                      {keyturnerStatus.counts.managed} managed · {keyturnerStatus.counts.approval_gated} approval-gated · {keyturnerStatus.mode}
                    </p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-center">
                    <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-3 py-2">
                      <p className="text-lg font-bold font-mono text-emerald-400">{keyturnerStatus.counts.healthy}</p>
                      <p className={`text-[9px] font-mono uppercase ${muted}`}>healthy</p>
                    </div>
                    <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2">
                      <p className="text-lg font-bold font-mono text-amber-300">{keyturnerStatus.counts.attention}</p>
                      <p className={`text-[9px] font-mono uppercase ${muted}`}>attention</p>
                    </div>
                  </div>
                </div>
                <div className="mt-4 grid grid-cols-1 gap-2">
                  <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                    {keyturnerSummaryCards.map((card) => (
                      <div key={card.title} className={`rounded-xl border px-3 py-3 ${summaryToneClass(card.tone)}`}>
                        <p className="text-[10px] font-mono font-bold uppercase opacity-70">{card.title}</p>
                        <p className="mt-1 text-xl font-bold font-mono">{card.value}</p>
                        <p className="mt-1 text-[10px] font-mono opacity-80">{card.detail}</p>
                      </div>
                    ))}
                  </div>
                  {keyturnerStatus.rotation_dry_run.blocked > 0 && (
                    <div className="rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                      {keyturnerStatus.rotation_dry_run.blocked} secret(s) are blocked from dry-run until their inventory or verification status is fixed.
                    </div>
                  )}
                  {keyturnerStatus.secrets.map((secret) => {
                    const statusClass = secret.status === "healthy"
                      ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-400"
                      : secret.status === "due_soon"
                        ? "border-amber-500/30 bg-amber-500/15 text-amber-300"
                        : "border-rose-500/30 bg-rose-500/15 text-rose-400";
                    return (
                      <div key={secret.secret_name} className={`rounded-xl border ${border} px-3 py-2`}>
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                          <div>
                            <p className="text-xs font-bold font-mono">{secret.secret_name}</p>
                            <p className={`text-[10px] font-mono ${muted}`}>
                              {secret.secret_class} · {secret.rotation_days}d cadence
                              {secret.next_due_at ? ` · due ${secret.next_due_at}` : ""}
                            </p>
                          </div>
                          <span className={`w-fit rounded border px-2 py-0.5 text-[10px] font-mono font-bold ${statusClass}`}>
                            {secret.status}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            {loadRotatableKeys && rotatableKeys.length === 0 ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errRotatableKeys && rotatableKeys.length === 0 ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : rotatableKeys.length === 0 ? (
              <div className={`rounded-2xl border ${border} ${subtle} p-6 text-sm font-mono opacity-50`}>
                No rotatable keys returned from API
              </div>
            ) : (
              <div className="space-y-3">
                {rotatableKeys.map((k) => (
                  <div
                    key={k.key_name}
                    className={`rounded-2xl border ${border} ${subtle} px-5 py-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3`}
                  >
                    <div>
                      <p className="font-bold text-sm">{k.provider}</p>
                      <p className={`text-xs font-mono ${muted} mt-0.5`}>{k.key_name}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        setRotatingKey(k);
                        setNewKeyValue("");
                        setFormatError(null);
                        setRotationResult(null);
                      }}
                      className={`inline-flex items-center justify-center gap-2 rounded-xl border ${border} px-4 py-2 text-xs font-mono font-bold hover:opacity-90 transition-opacity shrink-0`}
                    >
                      <RotateCw className="w-3.5 h-3.5" strokeWidth={2} />
                      Rotate
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section>
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
              Recent secret access
            </p>
            {loadSecretsAudit && secretsAuditEvents.length === 0 ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errSecretsAudit && secretsAuditEvents.length === 0 ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : secretsAuditEvents.length === 0 ? (
              <div className={`rounded-2xl border ${border} ${subtle} p-6 text-sm font-mono opacity-50`}>
                No secret access events recorded
              </div>
            ) : (
              <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
                <table className="w-full text-xs">
                  <thead>
                    <tr className={isDark ? "bg-white/5" : "bg-black/5"}>
                      <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                        Key name
                      </th>
                      <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                        Source
                      </th>
                      <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                        Accessed
                      </th>
                      <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                        Node
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {secretsAuditEvents.map((ev, i) => (
                      <tr key={`${ev.key}-${ev.accessed_at}-${i}`}>
                        <td className="px-4 py-2 font-mono">{ev.key}</td>
                        <td className="px-2 py-2">
                          <span
                            className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${secretSourceBadgeClass(ev.source, isDark)}`}
                          >
                            {ev.source}
                          </span>
                        </td>
                        <td className="px-2 py-2 font-mono opacity-80">
                          {relativeAccessedLabel(ev.accessed_at)}
                        </td>
                        <td className="px-4 py-2 font-mono opacity-80">{ev.node}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {rotatingKey && (
            <div
              role="presentation"
              className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
              onClick={closeRotationModal}
            >
              <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="rotation-modal-title"
                className={`w-full max-w-lg rounded-2xl border p-6 shadow-xl ${
                  isDark ? "border-white/10 bg-zinc-900" : "border-[#141414]/15 bg-white"
                }`}
                onClick={(e) => e.stopPropagation()}
              >
                {!rotationResult ? (
                  <>
                    <div className="flex items-center gap-2 mb-1">
                      <Shield className="w-5 h-5 text-emerald-400/90 shrink-0" />
                      <h2 id="rotation-modal-title" className="font-serif italic text-xl">
                        Rotate {rotatingKey.provider} key
                      </h2>
                    </div>
                    <p className={`text-xs font-mono ${muted} mb-3`}>
                      Paste your new API key from the {rotatingKey.provider} dashboard
                    </p>
                    <p className={`text-xs leading-relaxed ${muted} mb-4`}>
                      Keyturner will queue this as an approval-gated rotation. After approval,
                      submit the same key again to execute the tested Gateway rotation with rollback.
                    </p>
                    <label className="block text-[10px] font-mono uppercase opacity-50 mb-1.5">
                      New API key
                    </label>
                    <textarea
                      value={newKeyValue}
                      onChange={(e) => {
                        const v = e.target.value;
                        setNewKeyValue(v);
                        setFormatError(validateKeyFormat(rotatingKey, v));
                      }}
                      rows={3}
                      placeholder={`${rotatingKey.prefix}...`}
                      className={`w-full rounded-xl border font-mono text-sm p-3 resize-y min-h-[5rem] ${
                        isDark
                          ? "border-white/10 bg-black/30 text-white/90 placeholder:text-white/25"
                          : "border-[#141414]/15 bg-[#141414]/5 text-[#141414] placeholder:text-[#141414]/35"
                      }`}
                      disabled={rotationLoading}
                      autoComplete="off"
                      spellCheck={false}
                    />
                    <p className={`text-[10px] font-mono mt-2 ${muted}`}>
                      Expected prefix: {rotatingKey.prefix} · Min length: {rotatingKey.min_length}
                    </p>
                    {formatError && (
                      <p className="text-xs text-rose-400 mt-2 font-mono">{formatError}</p>
                    )}
                    {!formatError && newKeyValue.trim() !== "" && (
                      <p className="text-xs text-emerald-400 mt-2 font-mono flex items-center gap-1.5">
                        <CheckCircle className="w-3.5 h-3.5 shrink-0" />
                        Format valid
                      </p>
                    )}
                    <div className="flex flex-wrap items-center gap-3 mt-6">
                      <button
                        type="button"
                        onClick={closeRotationModal}
                        disabled={rotationLoading}
                        className={`rounded-xl border px-4 py-2 text-xs font-mono font-bold ${border} ${subtle} opacity-80 hover:opacity-100 disabled:opacity-40 disabled:cursor-not-allowed`}
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleRotate()}
                        disabled={
                          rotationLoading ||
                          !newKeyValue.trim() ||
                          Boolean(formatError) ||
                          Boolean(validateKeyFormat(rotatingKey, newKeyValue))
                        }
                        className="rounded-xl border border-amber-500/40 bg-amber-500/15 px-4 py-2 text-xs font-mono font-bold text-amber-200 hover:bg-amber-500/25 disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        {rotationLoading ? (
                          <span className="inline-flex items-center gap-2">
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            Asking Keyturner…
                          </span>
                        ) : (
                          "Request rotation"
                        )}
                      </button>
                    </div>
                    {rotationLoading && (
                      <p className={`text-[10px] font-mono ${muted} mt-3`}>
                        Sending request to Keyturner…
                      </p>
                    )}
                  </>
                ) : (
                  <div className="space-y-4">
                    {rotationResult.status === "success" && (
                      <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 space-y-2">
                        <div className="flex items-center gap-2 text-emerald-400 font-bold text-sm">
                          <CheckCircle className="w-5 h-5 shrink-0" />
                          Key rotated successfully
                        </div>
                        {rotationResult.old_key_health && (
                          <p className={`text-xs font-mono ${muted}`}>
                            Previous: {rotationResult.old_key_health}
                          </p>
                        )}
                        {rotationResult.new_key_health && (
                          <p className={`text-xs font-mono ${muted}`}>
                            New: {rotationResult.new_key_health}
                          </p>
                        )}
                      </div>
                    )}
                    {rotationResult.status === "approval_required" && (
                      <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 space-y-2">
                        <div className="flex items-center gap-2 text-amber-300 font-bold text-sm">
                          <AlertTriangle className="w-5 h-5 shrink-0" />
                          Keyturner approval queued
                        </div>
                        <p className={`text-xs font-mono ${muted}`}>
                          Approve the queued request, then submit this same key again to execute the rotation.
                        </p>
                        {rotationResult.approval_queue_id && (
                          <p className={`text-[10px] font-mono ${muted}`}>
                            Queue: {rotationResult.approval_queue_id}
                          </p>
                        )}
                      </div>
                    )}
                    {rotationResult.status === "rolled_back" && (
                      <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 space-y-2">
                        <div className="flex items-center gap-2 text-amber-300 font-bold text-sm">
                          <AlertTriangle className="w-5 h-5 shrink-0" />
                          Rotation rolled back — old key restored
                        </div>
                        {rotationResult.error && (
                          <p className="text-xs font-mono text-amber-200/90">{rotationResult.error}</p>
                        )}
                      </div>
                    )}
                    {rotationResult.status !== "success" && rotationResult.status !== "rolled_back" && rotationResult.status !== "approval_required" && (
                      <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 space-y-2">
                        <div className="flex items-center gap-2 text-rose-400 font-bold text-sm">
                          <XCircle className="w-5 h-5 shrink-0" />
                          Rotation failed
                        </div>
                        {rotationResult.error && (
                          <p className="text-xs font-mono text-rose-200/90">{rotationResult.error}</p>
                        )}
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={closeRotationModal}
                      className={`rounded-xl border px-4 py-2 text-xs font-mono font-bold ${border} ${subtle} w-full sm:w-auto`}
                    >
                      Close
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
        </motion.div>
  );
}
