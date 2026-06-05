import { Inbox, RefreshCw } from "lucide-react";
import type { PrivacyDraftInboxState } from "../../hooks/usePrivacyDraftInbox";
import { TARGET_METHOD_LABEL } from "../../types/privacy";
import { KeyValue, StatusLine } from "./PrivacyFields";

function chipClass(isDark: boolean) {
  return isDark
    ? "border-white/10 bg-white/5 text-white/65"
    : "border-[#141414]/10 bg-[#141414]/5 text-[#141414]/65";
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

export function PrivacyDraftInboxPanel({
  inbox,
  border,
  panel,
  muted,
  isDark,
  okClass,
  warnClass,
  errorClass,
}: {
  inbox: PrivacyDraftInboxState;
  border: string;
  panel: string;
  muted: string;
  isDark: boolean;
  okClass: string;
  warnClass: string;
  errorClass: string;
}) {
  return (
    <section className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Inbox className="h-4 w-4 text-emerald-400" />
          <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>
            Draft Inbox
          </h2>
        </div>
        <button
          type="button"
          onClick={inbox.refreshDrafts}
          className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm transition ${border}`}
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
          <StatusLine icon="error" className={warnClass} text="No drafts stored" />
        )}
        {inbox.drafts.map((draft) => (
          <button
            key={draft.case_id}
            type="button"
            onClick={() => inbox.selectCase(draft.case_id)}
            className={`w-full rounded-lg border p-3 text-left transition ${border} ${
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
                  className={`mt-1 text-[10px] font-mono uppercase tracking-widest ${muted}`}
                >
                  {draft.status} - {formatDate(draft.created_at)}
                </p>
              </div>
              <span
                className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${chipClass(isDark)}`}
              >
                {draft.highest_approval_tier ?? "T-"}
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
            <div className={`grid gap-3 rounded-lg border p-3 ${border}`}>
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
                        className={`truncate text-[10px] font-mono uppercase tracking-widest ${muted}`}
                      >
                        {packet.target_id}
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
