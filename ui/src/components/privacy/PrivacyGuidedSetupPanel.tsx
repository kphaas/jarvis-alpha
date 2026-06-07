import {
  CheckCircle2,
  ChevronDown,
  Fingerprint,
  ListChecks,
  SearchCheck,
  ShieldCheck,
} from "lucide-react";
import type { ReactNode } from "react";

export type PrivacyGuidedStepId =
  | "subject"
  | "targets"
  | "packet"
  | "review"
  | "actions"
  | "report";

export type PrivacyGuidedStep = {
  id: PrivacyGuidedStepId;
  label: string;
  detail: string;
  status: "done" | "current" | "waiting";
};

const STEP_ICONS: Record<PrivacyGuidedStepId, typeof Fingerprint> = {
  subject: Fingerprint,
  targets: SearchCheck,
  packet: ListChecks,
  review: ShieldCheck,
  actions: CheckCircle2,
  report: ChevronDown,
};

function stepTone(status: PrivacyGuidedStep["status"], isDark: boolean, border: string) {
  if (status === "done") {
    return isDark
      ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-100"
      : "border-emerald-800/20 bg-emerald-50 text-emerald-950";
  }
  if (status === "current") {
    return isDark
      ? "border-white/25 bg-white/10 text-white"
      : "border-[#141414]/30 bg-white text-[#141414]";
  }
  return `${border} ${isDark ? "bg-white/[0.025] text-white/55" : "bg-white/45 text-[#6F6A61]"}`;
}

export function PrivacyGuidedSetupPanel({
  steps,
  activeStep,
  children,
  border,
  panel,
  muted,
  isDark,
  onStepChange,
  onShowAdvanced,
}: {
  steps: PrivacyGuidedStep[];
  activeStep: PrivacyGuidedStepId;
  children: ReactNode;
  border: string;
  panel: string;
  muted: string;
  isDark: boolean;
  onStepChange: (step: PrivacyGuidedStepId) => void;
  onShowAdvanced: () => void;
}) {
  const active = steps.find((step) => step.id === activeStep) ?? steps[0];

  return (
    <section id="privacy-guided-setup" className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold">Guided setup</h2>
            <span className={`rounded-md border px-2 py-1 text-xs font-medium ${border} ${muted}`}>
              One panel at a time
            </span>
          </div>
          <p className={`mt-1 max-w-3xl text-sm leading-6 ${muted}`}>
            Follow the same removal workflow without scanning the full operator page.
            Use all details when you need audit controls or troubleshooting.
          </p>
        </div>
        <button
          type="button"
          onClick={onShowAdvanced}
          className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border px-3 text-sm font-semibold transition hover:border-emerald-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:hover:border-emerald-300/50 dark:focus-visible:outline-emerald-300 ${border}`}
        >
          Show all details
          <ChevronDown className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
        {steps.map((step) => {
          const Icon = STEP_ICONS[step.id];
          const selected = step.id === activeStep;
          return (
            <button
              key={step.id}
              type="button"
              onClick={() => onStepChange(step.id)}
              className={`min-h-[104px] rounded-lg border p-3 text-left transition hover:border-emerald-500/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:focus-visible:outline-emerald-300 ${
                selected ? stepTone("current", isDark, border) : stepTone(step.status, isDark, border)
              }`}
              aria-current={selected ? "step" : undefined}
            >
              <div className="flex items-start justify-between gap-2">
                <Icon className="h-4 w-4" />
                {step.status === "done" && <CheckCircle2 className="h-4 w-4 text-emerald-500" />}
              </div>
              <p className="mt-3 text-sm font-semibold">{step.label}</p>
              <p className={`mt-1 text-xs leading-5 ${selected ? "" : muted}`}>{step.detail}</p>
            </button>
          );
        })}
      </div>

      <div className={`mt-4 rounded-lg border ${border}`}>
        <div className={`border-b px-4 py-3 ${border}`}>
          <p className="text-sm font-semibold">{active.label}</p>
          <p className={`mt-1 text-sm leading-6 ${muted}`}>{active.detail}</p>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </section>
  );
}
