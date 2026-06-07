import { motion } from "framer-motion";
import {
  ArrowRight,
  CheckCircle2,
  Fingerprint,
  LockKeyhole,
  ShieldCheck,
} from "lucide-react";
import { useState } from "react";
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
import {
  PrivacyGuidedSetupPanel,
  type PrivacyGuidedStep,
  type PrivacyGuidedStepId,
} from "../components/privacy/PrivacyGuidedSetupPanel";
import { usePrivacyApprovedActions } from "../hooks/usePrivacyApprovedActions";
import { usePrivacyCaseDraft } from "../hooks/usePrivacyCaseDraft";
import { usePrivacyDraftInbox } from "../hooks/usePrivacyDraftInbox";
import { usePrivacyIntake } from "../hooks/usePrivacyIntake";
import { usePrivacyRemovalControl } from "../hooks/usePrivacyRemovalControl";
import { usePrivacyRemovalSeed } from "../hooks/usePrivacyRemovalSeed";
import { usePrivacyTargets } from "../hooks/usePrivacyTargets";
import { useAppStore } from "../store";
import type { ApprovedPrivacyAction, CaseDraftDetailResponse } from "../types/privacy";

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

function suggestedGuidedStep({
  subjectReady,
  selectedTargetCount,
  hasLocalPacket,
  draftReviewCount,
  approvalReviewCount,
  openActionCount,
  completedCaseCount,
}: {
  subjectReady: boolean;
  selectedTargetCount: number;
  hasLocalPacket: boolean;
  draftReviewCount: number;
  approvalReviewCount: number;
  openActionCount: number;
  completedCaseCount: number;
}): PrivacyGuidedStepId {
  if (openActionCount > 0) return "actions";
  if (completedCaseCount > 0) return "report";
  if (!subjectReady) return "subject";
  if (selectedTargetCount === 0 && !hasLocalPacket && draftReviewCount === 0 && approvalReviewCount === 0) {
    return "targets";
  }
  if (selectedTargetCount > 0 && !hasLocalPacket && draftReviewCount === 0) return "packet";
  if (hasLocalPacket || draftReviewCount > 0 || approvalReviewCount > 0) return "review";
  return "targets";
}

function shortId(value: string | null) {
  return value ? value.slice(0, 8) : "pending";
}

function isTerminalAction(action: ApprovedPrivacyAction | null) {
  return action?.status === "confirmed" || action?.status === "failed";
}

function focusedGuidedStep({
  hasDeepLink,
  selectedAction,
  selectedDraft,
}: {
  hasDeepLink: boolean;
  selectedAction: ApprovedPrivacyAction | null;
  selectedDraft: CaseDraftDetailResponse | null;
}): PrivacyGuidedStepId | null {
  if (!hasDeepLink) return null;
  if (selectedAction) return isTerminalAction(selectedAction) ? "report" : "actions";
  if (selectedDraft?.status === "draft" || selectedDraft?.status === "submitted_for_approval") {
    return "review";
  }
  return "actions";
}

function focusedCaseSummary({
  approvalQueueId,
  caseId,
  actionId,
  selectedAction,
  selectedDraft,
}: {
  approvalQueueId: string | null;
  caseId: string | null;
  actionId: string | null;
  selectedAction: ApprovedPrivacyAction | null;
  selectedDraft: CaseDraftDetailResponse | null;
}) {
  if (!approvalQueueId && !caseId && !actionId) return null;
  if (selectedAction) {
    if (selectedAction.status === "confirmed") {
      return {
        status: "Verified",
        next: "Review the case report and evidence hashes.",
        step: "report" as PrivacyGuidedStepId,
      };
    }
    if (selectedAction.status === "sent") {
      return {
        status: "Handled",
        next: "Record verification evidence for this action.",
        step: "actions" as PrivacyGuidedStepId,
      };
    }
    if (selectedAction.status === "failed") {
      return {
        status: "Needs review",
        next: "Open the report and inspect the failed action.",
        step: "report" as PrivacyGuidedStepId,
      };
    }
    return {
      status: "Approved",
      next: "Record manual handling for this target.",
      step: "actions" as PrivacyGuidedStepId,
    };
  }
  if (selectedDraft?.status === "draft") {
    return {
      status: "Draft",
      next: "Submit this packet for approval.",
      step: "review" as PrivacyGuidedStepId,
    };
  }
  if (selectedDraft?.status === "submitted_for_approval") {
    return {
      status: "Awaiting approval",
      next: "Finish the approval decision, then return here for handling.",
      step: "review" as PrivacyGuidedStepId,
    };
  }
  if (selectedDraft?.status === "completed") {
    return {
      status: "Completed",
      next: "Review the case report and evidence hashes.",
      step: "report" as PrivacyGuidedStepId,
    };
  }
  return {
    status: "Loading case",
    next: "AT-0 is locating the case workflow.",
    step: "actions" as PrivacyGuidedStepId,
  };
}

export default function Privacy() {
  const { theme } = useAppStore();
  const [searchParams] = useSearchParams();
  const approvalQueueId = searchParams.get("approval");
  const caseId = searchParams.get("case");
  const actionId = searchParams.get("action");
  const [privacyViewMode, setPrivacyViewMode] = useState<"guided" | "advanced">(
    "guided",
  );
  const [manualGuidedStep, setManualGuidedStep] = useState<PrivacyGuidedStepId | null>(
    null,
  );
  const intake = usePrivacyIntake();
  const targets = usePrivacyTargets();
  const subjectId = intake.createdSubject?.subject_id ?? null;
  const draftState = usePrivacyCaseDraft(subjectId, targets.selectedIds);
  const draftInbox = usePrivacyDraftInbox(caseId);
  const approvedActions = usePrivacyApprovedActions(actionId, caseId);
  const removalControl = usePrivacyRemovalControl();
  const removalSeed = usePrivacyRemovalSeed(subjectId, () => {
    void removalControl.refreshSummary();
  });
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
  const draftReviewCount = draftInbox.drafts.filter(
    (draft) => draft.status === "draft",
  ).length;
  const approvalReviewCount = draftInbox.drafts.filter(
    (draft) => draft.status === "submitted_for_approval",
  ).length;
  const workflowDraftCount = draftState.draft ? Math.max(1, activeDraftCount) : activeDraftCount;
  const hasFocusedCase = Boolean(caseId || actionId || approvalQueueId);
  const focusedStep = focusedGuidedStep({
    hasDeepLink: hasFocusedCase,
    selectedAction: approvedActions.selectedAction,
    selectedDraft: draftInbox.selectedDraft,
  });
  const guidedSuggestion = suggestedGuidedStep({
    subjectReady: Boolean(subjectId),
    selectedTargetCount: targets.selectedCount,
    hasLocalPacket: Boolean(draftState.draft),
    draftReviewCount,
    approvalReviewCount,
    openActionCount,
    completedCaseCount,
  });
  const activeGuidedStep = manualGuidedStep ?? focusedStep ?? guidedSuggestion;
  const focusedSummary = focusedCaseSummary({
    approvalQueueId,
    caseId,
    actionId,
    selectedAction: approvedActions.selectedAction,
    selectedDraft: draftInbox.selectedDraft,
  });
  const guidedSteps: PrivacyGuidedStep[] = [
    {
      id: "subject",
      label: "Subject",
      detail: "Add the encrypted profile and identity values.",
      status: subjectId ? "done" : activeGuidedStep === "subject" ? "current" : "waiting",
    },
    {
      id: "targets",
      label: "Targets",
      detail: "Choose broker and record sites.",
      status:
        targets.selectedCount > 0 || workflowDraftCount > 0 || openActionCount > 0
          ? "done"
          : activeGuidedStep === "targets"
            ? "current"
            : "waiting",
    },
    {
      id: "packet",
      label: "Packet",
      detail: "Create the local review packet.",
      status:
        Boolean(draftState.draft) || workflowDraftCount > 0
          ? "done"
          : activeGuidedStep === "packet"
            ? "current"
            : "waiting",
    },
    {
      id: "review",
      label: "Approval",
      detail: "Submit or inspect the draft packet.",
      status:
        openActionCount > 0 || completedCaseCount > 0
          ? "done"
          : activeGuidedStep === "review"
            ? "current"
            : "waiting",
    },
    {
      id: "actions",
      label: "Handling",
      detail: "Record manual handling and verification.",
      status:
        completedCaseCount > 0
          ? "done"
          : activeGuidedStep === "actions"
            ? "current"
            : "waiting",
    },
    {
      id: "report",
      label: "Report",
      detail: "Review readiness and evidence coverage.",
      status: completedCaseCount > 0 || activeGuidedStep === "report" ? "current" : "waiting",
    },
  ];

  function selectGuidedStep(step: PrivacyGuidedStepId) {
    setManualGuidedStep(step);
    setPrivacyViewMode("guided");
  }

  function renderGuidedPanel(step: PrivacyGuidedStepId) {
    if (step === "subject") {
      return (
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
        </div>
      );
    }
    if (step === "targets") {
      return (
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
      );
    }
    if (step === "packet") {
      return (
        <PrivacyCaseDraftPanel
          draftState={draftState}
          subjectId={subjectId}
          selectedCount={targets.selectedCount}
          onDraftCreated={() => {
            targets.clearSelection();
            draftInbox.refreshDrafts();
            setManualGuidedStep("review");
          }}
          border={border}
          panel={panel}
          muted={muted}
          isDark={isDark}
          okClass={tone(isDark, "ok")}
          warnClass={tone(isDark, "warn")}
          errorClass={tone(isDark, "error")}
        />
      );
    }
    if (step === "review") {
      return (
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
      );
    }
    if (step === "actions") {
      return (
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
      );
    }
    return (
      <PrivacyRemovalControlPanel
        control={removalControl}
        seed={removalSeed}
        border={border}
        panel={panel}
        muted={muted}
        isDark={isDark}
        okClass={tone(isDark, "ok")}
        warnClass={tone(isDark, "warn")}
        errorClass={tone(isDark, "error")}
      />
    );
  }

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

      {focusedSummary && (
        <section
          id="privacy-current-case"
          className={`rounded-xl border ${border} ${panel} p-4`}
          aria-label="Current privacy case"
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-start gap-3">
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border ${border}`}>
                <ShieldCheck className={`h-5 w-5 ${successIcon}`} />
              </div>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-semibold">Current case</p>
                  <span className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${border} ${muted}`}>
                    {shortId(caseId ?? approvedActions.selectedAction?.case_id ?? null)}
                  </span>
                  <span className={tone(isDark, focusedSummary.status === "Loading case" ? "warn" : "ok") + " rounded-md border px-2 py-1 text-xs font-semibold"}>
                    {focusedSummary.status}
                  </span>
                </div>
                <p className={`mt-1 max-w-3xl text-sm leading-6 ${muted}`}>
                  {focusedSummary.next}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => selectGuidedStep(focusedSummary.step)}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-emerald-500 px-4 text-sm font-bold text-[#0A0A0A] transition hover:bg-emerald-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:focus-visible:outline-emerald-300"
            >
              Open next step
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </section>
      )}

      {privacyViewMode === "guided" ? (
        <PrivacyGuidedSetupPanel
          steps={guidedSteps}
          activeStep={activeGuidedStep}
          border={border}
          panel={panel}
          muted={muted}
          isDark={isDark}
          onStepChange={selectGuidedStep}
          onShowAdvanced={() => setPrivacyViewMode("advanced")}
        >
          {renderGuidedPanel(activeGuidedStep)}
        </PrivacyGuidedSetupPanel>
      ) : (
        <>
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
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className={`text-base font-semibold ${strong}`}>Advanced workflow</h2>
                <p className={`max-w-3xl text-sm leading-6 ${muted}`}>
                  Detailed intake, packet, approval, handling, and evidence tools stay here for audit
                  and troubleshooting.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setPrivacyViewMode("guided")}
                className={`inline-flex min-h-11 items-center justify-center rounded-lg border px-3 text-sm font-semibold transition hover:border-emerald-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:hover:border-emerald-300/50 dark:focus-visible:outline-emerald-300 ${border}`}
              >
                Show guided setup
              </button>
            </div>
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
            seed={removalSeed}
            border={border}
            panel={panel}
            muted={muted}
            isDark={isDark}
            okClass={tone(isDark, "ok")}
            warnClass={tone(isDark, "warn")}
            errorClass={tone(isDark, "error")}
          />
        </>
      )}
    </motion.div>
  );
}
