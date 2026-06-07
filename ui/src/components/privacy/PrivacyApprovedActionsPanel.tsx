import { useState, type FormEvent } from "react";
import {
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  ClipboardList,
  FileText,
  History,
  ListChecks,
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
    ? "border-white/10 bg-white/5 text-white/70"
    : "border-[#141414]/10 bg-[#141414]/5 text-[#4A4741]";
}

function fieldClass(isDark: boolean) {
  return isDark
    ? "border-white/10 bg-[#0A0A0A] text-white placeholder:text-white/55"
    : "border-[#141414]/18 bg-[#F7F6F3] text-[#141414] placeholder:text-[#4A4741]";
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

function isTerminalAction(action: ApprovedPrivacyAction) {
  return action.status === "confirmed" || action.status === "failed";
}

function focusedFirst(
  actions: ApprovedPrivacyAction[],
  selectedActionId: string | null,
) {
  if (!selectedActionId) return actions;
  return [...actions].sort((left, right) => {
    if (left.action_id === selectedActionId) return -1;
    if (right.action_id === selectedActionId) return 1;
    return 0;
  });
}

function workflowStatus(action: ApprovedPrivacyAction) {
  if (action.status === "confirmed") {
    return {
      className: "ok" as const,
      text: "Verification recorded. Case report is ready.",
    };
  }
  if (action.status === "failed") {
    return {
      className: "error" as const,
      text: action.error_code
        ? `Action stopped: ${action.error_code}`
        : "Action stopped. Review the case report.",
    };
  }
  if (action.manual_disposition === "blocked") {
    return {
      className: "error" as const,
      text: "Manual handling is blocked. Review evidence before retrying.",
    };
  }
  if (action.manual_disposition === "deferred") {
    return {
      className: "warn" as const,
      text: "Manual handling is deferred until the due date.",
    };
  }
  if (action.status === "sent") {
    return {
      className: "warn" as const,
      text: "Manual handling recorded. Verification can be added when evidence is ready.",
    };
  }
  return {
    className: "ok" as const,
    text: "Ready for manual operator handling",
  };
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
  const [showCompleted, setShowCompleted] = useState(false);
  const openActions = actionsState.actions.filter(
    (action) => !isTerminalAction(action),
  );
  const completedActions = actionsState.actions.filter(isTerminalAction);
  const focusedOpenActions = focusedFirst(openActions, actionsState.selectedActionId);
  const selectedCompletedAction =
    actionsState.selectedAction &&
    isTerminalAction(actionsState.selectedAction) &&
    !showCompleted
      ? actionsState.selectedAction
      : null;
  const visibleCompletedActions = showCompleted
    ? completedActions
    : selectedCompletedAction
      ? [selectedCompletedAction]
      : [];
  const completedActionIds = new Set(
    visibleCompletedActions.map((action) => action.action_id),
  );
  const hiddenCompletedCount = completedActions.filter(
    (action) => !completedActionIds.has(action.action_id),
  ).length;
  const successIcon = isDark ? "text-emerald-300" : "text-emerald-800";

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

  function selectAction(action: ApprovedPrivacyAction) {
    actionsState.selectAction(action.action_id);
    void actionsState.loadCaseWorkflow(action.case_id);
  }

  function renderActionCard(action: ApprovedPrivacyAction) {
    const status = workflowStatus(action);
    const statusClass =
      status.className === "error"
        ? errorClass
        : status.className === "warn"
          ? warnClass
          : okClass;
    const selected = actionsState.selectedActionId === action.action_id;
    const terminal = isTerminalAction(action);

    return (
      <article
        key={action.action_id}
        data-testid={`privacy-action-${shortId(action.action_id)}`}
        className={`rounded-lg border p-3 transition ${
          selected ? "border-emerald-400/70 bg-emerald-500/10" : border
        }`}
      >
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

        <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
          <SummaryItem
            label="Method"
            value={TARGET_METHOD_LABEL[action.opt_out_method]}
            muted={muted}
            border={border}
          />
          <SummaryItem
            label="Due"
            value={formatDate(action.verification_due_at)}
            muted={muted}
            border={border}
          />
          <SummaryItem
            label="Jurisdiction"
            value={action.jurisdiction}
            muted={muted}
            border={border}
          />
          <SummaryItem
            label="Response"
            value={
              action.avg_response_days === null
                ? "Unknown"
                : `${action.avg_response_days} days`
            }
            muted={muted}
            border={border}
          />
        </div>

        <details className={`mt-3 rounded-lg border ${border}`}>
          <summary className={`cursor-pointer px-3 py-2 text-sm font-medium ${muted}`}>
            Audit details
          </summary>
          <div className={`grid gap-3 border-t p-3 text-sm ${border}`}>
            <KeyValue label="Action ID" value={action.action_id} mutedClass={muted} />
            <KeyValue label="Target ID" value={action.target_id} mutedClass={muted} />
            <KeyValue label="Status" value={action.status} mutedClass={muted} />
            <KeyValue
              label="Case status"
              value={action.case_status}
              mutedClass={muted}
            />
            <KeyValue
              label="Evidence hash"
              value={action.evidence_payload_hash ?? "none"}
              mutedClass={muted}
            />
          </div>
        </details>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <StatusLine
            icon={status.className === "error" ? "error" : "ok"}
            className={statusClass}
            text={status.text}
          />
          <button
            type="button"
            onClick={() => selectAction(action)}
            className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm transition hover:border-emerald-400/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 ${border}`}
          >
            <FileText className="h-4 w-4" />
            Case report
          </button>
        </div>

        {!terminal && (
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
        )}

        {actionsState.caseWorkflow?.caseId === action.case_id && (
          <CaseWorkflowView
            actionsState={actionsState}
            border={border}
            muted={muted}
            isDark={isDark}
          />
        )}
      </article>
    );
  }

  return (
    <section id="privacy-approved-actions" className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ClipboardList className={`h-4 w-4 ${successIcon}`} />
          <div>
            <h2 className="text-base font-semibold">
              Approved actions
            </h2>
            <p className={`mt-1 text-sm leading-6 ${muted}`}>
              Record manual work after approval. This panel does not send anything.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={actionsState.refreshActions}
          className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm transition hover:border-emerald-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:hover:border-emerald-300/50 dark:focus-visible:outline-emerald-300 ${border}`}
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
              text="Approved actions appear here after a draft is approved."
            />
          )}
        {!actionsState.isLoading &&
          !actionsState.error &&
          actionsState.actions.length > 0 && (
            <div className={`grid gap-2 rounded-lg border p-3 ${border}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <ListChecks className={`h-4 w-4 ${successIcon}`} />
                  <p className="text-sm font-semibold">
                    Needs handling
                  </p>
                </div>
                <span
                  className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${chipClass(isDark)}`}
                >
                  {openActions.length} open
                </span>
              </div>
              {openActions.length === 0 ? (
                <StatusLine
                  icon="ok"
                  className={okClass}
                  text="No open manual actions"
                />
              ) : (
                <div className="space-y-3">
                  {focusedOpenActions.map((action) => renderActionCard(action))}
                </div>
              )}
            </div>
          )}
        {visibleCompletedActions.length > 0 && (
          <div className={`grid gap-3 rounded-lg border p-3 ${border}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <History className={`h-4 w-4 ${successIcon}`} />
                <p className="text-sm font-semibold">
                  Completed actions
                </p>
              </div>
              <span
                className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${chipClass(isDark)}`}
              >
                {completedActions.length} terminal
              </span>
            </div>
            {visibleCompletedActions.map((action) => renderActionCard(action))}
          </div>
        )}
        {completedActions.length > 0 && (
          <button
            type="button"
            onClick={() => setShowCompleted((current) => !current)}
            className={`inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg border px-3 text-sm transition hover:border-emerald-400/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 ${border}`}
          >
            <ChevronDown
              className={`h-4 w-4 transition ${showCompleted ? "rotate-180" : ""}`}
            />
            {showCompleted
              ? "Hide completed"
              : `Show completed${hiddenCompletedCount ? ` (${hiddenCompletedCount})` : ""}`}
          </button>
        )}
        {!actionsState.isLoading && !actionsState.error && actionsState.count > 0 && (
          <div className="flex items-center gap-2 text-sm">
            <CheckCircle2 className={`h-4 w-4 ${successIcon}`} />
            <span className={muted}>
              {openActions.length} open / {completedActions.length} completed
            </span>
          </div>
        )}
      </div>
    </section>
  );
}

function SummaryItem({
  label,
  value,
  muted,
  border,
}: {
  label: string;
  value: string;
  muted: string;
  border: string;
}) {
  return (
    <div className={`rounded-lg border px-3 py-2 ${border}`}>
      <p className={`text-xs font-medium ${muted}`}>{label}</p>
      <p className="mt-1 break-words text-sm font-semibold">{value}</p>
    </div>
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
  const input = `min-h-11 rounded-lg border px-3 text-sm outline-none transition focus:border-emerald-600 focus-visible:ring-2 focus-visible:ring-emerald-700/25 dark:focus:border-emerald-400 dark:focus-visible:ring-emerald-300/25 ${fieldClass(isDark)}`;
  const area = `min-h-20 rounded-lg border px-3 py-2 text-sm outline-none transition focus:border-emerald-600 focus-visible:ring-2 focus-visible:ring-emerald-700/25 dark:focus:border-emerald-400 dark:focus-visible:ring-emerald-300/25 ${fieldClass(isDark)}`;
  const dispositionDisabled = isSaving || action.status !== "approved";
  const verificationDisabled = isSaving || action.status !== "sent";
  const idPrefix = `privacy-action-${shortId(action.action_id)}`;
  const labelClass = `text-xs font-medium ${muted}`;

  return (
    <div className={`mt-4 grid gap-4 border-t pt-4 ${border}`}>
      <form className="grid gap-3" onSubmit={onDisposition}>
        <div className="flex items-center gap-2">
          <SendHorizontal className="h-4 w-4 text-emerald-400" />
          <p className="text-sm font-semibold">
            Manual disposition
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="grid gap-1" htmlFor={`${idPrefix}-disposition`}>
            <span className={labelClass}>Disposition</span>
            <select
              id={`${idPrefix}-disposition`}
              value={draft.disposition}
              onChange={(event) =>
                onDraft({ disposition: event.target.value as ManualDisposition })
              }
              className={input}
              disabled={dispositionDisabled}
            >
              <option value="handled">Handled</option>
              <option value="deferred">Deferred</option>
              <option value="blocked">Blocked</option>
            </select>
          </label>
          <label className="grid gap-1" htmlFor={`${idPrefix}-disposition-due`}>
            <span className={labelClass}>Follow-up due</span>
            <input
              id={`${idPrefix}-disposition-due`}
              type="datetime-local"
              value={draft.dueAt}
              onChange={(event) => onDraft({ dueAt: event.target.value })}
              className={input}
              disabled={dispositionDisabled}
              required={draft.disposition === "deferred"}
            />
          </label>
        </div>
        <label className="grid gap-1" htmlFor={`${idPrefix}-operator-note`}>
          <span className={labelClass}>Operator note</span>
          <textarea
            id={`${idPrefix}-operator-note`}
            value={draft.note}
            onChange={(event) => onDraft({ note: event.target.value })}
            className={area}
            placeholder="Manual handling note"
            disabled={dispositionDisabled}
            maxLength={1000}
          />
        </label>
        <label className="grid gap-1" htmlFor={`${idPrefix}-evidence`}>
          <span className={labelClass}>Evidence reference</span>
          <input
            id={`${idPrefix}-evidence`}
            value={draft.evidence}
            onChange={(event) => onDraft({ evidence: event.target.value })}
            className={input}
            placeholder="smoke:// or local evidence reference"
            disabled={dispositionDisabled}
            maxLength={1000}
          />
        </label>
        <button
          type="submit"
          disabled={dispositionDisabled}
          className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border px-3 text-sm transition ${border} disabled:opacity-50`}
        >
          <ShieldCheck className="h-4 w-4" />
          Record disposition
        </button>
      </form>

      <form className="grid gap-3" onSubmit={onVerification}>
        <div className="flex items-center gap-2">
          <CalendarClock className="h-4 w-4 text-emerald-400" />
          <p className="text-sm font-semibold">
            Verification
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="grid gap-1" htmlFor={`${idPrefix}-verification`}>
            <span className={labelClass}>Outcome</span>
            <select
              id={`${idPrefix}-verification`}
              value={draft.outcome}
              onChange={(event) =>
                onDraft({ outcome: event.target.value as VerificationOutcome })
              }
              className={input}
              disabled={verificationDisabled}
            >
              <option value="confirmed">Confirmed</option>
              <option value="needs_followup">Follow-up</option>
              <option value="failed">Failed</option>
            </select>
          </label>
          <label className="grid gap-1" htmlFor={`${idPrefix}-verification-due`}>
            <span className={labelClass}>Verification due</span>
            <input
              id={`${idPrefix}-verification-due`}
              type="datetime-local"
              value={draft.verificationDueAt}
              onChange={(event) =>
                onDraft({ verificationDueAt: event.target.value })
              }
              className={input}
              disabled={verificationDisabled}
              required={draft.outcome === "needs_followup"}
            />
          </label>
        </div>
        <label className="grid gap-1" htmlFor={`${idPrefix}-verification-note`}>
          <span className={labelClass}>Verification note</span>
          <textarea
            id={`${idPrefix}-verification-note`}
            value={draft.verificationNote}
            onChange={(event) =>
              onDraft({ verificationNote: event.target.value })
            }
            className={area}
            placeholder="Verification result note"
            disabled={verificationDisabled}
            maxLength={1000}
          />
        </label>
        <label className="grid gap-1" htmlFor={`${idPrefix}-verification-evidence`}>
          <span className={labelClass}>Verification evidence</span>
          <input
            id={`${idPrefix}-verification-evidence`}
            value={draft.verificationEvidence}
            onChange={(event) =>
              onDraft({ verificationEvidence: event.target.value })
            }
            className={input}
            placeholder="smoke:// or local verification reference"
            disabled={verificationDisabled}
            maxLength={1000}
          />
        </label>
        <button
          type="submit"
          disabled={verificationDisabled}
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
  const manifest = workflow.report.evidence_manifest;

  return (
    <div className={`mt-4 border-t pt-4 ${border}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
          Timeline
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
          Case report
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
          <KeyValue
            label="Evidence status"
            value={manifest.status}
            mutedClass={muted}
          />
          <KeyValue
            label="Evidence hashes"
            value={`${manifest.evidence_payload_hash_count} / ${manifest.action_count}`}
            mutedClass={muted}
          />
          <KeyValue
            label="Event hashes"
            value={String(manifest.event_payload_hash_count)}
            mutedClass={muted}
          />
          <KeyValue
            label="Needs evidence"
            value={String(manifest.missing_evidence_count)}
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
