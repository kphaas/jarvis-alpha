import { CheckCircle2, ClipboardList, RefreshCw } from "lucide-react";
import type { PrivacyApprovedActionsState } from "../../hooks/usePrivacyApprovedActions";
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
                {action.approval_tier}
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
            </div>

            <div className="mt-3">
              <StatusLine
                icon="ok"
                className={okClass}
                text="Ready for manual operator handling"
              />
            </div>
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
