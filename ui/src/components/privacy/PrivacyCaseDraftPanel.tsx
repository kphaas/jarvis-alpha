import { FileText, X } from "lucide-react";
import type { PrivacyCaseDraftState } from "../../hooks/usePrivacyCaseDraft";
import { TARGET_METHOD_LABEL } from "../../types/privacy";
import { KeyValue, StatusLine } from "./PrivacyFields";

function chipClass(isDark: boolean) {
  return isDark
    ? "border-white/10 bg-white/5 text-white/70"
    : "border-[#141414]/10 bg-[#141414]/5 text-[#4A4741]";
}

export function PrivacyCaseDraftPanel({
  draftState,
  subjectId,
  selectedCount,
  onDraftCreated,
  border,
  panel,
  muted,
  isDark,
  okClass,
  warnClass,
  errorClass,
}: {
  draftState: PrivacyCaseDraftState;
  subjectId: string | null;
  selectedCount: number;
  onDraftCreated: () => void;
  border: string;
  panel: string;
  muted: string;
  isDark: boolean;
  okClass: string;
  warnClass: string;
  errorClass: string;
}) {
  async function createDraft() {
    const result = await draftState.createDraft();
    if (result) onDraftCreated();
  }

  return (
    <section className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-emerald-400" />
          <h2
            className={`text-xs font-mono uppercase tracking-widest ${muted}`}
          >
            Review Packet
          </h2>
        </div>
        <div className="flex items-center gap-2">
          {draftState.draft && (
            <button
              type="button"
              onClick={draftState.clearDraft}
              className={`inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border ${border}`}
              aria-label="Clear review packet"
            >
              <X className="h-4 w-4" />
            </button>
          )}
          <button
            type="button"
            onClick={createDraft}
            disabled={!draftState.canCreate}
            className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm transition disabled:opacity-40 ${border}`}
          >
            <FileText className="h-4 w-4" />
            Create draft
          </button>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {!draftState.draft && !subjectId && (
          <StatusLine
            icon="error"
            className={warnClass}
            text="Create a subject before drafting"
          />
        )}
        {!draftState.draft && subjectId && selectedCount === 0 && (
          <StatusLine
            icon="error"
            className={warnClass}
            text="Select at least one target"
          />
        )}
        {draftState.error && (
          <StatusLine
            icon="error"
            className={errorClass}
            text="Draft creation failed"
          />
        )}
        {draftState.loading && (
          <div
            className={`h-24 animate-pulse rounded-lg ${isDark ? "bg-white/5" : "bg-[#141414]/5"}`}
          />
        )}
        {draftState.draft && (
          <>
            <StatusLine
              icon="ok"
              className={okClass}
              text={`${draftState.draft.action_count} draft actions stored`}
            />
            <div className={`grid gap-3 rounded-lg border p-3 sm:grid-cols-2 ${border}`}>
              <KeyValue
                label="Targets"
                value={String(draftState.draft.target_count)}
                mutedClass={muted}
              />
              <KeyValue
                label="Actions"
                value={String(draftState.draft.action_count)}
                mutedClass={muted}
              />
            </div>
            <details className={`rounded-lg border ${border}`}>
              <summary className={`cursor-pointer px-3 py-2 text-sm font-medium ${muted}`}>
                Audit details
              </summary>
              <div className={`grid gap-3 border-t p-3 sm:grid-cols-2 ${border}`}>
                <KeyValue
                  label="Case ID"
                  value={draftState.draft.case_id}
                  mutedClass={muted}
                />
                <KeyValue
                  label="Payload key"
                  value={draftState.draft.payload_key_version}
                  mutedClass={muted}
                />
                <KeyValue
                  label="Status"
                  value={draftState.draft.status}
                  mutedClass={muted}
                />
              </div>
            </details>
            <div className="space-y-3">
              {draftState.draft.review_packets.map((packet) => (
                <article
                  key={packet.target_id}
                  className={`rounded-lg border p-3 ${border}`}
                >
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
                  <p className={`mt-3 text-sm ${muted}`}>
                    {packet.legal_basis}
                  </p>
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
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    <div>
                      <p
                        className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
                      >
                        Identifiers
                      </p>
                      <p className="mt-1 text-sm">
                        {packet.required_identifiers.join(", ")}
                      </p>
                    </div>
                    <div>
                      <p
                        className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
                      >
                        Available
                      </p>
                      <p className="mt-1 text-sm">
                        {packet.available_identity_tuple_types.join(", ") ||
                          "none"}
                      </p>
                    </div>
                  </div>
                  <ul className={`mt-3 space-y-1 text-sm ${muted}`}>
                    {packet.evidence_checklist.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </article>
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
