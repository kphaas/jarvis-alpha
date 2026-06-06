import { useState, type FormEvent } from "react";
import {
  CalendarClock,
  CheckCircle2,
  ClipboardList,
  FileText,
  RefreshCw,
  SendHorizontal,
  ShieldCheck,
} from "lucide-react";
import type { PrivacyApprovedActionsState } from "../../hooks/usePrivacyApprovedActions";
import {
  TARGET_METHOD_LABEL,
  type ApprovedPrivacyAction,
  type ManualDisposition,
  type PrivacyCaseEvent,
  type VerificationOutcome,
} from "../../types/privacy";
import { KeyValue, StatusLine } from "./PrivacyFields";

type WorkflowDraft = {
  disposition: ManualDisposition;
  note: string;
  evidence: string;
  dueAt: string;
  outcome: VerificationOutcome;
  verificationNote: string;
  verificationEvidence: string;
  verificationDueAt: string;
};

function chipClass(isDark: boolean) {
  return isDark
    ? "border-white/10 bg-white/5 text-white/65"
    : "border-[#141414]/10 bg-[#141414]/5 text-[#141414]/65";
}

function fieldClass(isDark: boolean) {
  return isDark
    ? "border-white/10 bg-[#0A0A0A] text-white placeholder:text-white/30"
    : "border-[#141414]/15 bg-[#E4E3E0] text-[#141414] placeholder:text-[#141414]/35";
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

function cleanOptional(value: string) {
  const trimmed = value.trim();
  return trimmed || undefined;
}

function localDateToIso(value: string) {
  return value ? new Date(value).toISOString() : null;
}

function defaultDraft(): WorkflowDraft {
  return {
    disposition: "handled",
    note: "",
    evidence: "",
    dueAt: "",
    outcome: "confirmed",
    verificationNote: "",
    verificationEvidence: "",
    verificationDueAt: "",
  };
}

function actionStateText(action: ApprovedPrivacyAction) {
  if (action.status === "confirmed") return "Confirmed";
  if (action.status === "failed") return action.error_code ?? "Failed";
  if (action.manual_disposition === "deferred") return "Deferred";
  if (action.status === "sent") return "Handled";
  return "Ready";
}

export function PrivacyApprovedActionsPanel({
  actionsState,
  border,
  panel,
  muted,
  isDark,
  okClass,
  warnClass,
  errorClass,
}: {
  actionsState: PrivacyApprovedActionsState;
  border: string;
  panel: string;
  muted: string;
  isDark: boolean;
  okClass: string;
  warnClass: string;
  errorClass: string;
}) {
  const [drafts, setDrafts] = useState<Record<string, WorkflowDraft>>({});

  function draftFor(actionId: string) {
    return drafts[actionId] ?? defaultDraft();
  }

  function updateDraft(actionId: string, patch: Partial<WorkflowDraft>) {
    setDrafts((current) => ({
      ...current,
      [actionId]: { ...(current[actionId] ?? defaultDraft()), ...patch },
    }));
  }

  async function submitDisposition(
    event: FormEvent<HTMLFormElement>,
    action: ApprovedPrivacyAction,
  ) {
    event.preventDefault();
    const draft = draftFor(action.action_id);
    await actionsState.recordManualDisposition({
      actionId: action.action_id,
      disposition: draft.disposition,
      operator_note: cleanOptional(draft.note),
      evidence_reference: cleanOptional(draft.evidence),
      verification_due_at: localDateToIso(draft.dueAt),
    });
    await actionsState.loadCaseWorkflow(action.case_id);
  }

  async function submitVerification(
    event: FormEvent<HTMLFormElement>,
    action: ApprovedPrivacyAction,
  ) {
    event.preventDefault();
    const draft = draftFor(action.action_id);
    await actionsState.recordVerification({
      actionId: action.action_id,
      outcome: draft.outcome,
      operator_note: cleanOptional(draft.verificationNote),
      evidence_reference: cleanOptional(draft.verificationEvidence),
      verification_due_at: localDateToIso(draft.verificationDueAt),
    });
    await actionsState.loadCaseWorkflow(action.case_id);
  }

  return (
    <section className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ClipboardList className="h-4 w-4 text-emerald-400" />
          <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>
            Approved Actions
          </h2>
        </div>
        <button
          type="button"
          onClick={actionsState.refreshActions}
          className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm transition ${border}`}
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </div>

      <div className="mt-4 space-y-3">
        {actionsState.error && (
          <StatusLine
            icon="error"
            className={errorClass}
            text="Approved actions unavailable"
          />
        )}
        {actionsState.workflowError && (
          <StatusLine
            icon="error"
            className={errorClass}
            text={actionsState.workflowError.message}
          />
        )}
        {actionsState.isLoading && (
          <div
            className={`h-24 animate-pulse rounded-lg ${isDark ? "bg-white/5" : "bg-[#141414]/5"}`}
          />
        )}
        {!actionsState.isLoading &&
          !actionsState.error &&
          actionsState.actions.length === 0 && (
            <StatusLine
              icon="error"
              className={warnClass}
              text="No approved actions ready"
            />
          )}
        {actionsState.actions.map((action) => (
          <article key={action.action_id} className={`rounded-lg border p-3 ${border}`}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold">
                  {action.target_name}
                </p>
                <p
                  className={`truncate text-[10px] font-mono uppercase tracking-widest ${muted}`}
                >
                  Case {shortId(action.case_id)} - {formatDate(action.approved_at)}
                </p>
              </div>
              <span
                className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${chipClass(isDark)}`}
              >
                {action.approval_tier} / {actionStateText(action)}
              </span>
            </div>

            <div className={`mt-3 grid gap-3 rounded-lg border p-3 text-sm ${border}`}>
              <KeyValue label="Action ID" value={action.action_id} mutedClass={muted} />
              <KeyValue label="Target ID" value={action.target_id} mutedClass={muted} />
              <KeyValue label="Status" value={action.status} mutedClass={muted} />
              <KeyValue
                label="Method"
                value={TARGET_METHOD_LABEL[action.opt_out_method]}
                mutedClass={muted}
              />
              <KeyValue
                label="Jurisdiction"
                value={action.jurisdiction}
                mutedClass={muted}
              />
              <KeyValue
                label="Response window"
                value={
                  action.avg_response_days === null
                    ? "unknown"
                    : `${action.avg_response_days} days`
                }
                mutedClass={muted}
              />
              <KeyValue
                label="Due"
                value={formatDate(action.verification_due_at)}
                mutedClass={muted}
              />
              <KeyValue
                label="Evidence hash"
                value={action.evidence_payload_hash ?? "none"}
                mutedClass={muted}
              />
            </div>

            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
              <StatusLine
                icon="ok"
                className={okClass}
                text="Ready for manual operator handling"
              />
              <button
                type="button"
                onClick={() => actionsState.loadCaseWorkflow(action.case_id)}
                className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm transition ${border}`}
              >
                <FileText className="h-4 w-4" />
                Case report
              </button>
            </div>

            <WorkflowForms
              action={action}
              draft={draftFor(action.action_id)}
              border={border}
              muted={muted}
              isDark={isDark}
              isSaving={actionsState.isSaving}
              onDraft={(patch) => updateDraft(action.action_id, patch)}
              onDisposition={(event) => submitDisposition(event, action)}
              onVerification={(event) => submitVerification(event, action)}
            />

            {actionsState.caseWorkflow?.caseId === action.case_id && (
              <CaseWorkflowView
                actionsState={actionsState}
                border={border}
                muted={muted}
                isDark={isDark}
              />
            )}
          </article>
        ))}
        {!actionsState.isLoading && !actionsState.error && actionsState.count > 0 && (
          <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest">
            <CheckCircle2 className="h-4 w-4 text-emerald-400" />
            <span className={muted}>{actionsState.count} approved</span>
          </div>
        )}
      </div>
    </section>
  );
}

function WorkflowForms({
  action,
  draft,
  border,
  muted,
  isDark,
  isSaving,
  onDraft,
  onDisposition,
  onVerification,
}: {
  action: ApprovedPrivacyAction;
  draft: WorkflowDraft;
  border: string;
  muted: string;
  isDark: boolean;
  isSaving: boolean;
  onDraft: (patch: Partial<WorkflowDraft>) => void;
  onDisposition: (event: FormEvent<HTMLFormElement>) => void;
  onVerification: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const input = `min-h-11 rounded-lg border px-3 text-sm outline-none ${fieldClass(isDark)}`;
  const area = `min-h-20 rounded-lg border px-3 py-2 text-sm outline-none ${fieldClass(isDark)}`;
  const disabled = isSaving || action.status === "confirmed";

  return (
    <div className={`mt-4 grid gap-4 border-t pt-4 ${border}`}>
      <form className="grid gap-3" onSubmit={onDisposition}>
        <div className="flex items-center gap-2">
          <SendHorizontal className="h-4 w-4 text-emerald-400" />
          <p className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
            P3-D disposition
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <select
            value={draft.disposition}
            onChange={(event) =>
              onDraft({ disposition: event.target.value as ManualDisposition })
            }
            className={input}
            disabled={disabled}
          >
            <option value="handled">Handled</option>
            <option value="deferred">Deferred</option>
            <option value="blocked">Blocked</option>
          </select>
          <input
            type="datetime-local"
            value={draft.dueAt}
            onChange={(event) => onDraft({ dueAt: event.target.value })}
            className={input}
            disabled={disabled}
            required={draft.disposition === "deferred"}
          />
        </div>
        <textarea
          value={draft.note}
          onChange={(event) => onDraft({ note: event.target.value })}
          className={area}
          placeholder="Operator note"
          disabled={disabled}
          maxLength={1000}
        />
        <input
          value={draft.evidence}
          onChange={(event) => onDraft({ evidence: event.target.value })}
          className={input}
          placeholder="Evidence reference"
          disabled={disabled}
          maxLength={1000}
        />
        <button
          type="submit"
          disabled={disabled}
          className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border px-3 text-sm transition ${border} disabled:opacity-50`}
        >
          <ShieldCheck className="h-4 w-4" />
          Record disposition
        </button>
      </form>

      <form className="grid gap-3" onSubmit={onVerification}>
        <div className="flex items-center gap-2">
          <CalendarClock className="h-4 w-4 text-emerald-400" />
          <p className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
            P3-E verification
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <select
            value={draft.outcome}
            onChange={(event) =>
              onDraft({ outcome: event.target.value as VerificationOutcome })
            }
            className={input}
            disabled={disabled}
          >
            <option value="confirmed">Confirmed</option>
            <option value="needs_followup">Follow-up</option>
            <option value="failed">Failed</option>
          </select>
          <input
            type="datetime-local"
            value={draft.verificationDueAt}
            onChange={(event) =>
              onDraft({ verificationDueAt: event.target.value })
            }
            className={input}
            disabled={disabled}
            required={draft.outcome === "needs_followup"}
          />
        </div>
        <textarea
          value={draft.verificationNote}
          onChange={(event) =>
            onDraft({ verificationNote: event.target.value })
          }
          className={area}
          placeholder="Verification note"
          disabled={disabled}
          maxLength={1000}
        />
        <input
          value={draft.verificationEvidence}
          onChange={(event) =>
            onDraft({ verificationEvidence: event.target.value })
          }
          className={input}
          placeholder="Verification evidence"
          disabled={disabled}
          maxLength={1000}
        />
        <button
          type="submit"
          disabled={disabled}
          className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border px-3 text-sm transition ${border} disabled:opacity-50`}
        >
          <CheckCircle2 className="h-4 w-4" />
          Record verification
        </button>
      </form>
    </div>
  );
}

function CaseWorkflowView({
  actionsState,
  border,
  muted,
  isDark,
}: {
  actionsState: PrivacyApprovedActionsState;
  border: string;
  muted: string;
  isDark: boolean;
}) {
  const workflow = actionsState.caseWorkflow;
  if (actionsState.caseWorkflowLoading) {
    return (
      <div
        className={`mt-4 h-24 animate-pulse rounded-lg ${isDark ? "bg-white/5" : "bg-[#141414]/5"}`}
      />
    );
  }
  if (!workflow) return null;

  return (
    <div className={`mt-4 border-t pt-4 ${border}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
          P3-F timeline
        </p>
        <span
          className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${chipClass(isDark)}`}
        >
          {workflow.report.action_count} actions / {workflow.report.event_count} events
        </span>
      </div>
      <div className="mt-3 space-y-2">
        {workflow.timeline.events.slice(-5).map((event) => (
          <TimelineRow
            key={event.event_id}
            event={event}
            border={border}
            muted={muted}
          />
        ))}
      </div>
      <div className={`mt-4 grid gap-3 border-t pt-4 ${border}`}>
        <p className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
          P3-G report
        </p>
        <div className="grid gap-3 text-sm sm:grid-cols-2">
          <KeyValue
            label="Generated"
            value={formatDate(workflow.report.generated_at)}
            mutedClass={muted}
          />
          <KeyValue
            label="Case status"
            value={workflow.report.status}
            mutedClass={muted}
          />
          <KeyValue
            label="Subjects"
            value={shortId(workflow.report.subject_id)}
            mutedClass={muted}
          />
          <KeyValue
            label="Targets"
            value={String(workflow.report.target_count)}
            mutedClass={muted}
          />
        </div>
      </div>
    </div>
  );
}

function TimelineRow({
  event,
  border,
  muted,
}: {
  event: PrivacyCaseEvent;
  border: string;
  muted: string;
}) {
  return (
    <div className={`grid gap-1 border-l px-3 py-2 ${border}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold">{event.target_name}</p>
        <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
          {formatDate(event.created_at)}
        </span>
      </div>
      <p className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
        {event.event_type} / {shortId(event.action_id)}
      </p>
      {event.event_payload_hash && (
        <p className={`truncate text-[10px] font-mono ${muted}`}>
          {event.event_payload_hash}
        </p>
      )}
    </div>
  );
}
