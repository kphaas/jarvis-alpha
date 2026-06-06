import { motion } from "framer-motion";
import { CheckCircle2, Fingerprint, LockKeyhole, ShieldCheck } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { PrivacyCaseDraftPanel } from "../components/privacy/PrivacyCaseDraftPanel";
import { PrivacyApprovedActionsPanel } from "../components/privacy/PrivacyApprovedActionsPanel";
import { PrivacyDraftInboxPanel } from "../components/privacy/PrivacyDraftInboxPanel";
import { PrivacyRemovalControlPanel } from "../components/privacy/PrivacyRemovalControlPanel";
import { PrivacyTargetRegistry } from "../components/privacy/PrivacyTargetRegistry";
import { PrivacyResultPanel } from "../components/privacy/PrivacyResultPanel";
import { SubjectIntakeForm } from "../components/privacy/SubjectIntakeForm";
import { usePrivacyApprovedActions } from "../hooks/usePrivacyApprovedActions";
import { usePrivacyCaseDraft } from "../hooks/usePrivacyCaseDraft";
import { usePrivacyDraftInbox } from "../hooks/usePrivacyDraftInbox";
import { usePrivacyIntake } from "../hooks/usePrivacyIntake";
import { usePrivacyRemovalControl } from "../hooks/usePrivacyRemovalControl";
import { usePrivacyTargets } from "../hooks/usePrivacyTargets";
import { useAppStore } from "../store";

function tone(isDark: boolean, variant: "ok" | "warn" | "error") {
  if (variant === "ok") {
    return isDark
      ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200"
      : "border-emerald-700/30 bg-emerald-50 text-emerald-800";
  }
  if (variant === "warn") {
    return isDark
      ? "border-amber-400/30 bg-amber-500/10 text-amber-200"
      : "border-amber-700/30 bg-amber-50 text-amber-800";
  }
  return isDark
    ? "border-rose-400/30 bg-rose-500/10 text-rose-200"
    : "border-rose-700/30 bg-rose-50 text-rose-800";
}

export default function Privacy() {
  const { theme } = useAppStore();
  const [searchParams] = useSearchParams();
  const approvalQueueId = searchParams.get("approval");
  const caseId = searchParams.get("case");
  const actionId = searchParams.get("action");
  const intake = usePrivacyIntake();
  const targets = usePrivacyTargets();
  const subjectId = intake.createdSubject?.subject_id ?? null;
  const draftState = usePrivacyCaseDraft(subjectId, targets.selectedIds);
  const draftInbox = usePrivacyDraftInbox(caseId);
  const approvedActions = usePrivacyApprovedActions(actionId, caseId);
  const removalControl = usePrivacyRemovalControl();
  const isDark = theme === "dark";
  const border = isDark ? "border-white/10" : "border-[#141414]/10";
  const panel = isDark ? "bg-white/5" : "bg-[#141414]/5";
  const input = isDark
    ? "bg-[#0A0A0A] border-white/10"
    : "bg-[#E4E3E0] border-[#141414]/15";
  const muted = isDark ? "text-white/45" : "text-[#141414]/50";
  const strong = isDark ? "text-white" : "text-[#141414]";
  const openActionCount = approvedActions.actions.filter(
    (action) => action.status !== "confirmed" && action.status !== "failed",
  ).length;
  const completedCaseCount = draftInbox.drafts.filter(
    (draft) => draft.status === "completed",
  ).length;

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className="max-w-6xl space-y-6"
    >
      <div
        className={`rounded-xl border ${border} ${panel} p-5`}
      >
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex items-center gap-3">
          <div
            className={`flex h-10 w-10 items-center justify-center rounded-lg border ${border} ${panel}`}
          >
            <Fingerprint className="h-5 w-5 text-emerald-400" />
          </div>
          <div>
            <p
              className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
            >
              AT-0 Privacy Agent
            </p>
            <h1 className={`mt-1 text-2xl font-semibold ${strong}`}>
              AT-0 Privacy Console
            </h1>
            <p
              className={`mt-2 max-w-2xl text-sm leading-6 ${muted}`}
            >
              Manual MVP v0.1: encrypted intake, approval handoff, local
              disposition, verification, report evidence, and P4 removal
              control.
            </p>
          </div>
        </div>
        <div
          className={`grid min-w-72 grid-cols-3 overflow-hidden rounded-lg border text-center text-[10px] font-mono uppercase ${border}`}
        >
          <div className={`px-3 py-3 ${panel}`}>
            <LockKeyhole className="mx-auto mb-1 h-4 w-4 text-emerald-400" />
            local only
          </div>
          <div className={`border-x px-3 py-3 ${border}`}>
            <ShieldCheck className="mx-auto mb-1 h-4 w-4 text-emerald-400" />
            {openActionCount} open
          </div>
          <div className={`px-3 py-3 ${panel}`}>
            <CheckCircle2 className="mx-auto mb-1 h-4 w-4 text-emerald-400" />
            {completedCaseCount} complete
          </div>
        </div>
      </div>
      </div>

      <PrivacyRemovalControlPanel
        control={removalControl}
        border={border}
        panel={panel}
        muted={muted}
        isDark={isDark}
        okClass={tone(isDark, "ok")}
        warnClass={tone(isDark, "warn")}
        errorClass={tone(isDark, "error")}
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.75fr)]">
        <SubjectIntakeForm
          intake={intake}
          isDark={isDark}
          border={border}
          panel={panel}
          input={input}
          muted={muted}
          errorClass={tone(isDark, "error")}
        />
        <div className="space-y-6">
          <PrivacyResultPanel
            intake={intake}
            border={border}
            panel={panel}
            input={input}
            muted={muted}
            isDark={isDark}
            okClass={tone(isDark, "ok")}
            warnClass={tone(isDark, "warn")}
            errorClass={tone(isDark, "error")}
          />
          <PrivacyCaseDraftPanel
            draftState={draftState}
            subjectId={subjectId}
            selectedCount={targets.selectedCount}
            onDraftCreated={() => {
              targets.clearSelection();
              draftInbox.refreshDrafts();
            }}
            border={border}
            panel={panel}
            muted={muted}
            isDark={isDark}
            okClass={tone(isDark, "ok")}
            warnClass={tone(isDark, "warn")}
            errorClass={tone(isDark, "error")}
          />
          <PrivacyDraftInboxPanel
            inbox={draftInbox}
            approvalQueueId={approvalQueueId}
            border={border}
            panel={panel}
            muted={muted}
            isDark={isDark}
            okClass={tone(isDark, "ok")}
            warnClass={tone(isDark, "warn")}
            errorClass={tone(isDark, "error")}
          />
          <PrivacyApprovedActionsPanel
            actionsState={approvedActions}
            border={border}
            panel={panel}
            muted={muted}
            isDark={isDark}
            okClass={tone(isDark, "ok")}
            warnClass={tone(isDark, "warn")}
            errorClass={tone(isDark, "error")}
          />
          <PrivacyTargetRegistry
            targets={targets}
            subjectId={subjectId}
            border={border}
            panel={panel}
            muted={muted}
            isDark={isDark}
            okClass={tone(isDark, "ok")}
            warnClass={tone(isDark, "warn")}
            errorClass={tone(isDark, "error")}
          />
        </div>
      </div>
    </motion.div>
  );
}
