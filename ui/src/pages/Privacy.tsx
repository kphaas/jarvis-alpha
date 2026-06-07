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
import { PrivacyWorkflowGuide } from "../components/privacy/PrivacyWorkflowGuide";
import { PrivacyCommandCenter } from "../components/privacy/PrivacyCommandCenter";
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
  const border = isDark ? "border-white/10" : "border-[#141414]/12";
  const panel = isDark ? "bg-white/[0.045]" : "bg-white/60";
  const input = isDark
    ? "bg-[#0A0A0A] border-white/10 text-white placeholder:text-white/55"
    : "bg-[#F7F6F3] border-[#141414]/18 text-[#141414] placeholder:text-[#4A4741]";
  const muted = isDark ? "text-white/70" : "text-[#4A4741]";
  const strong = isDark ? "text-white" : "text-[#141414]";
  const successIcon = isDark ? "text-emerald-300" : "text-emerald-800";
  const openActionCount = approvedActions.actions.filter(
    (action) => action.status !== "confirmed" && action.status !== "failed",
  ).length;
  const completedCaseCount = draftInbox.drafts.filter(
    (draft) => draft.status === "completed",
  ).length;
  const activeDraftCount = draftInbox.drafts.filter(
    (draft) => draft.status === "draft" || draft.status === "submitted_for_approval",
  ).length;
  const workflowDraftCount = draftState.draft ? Math.max(1, activeDraftCount) : activeDraftCount;

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className="max-w-7xl space-y-5"
    >
      <div
        className={`rounded-xl border ${border} ${panel} p-5`}
      >
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="flex items-center gap-3">
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-lg border ${border} ${panel}`}
            >
              <Fingerprint className={`h-5 w-5 ${successIcon}`} />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <p className={`text-xs font-semibold tracking-tight ${strong}`}>
                  AT-0 Privacy Agent
                </p>
                <span className={`rounded-md border px-2 py-1 text-xs font-medium ${border} ${muted}`}>
                  Manual MVP
                </span>
              </div>
              <h1 className={`mt-1 text-2xl font-semibold tracking-tight ${strong}`}>
                AT-0 Privacy Console
              </h1>
              <p
                className={`mt-2 max-w-2xl text-sm leading-6 ${muted}`}
              >
                Guided private intake, target selection, review packets,
                approvals, manual handling, and evidence. Outbound removal
                work stays disabled until explicit go-live approval.
              </p>
            </div>
          </div>
          <div
            className={`grid w-full grid-cols-3 overflow-hidden rounded-lg border text-center text-xs font-medium sm:w-auto sm:min-w-[22rem] ${border}`}
          >
            <div className={`px-3 py-3 ${isDark ? "bg-white/[0.03]" : "bg-white/45"}`}>
              <LockKeyhole className={`mx-auto mb-1 h-4 w-4 ${successIcon}`} />
              <span className="whitespace-nowrap">Local review</span>
            </div>
            <div className={`border-x px-3 py-3 ${border}`}>
              <ShieldCheck className={`mx-auto mb-1 h-4 w-4 ${successIcon}`} />
              <span className="whitespace-nowrap">{openActionCount} open</span>
            </div>
            <div className={`px-3 py-3 ${isDark ? "bg-white/[0.03]" : "bg-white/45"}`}>
              <CheckCircle2 className={`mx-auto mb-1 h-4 w-4 ${successIcon}`} />
              <span className="whitespace-nowrap">{completedCaseCount} verified</span>
            </div>
          </div>
        </div>
      </div>

      <PrivacyCommandCenter
        subjectReady={Boolean(subjectId)}
        selectedTargetCount={targets.selectedCount}
        targetCount={targets.targets.length}
        drafts={draftInbox.drafts}
        actions={approvedActions.actions}
        completedCaseCount={completedCaseCount}
        border={border}
        panel={panel}
        muted={muted}
        isDark={isDark}
      />

      <PrivacyWorkflowGuide
        subjectReady={Boolean(subjectId)}
        selectedTargetCount={targets.selectedCount}
        activeDraftCount={workflowDraftCount}
        openActionCount={openActionCount}
        completedCaseCount={completedCaseCount}
        border={border}
        panel={panel}
        muted={muted}
        isDark={isDark}
      />

      <div id="privacy-advanced-workflow" className="flex flex-col gap-2">
        <h2 className={`text-base font-semibold ${strong}`}>Advanced workflow</h2>
        <p className={`max-w-3xl text-sm leading-6 ${muted}`}>
          Detailed intake, packet, approval, handling, and evidence tools stay here for audit
          and troubleshooting.
        </p>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
        <div className="space-y-5">
          <SubjectIntakeForm
            intake={intake}
            isDark={isDark}
            border={border}
            panel={panel}
            input={input}
            muted={muted}
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
        <div className="space-y-5">
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
    </motion.div>
  );
}
