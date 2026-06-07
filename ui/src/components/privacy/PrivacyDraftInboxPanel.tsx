import { Archive, CheckCircle2, Inbox, LoaderCircle, RefreshCw } from "lucide-react";
import type { PrivacyDraftInboxState } from "../../hooks/usePrivacyDraftInbox";
import { TARGET_METHOD_LABEL } from "../../types/privacy";
import { KeyValue, StatusLine } from "./PrivacyFields";

function chipClass(isDark: boolean) {
  return isDark
    ? "border-white/10 bg-white/5 text-white/70"
    : "border-[#141414]/10 bg-[#141414]/5 text-[#4A4741]";
}

function shortId(id: string) {
  return id.slice(0, 8);
}

function formatDate(value: string | null) {
  if (!value) return "unknown";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function caseStatusLabel(status: string) {
  if (status === "draft") return "Draft";
  if (status === "submitted_for_approval") return "In workflow";
  if (status === "completed") return "Completed";
  if (status === "archived") return "Archived";
  return status;
}

function caseStatusTone(status: string, isDark: boolean) {
  if (status === "completed") {
    return isDark
      ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200"
      : "border-emerald-700/30 bg-emerald-50 text-emerald-800";
  }
  if (status === "archived") {
    return isDark
      ? "border-white/10 bg-white/5 text-white/45"
      : "border-[#141414]/10 bg-[#141414]/5 text-[#4A4741]";
  }
  if (status === "submitted_for_approval") {
    return isDark
      ? "border-amber-400/30 bg-amber-500/10 text-amber-200"
      : "border-amber-700/30 bg-amber-50 text-amber-800";
  }
  return chipClass(isDark);
}

export function PrivacyDraftInboxPanel({
  inbox,
  approvalQueueId,
  border,
  panel,
  muted,
  isDark,
  okClass,
  warnClass,
  errorClass,
}: {
  inbox: PrivacyDraftInboxState;
  approvalQueueId: string | null;
  border: string;
  panel: string;
  muted: string;
  isDark: boolean;
  okClass: string;
  warnClass: string;
  errorClass: string;
}) {
  const canDispose = inbox.selectedDraft?.status === "draft" && !inbox.dispositionLoading;
  const activeDisposition =
    inbox.dispositionResult?.case_id === inbox.selectedDraft?.case_id
      ? inbox.dispositionResult
      : null;
  const activeDraftCount = inbox.drafts.filter(
    (draft) => draft.status === "draft" || draft.status === "submitted_for_approval",
  ).length;
  const completedDraftCount = inbox.drafts.filter(
    (draft) => draft.status === "completed",
  ).length;
  const successIcon = isDark ? "text-emerald-300" : "text-emerald-800";

  return (
    <section id="privacy-draft-inbox" className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Inbox className={`h-4 w-4 ${successIcon}`} />
          <div>
            <h2 className="text-base font-semibold">
              Draft review
            </h2>
            <p className={`mt-1 text-sm leading-6 ${muted}`}>
              Draft inbox stores saved packets before approval.
            </p>
            <p className={`mt-1 text-xs font-medium ${muted}`}>
              {activeDraftCount} active / {completedDraftCount} completed
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={inbox.refreshDrafts}
          className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm transition hover:border-emerald-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:hover:border-emerald-300/50 dark:focus-visible:outline-emerald-300 ${border}`}
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </div>

      <div className="mt-4 space-y-3">
        {inbox.error && (
          <StatusLine
            icon="error"
            className={errorClass}
            text="Draft inbox unavailable"
          />
        )}
        {inbox.isLoading && (
          <div
            className={`h-24 animate-pulse rounded-lg ${isDark ? "bg-white/5" : "bg-[#141414]/5"}`}
          />
        )}
        {!inbox.isLoading && !inbox.error && inbox.drafts.length === 0 && (
          <StatusLine
            icon="error"
            className={warnClass}
            text="Drafts appear here after you create a review packet."
          />
        )}
        {inbox.drafts.map((draft) => (
          <button
            key={draft.case_id}
            type="button"
            onClick={() => inbox.selectCase(draft.case_id)}
            className={`w-full rounded-lg border p-3 text-left transition hover:border-emerald-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:hover:border-emerald-300/50 dark:focus-visible:outline-emerald-300 ${border} ${
              inbox.selectedCaseId === draft.case_id
                ? "border-emerald-400/60 bg-emerald-500/10"
                : isDark
                  ? "bg-[#0A0A0A]/60"
                  : "bg-[#E4E3E0]/60"
            }`}
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold">Case {shortId(draft.case_id)}</p>
                <p
                  className={`mt-1 text-xs font-medium ${muted}`}
                >
                  {caseStatusLabel(draft.status)} - {formatDate(draft.created_at)}
                </p>
              </div>
              <span
                className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${caseStatusTone(draft.status, isDark)}`}
              >
                {draft.highest_approval_tier ?? "T-"} / {caseStatusLabel(draft.status)}
              </span>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <span
                className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${chipClass(isDark)}`}
              >
                {draft.target_count} targets
              </span>
              <span
                className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${chipClass(isDark)}`}
              >
                {draft.action_count} actions
              </span>
            </div>
          </button>
        ))}
      </div>

      <div className="mt-4 space-y-3">
        {inbox.detailError && (
          <StatusLine
            icon="error"
            className={errorClass}
            text="Draft detail unavailable"
          />
        )}
        {inbox.detailLoading && (
          <div
            className={`h-32 animate-pulse rounded-lg ${isDark ? "bg-white/5" : "bg-[#141414]/5"}`}
          />
        )}
        {!inbox.selectedCaseId && inbox.drafts.length > 0 && (
          <StatusLine icon="error" className={warnClass} text="Select a draft" />
        )}
        {inbox.selectedDraft && (
          <>
            <StatusLine
              icon="ok"
              className={okClass}
              text={`${inbox.selectedDraft.action_count} draft actions ready`}
            />
            {inbox.dispositionError && (
              <StatusLine
                icon="error"
                className={errorClass}
                text="Draft disposition failed"
              />
            )}
            {activeDisposition && (
              <StatusLine
                icon="ok"
                className={
                  activeDisposition.status === "archived" ? warnClass : okClass
                }
                text={
                  activeDisposition.queue_id
                    ? "Approval handoff queued"
                    : "Draft archived"
                }
              />
            )}
            <div className={`grid gap-3 rounded-lg border p-3 sm:grid-cols-2 ${border}`}>
              <KeyValue
                label="Status"
                value={caseStatusLabel(inbox.selectedDraft.status)}
                mutedClass={muted}
              />
              <KeyValue
                label="Targets"
                value={String(inbox.selectedDraft.target_count)}
                mutedClass={muted}
              />
            </div>
            <details className={`rounded-lg border ${border}`}>
              <summary className={`cursor-pointer px-3 py-2 text-sm font-medium ${muted}`}>
                Audit details
              </summary>
              <div className={`grid gap-3 border-t p-3 ${border}`}>
                <KeyValue
                  label="Case ID"
                  value={inbox.selectedDraft.case_id}
                  mutedClass={muted}
                />
                <KeyValue
                  label="Payload key"
                  value={inbox.selectedDraft.payload_key_version}
                  mutedClass={muted}
                />
                {activeDisposition?.queue_id && (
                  <KeyValue
                    label="Queue ID"
                    value={activeDisposition.queue_id}
                    mutedClass={muted}
                  />
                )}
                {approvalQueueId && !activeDisposition?.queue_id && (
                  <KeyValue
                    label="Approval queue"
                    value={approvalQueueId}
                    mutedClass={muted}
                  />
                )}
              </div>
            </details>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={inbox.submitSelectedDraftForApproval}
                disabled={!canDispose}
                className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:focus-visible:outline-emerald-300 ${border} ${
                  canDispose
                    ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300"
                    : "cursor-not-allowed opacity-45"
                }`}
              >
                {inbox.pendingDispositionPath === "submit-approval" ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-4 w-4" />
                )}
                Submit for approval
              </button>
              <button
                type="button"
                onClick={inbox.archiveSelectedDraft}
                disabled={!canDispose}
                className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:focus-visible:outline-emerald-300 ${border} ${
                  canDispose
                    ? "bg-amber-500/10 text-amber-700 dark:text-amber-300"
                    : "cursor-not-allowed opacity-45"
                }`}
              >
                {inbox.pendingDispositionPath === "archive" ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <Archive className="h-4 w-4" />
                )}
                Archive
              </button>
            </div>
            <div className="space-y-3">
              {inbox.selectedDraft.review_packets.map((packet) => (
                <article key={packet.target_id} className={`rounded-lg border p-3 ${border}`}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold">
                        {packet.target_name}
                      </p>
                      <p
                        className={`truncate text-sm ${muted}`}
                      >
                        {TARGET_METHOD_LABEL[packet.opt_out_method]} · {packet.jurisdiction}
                      </p>
                    </div>
                    <span
                      className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${chipClass(isDark)}`}
                    >
                      {packet.approval_tier}
                    </span>
                  </div>
                  <p className={`mt-3 text-sm ${muted}`}>{packet.legal_basis}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <span
                      className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${chipClass(isDark)}`}
                    >
                      {packet.category.replace("_", " ")}
                    </span>
                    <span
                      className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${chipClass(isDark)}`}
                    >
                      {TARGET_METHOD_LABEL[packet.opt_out_method]}
                    </span>
                    <span
                      className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${chipClass(isDark)}`}
                    >
                      {packet.jurisdiction}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
