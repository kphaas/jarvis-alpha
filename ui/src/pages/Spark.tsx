import { motion } from "framer-motion"
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  LoaderCircle,
  MessageSquareText,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from "lucide-react"
import { useSearchParams } from "react-router-dom"
import { SparkGuardrailsPanel } from "../components/spark/SparkGuardrailsPanel"
import { useSparkDraftReview } from "../hooks/useSparkDraftReview"
import { useAppStore } from "../store"
import type { SparkIMessageDraftResponse } from "../types/spark"

function tone(isDark: boolean, variant: "ok" | "warn" | "error") {
  if (variant === "ok") {
    return isDark
      ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200"
      : "border-emerald-700/30 bg-emerald-50 text-emerald-800"
  }
  if (variant === "warn") {
    return isDark
      ? "border-amber-400/30 bg-amber-500/10 text-amber-200"
      : "border-amber-700/30 bg-amber-50 text-amber-800"
  }
  return isDark
    ? "border-rose-400/30 bg-rose-500/10 text-rose-200"
    : "border-rose-700/30 bg-rose-50 text-rose-800"
}

function shortHash(value: string) {
  return `${value.slice(0, 10)}...${value.slice(-8)}`
}

function ErrorLine({ text, className }: { text: string; className: string }) {
  return (
    <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${className}`}>
      <AlertTriangle className="h-4 w-4 shrink-0" />
      <span>{text}</span>
    </div>
  )
}

function StatusChip({
  label,
  className,
}: {
  label: string
  className: string
}) {
  return (
    <span className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${className}`}>
      {label}
    </span>
  )
}

function MetricRow({
  label,
  value,
  muted,
}: {
  label: string
  value: string | number
  muted: string
}) {
  return (
    <div className="flex min-h-11 items-center justify-between gap-3 border-b border-current/10 py-2 last:border-b-0">
      <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
        {label}
      </span>
      <span className="min-w-0 truncate text-right text-sm font-semibold">{value}</span>
    </div>
  )
}

function DraftMetadata({
  draft,
  muted,
}: {
  draft: SparkIMessageDraftResponse
  muted: string
}) {
  return (
    <div className="space-y-1">
      <MetricRow label="Context read" value={draft.context_messages_read} muted={muted} />
      <MetricRow label="Sent examples" value={draft.principal_sent_messages} muted={muted} />
      <MetricRow label="Runtime context" value={draft.runtime_context_messages} muted={muted} />
      <MetricRow label="Approval hash" value={shortHash(draft.approval_ref_hash)} muted={muted} />
      <MetricRow label="Thread hash" value={shortHash(draft.chat_guid_hash)} muted={muted} />
    </div>
  )
}

export default function Spark() {
  const { theme } = useAppStore()
  const [searchParams] = useSearchParams()
  const activeApproval = searchParams.get("approval")
  const state = useSparkDraftReview()
  const isDark = theme === "dark"
  const border = isDark ? "border-white/10" : "border-[#141414]/10"
  const panel = isDark ? "bg-white/5" : "bg-[#141414]/5"
  const input = isDark
    ? "bg-[#0A0A0A] border-white/10"
    : "bg-[#E4E3E0] border-[#141414]/15"
  const muted = isDark ? "text-white/45" : "text-[#141414]/50"
  const strong = isDark ? "text-white" : "text-[#141414]"
  const okClass = tone(isDark, "ok")
  const warnClass = tone(isDark, "warn")
  const errorClass = tone(isDark, "error")

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className="max-w-6xl space-y-6"
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex items-center gap-3">
          <div
            className={`flex h-10 w-10 items-center justify-center rounded-lg border ${border} ${panel}`}
          >
            <Sparkles className="h-5 w-5 text-emerald-400" />
          </div>
          <div>
            <h1 className={`font-serif italic text-3xl ${strong}`}>Spark</h1>
            <p className={`mt-1 text-[10px] font-mono uppercase tracking-widest ${muted}`}>
              iMessage draft review
            </p>
          </div>
        </div>
        <div
          className={`grid min-w-64 grid-cols-3 overflow-hidden rounded-lg border text-center text-[10px] font-mono uppercase ${border}`}
        >
          <div className={`px-3 py-2 ${panel}`}>draft only</div>
          <div className={`border-x px-3 py-2 ${border}`}>local</div>
          <div className={`px-3 py-2 ${panel}`}>approval</div>
        </div>
      </div>

      {activeApproval && (
        <div className={`rounded-lg border px-3 py-2 text-sm ${okClass}`}>
          Approval queue {activeApproval}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <section className={`rounded-xl border ${border} ${panel} p-5`}>
          <div className="flex items-center gap-2">
            <MessageSquareText className="h-4 w-4 text-emerald-400" />
            <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>
              Request
            </h2>
          </div>
          <div className="mt-4 space-y-4">
            <label className="block">
              <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
                Reply goal
              </span>
              <textarea
                value={state.replyGoal}
                onChange={(event) => state.setReplyGoal(event.target.value)}
                rows={6}
                maxLength={1000}
                className={`mt-2 w-full resize-y rounded-lg border p-3 text-sm outline-none transition focus:border-emerald-400 ${input}`}
              />
            </label>
            <label className="block">
              <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
                Context messages
              </span>
              <div className="mt-2 flex items-center gap-3">
                <input
                  type="range"
                  min={1}
                  max={50}
                  value={state.maxContextMessages}
                  onChange={(event) => state.setMaxContextMessages(Number(event.target.value))}
                  className="min-w-0 flex-1"
                />
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={state.maxContextMessages}
                  onChange={(event) => state.setMaxContextMessages(Number(event.target.value))}
                  className={`h-11 w-20 rounded-lg border px-3 text-sm ${input}`}
                />
              </div>
            </label>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={state.generateDraft}
                disabled={state.draftLoading}
                className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-emerald-600 px-4 text-sm font-bold text-white transition hover:bg-emerald-500 disabled:opacity-45"
              >
                {state.draftLoading ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                Generate draft
              </button>
              <button
                type="button"
                onClick={state.submitForApproval}
                disabled={!state.canSubmitForApproval}
                className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-4 text-sm font-bold transition ${border} ${
                  state.canSubmitForApproval
                    ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300"
                    : "opacity-45"
                }`}
              >
                {state.approvalLoading ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <ShieldCheck className="h-4 w-4" />
                )}
                Submit approval
              </button>
            </div>
            {state.draftError && (
              <ErrorLine text="Draft route unavailable" className={errorClass} />
            )}
            {state.approvalError && (
              <ErrorLine text="Approval handoff failed" className={errorClass} />
            )}
            {state.approval && (
              <div className={`rounded-lg border px-3 py-2 text-sm ${okClass}`}>
                Approval queued {state.approval.queue_id}
              </div>
            )}
          </div>
        </section>

        <section className={`rounded-xl border ${border} ${panel} p-5`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Copy className="h-4 w-4 text-emerald-400" />
              <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>
                Draft
              </h2>
            </div>
            <div className="flex flex-wrap gap-2">
              <StatusChip label="no send" className={warnClass} />
              <StatusChip label="runtime only" className={okClass} />
              <StatusChip label="human gate" className={okClass} />
            </div>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(260px,0.75fr)]">
            <label className="block">
              <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
                Draft text
              </span>
              <textarea
                value={state.draftText}
                onChange={(event) => state.setDraftText(event.target.value)}
                rows={14}
                maxLength={4000}
                className={`mt-2 w-full resize-y rounded-lg border p-3 text-sm outline-none transition focus:border-emerald-400 ${input}`}
              />
            </label>
            <div className="space-y-4">
              {state.draft ? (
                <>
                  <DraftMetadata draft={state.draft} muted={muted} />
                  <div className="flex flex-wrap gap-2">
                    {state.draft.warnings.map((warning) => (
                      <StatusChip key={warning} label={warning.replace(/_/g, " ")} className={warnClass} />
                    ))}
                  </div>
                </>
              ) : (
                <div className={`flex min-h-40 items-center justify-center rounded-lg border ${border}`}>
                  <span className={`text-sm ${muted}`}>No draft loaded</span>
                </div>
              )}
              {state.approval && (
                <div className={`space-y-2 rounded-lg border p-3 ${border}`}>
                  <div className="flex items-center gap-2 text-sm">
                    <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                    <span className="font-semibold">{state.approval.approval_status}</span>
                  </div>
                  <MetricRow label="Queue ID" value={state.approval.queue_id} muted={muted} />
                </div>
              )}
            </div>
          </div>
        </section>
      </div>

      <SparkGuardrailsPanel
        border={border}
        panel={panel}
        input={input}
        muted={muted}
        okClass={okClass}
        warnClass={warnClass}
        errorClass={errorClass}
      />
    </motion.div>
  )
}
