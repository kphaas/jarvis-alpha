import {
  CheckCircle2,
  Circle,
  ClipboardCheck,
  FileText,
  Fingerprint,
  ListChecks,
  SearchCheck,
  ShieldCheck,
} from "lucide-react";

type StepStatus = "done" | "current" | "blocked";

type WorkflowStep = {
  label: string;
  detail: string;
  status: StepStatus;
  metric?: string;
  Icon: typeof Fingerprint;
};

function stepClass(status: StepStatus, isDark: boolean, border: string) {
  if (status === "done") {
    return isDark
      ? "border-emerald-400/30 bg-emerald-500/10"
      : "border-emerald-800/20 bg-emerald-50";
  }
  if (status === "current") {
    return isDark
      ? "border-white/25 bg-white/10"
      : "border-[#141414]/30 bg-white/75";
  }
  return `${border} ${isDark ? "bg-white/[0.03]" : "bg-white/35"}`;
}

function statusCopy(status: StepStatus) {
  if (status === "done") return "Done";
  if (status === "current") return "Now";
  return "Waiting";
}

export function PrivacyWorkflowGuide({
  subjectReady,
  selectedTargetCount,
  activeDraftCount,
  openActionCount,
  completedCaseCount,
  border,
  panel,
  muted,
  isDark,
}: {
  subjectReady: boolean;
  selectedTargetCount: number;
  activeDraftCount: number;
  openActionCount: number;
  completedCaseCount: number;
  border: string;
  panel: string;
  muted: string;
  isDark: boolean;
}) {
  const hasTargets = selectedTargetCount > 0 || activeDraftCount > 0 || openActionCount > 0 || completedCaseCount > 0;
  const hasDraft = activeDraftCount > 0 || openActionCount > 0 || completedCaseCount > 0;
  const hasHandledAction = completedCaseCount > 0;

  const steps: WorkflowStep[] = [
    {
      label: "Subject",
      detail: "Add the encrypted profile",
      status: subjectReady ? "done" : "current",
      Icon: Fingerprint,
    },
    {
      label: "Targets",
      detail: "Choose broker or record sites",
      status: hasTargets ? "done" : subjectReady ? "current" : "blocked",
      metric: selectedTargetCount > 0 ? `${selectedTargetCount} selected` : undefined,
      Icon: SearchCheck,
    },
    {
      label: "Draft",
      detail: "Build a review packet",
      status: hasDraft ? "done" : subjectReady && selectedTargetCount > 0 ? "current" : "blocked",
      metric: activeDraftCount > 0 ? `${activeDraftCount} active` : undefined,
      Icon: FileText,
    },
    {
      label: "Approval",
      detail: "Send to AT-0 review",
      status: openActionCount > 0 || completedCaseCount > 0 ? "done" : hasDraft ? "current" : "blocked",
      Icon: ShieldCheck,
    },
    {
      label: "Action",
      detail: "Record manual handling",
      status: hasHandledAction ? "done" : openActionCount > 0 ? "current" : "blocked",
      metric: openActionCount > 0 ? `${openActionCount} open` : undefined,
      Icon: ClipboardCheck,
    },
    {
      label: "Evidence",
      detail: "Verify and keep proof",
      status: completedCaseCount > 0 ? "current" : "blocked",
      metric: completedCaseCount > 0 ? `${completedCaseCount} complete` : undefined,
      Icon: ListChecks,
    },
  ];

  const nextAction =
    !subjectReady
      ? "Create the subject profile first. Only enter the minimum details needed for the removal work."
      : !hasTargets
        ? "Pick the targets to include. Start with the highest-risk brokers or public-record sources."
        : selectedTargetCount > 0 && !hasDraft
          ? "Create the review packet so each target has a local draft action."
          : hasDraft && openActionCount === 0 && completedCaseCount === 0
            ? "Submit the draft for approval from the Draft Inbox."
            : openActionCount > 0
              ? "Record the manual handling result for each approved action."
              : "Review the evidence report and keep verification current.";

  return (
    <section className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-base font-semibold">Next step</h2>
          <p className={`mt-1 max-w-3xl text-sm leading-6 ${muted}`}>{nextAction}</p>
        </div>
        <div
          className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm font-medium ${
            isDark
              ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200"
              : "border-emerald-900/20 bg-emerald-50 text-emerald-900"
          }`}
        >
          <ShieldCheck className="h-4 w-4" />
          Manual approval stays on
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        {steps.map((step) => {
          const Icon = step.Icon;
          const StatusIcon = step.status === "done" ? CheckCircle2 : Circle;
          return (
            <div
              key={step.label}
              className={`min-h-[138px] rounded-lg border p-3 transition ${stepClass(step.status, isDark, border)}`}
            >
              <div className="flex items-start justify-between gap-3">
                <Icon
                  className={`h-4 w-4 ${
                    step.status === "blocked"
                      ? isDark
                        ? "text-white/45"
                        : "text-[#6F6A61]"
                      : isDark
                        ? "text-emerald-300"
                        : "text-emerald-800"
                  }`}
                />
                <span className={`inline-flex items-center gap-1 text-xs font-medium ${muted}`}>
                  <StatusIcon className="h-3.5 w-3.5" />
                  {statusCopy(step.status)}
                </span>
              </div>
              <h3 className="mt-3 text-sm font-semibold">{step.label}</h3>
              <p className={`mt-1 text-xs leading-5 ${muted}`}>{step.detail}</p>
              {step.metric && (
                <p className="mt-3 text-xs font-semibold text-emerald-700 dark:text-emerald-300">
                  {step.metric}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
