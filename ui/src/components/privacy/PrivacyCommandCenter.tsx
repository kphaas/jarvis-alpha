import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  ClipboardCheck,
  Fingerprint,
  Inbox,
  ListChecks,
  SearchCheck,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type {
  ApprovedPrivacyAction,
  CaseDraftSummary,
} from "../../types/privacy";

type NextAction = {
  label: string;
  text: string;
  href: string;
  tone: "primary" | "review" | "quiet";
};

type InboxLane = {
  label: string;
  detail: string;
  count: number;
  href: string;
  Icon: typeof Inbox;
  tone: "ok" | "warn" | "error" | "neutral";
};

function isTerminalAction(action: ApprovedPrivacyAction) {
  return action.status === "confirmed" || action.status === "failed";
}

function deriveNextAction({
  subjectReady,
  selectedTargetCount,
  draftReviewCount,
  approvalReviewCount,
  readyToHandleCount,
  verificationCount,
  completedCaseCount,
}: {
  subjectReady: boolean;
  selectedTargetCount: number;
  draftReviewCount: number;
  approvalReviewCount: number;
  readyToHandleCount: number;
  verificationCount: number;
  completedCaseCount: number;
}): NextAction {
  if (!subjectReady) {
    return {
      label: "Start setup",
      text: "Add the person once. AT-0 encrypts the profile before any packet is created.",
      href: "#privacy-subject-intake",
      tone: "primary",
    };
  }
  if (selectedTargetCount === 0 && draftReviewCount === 0 && approvalReviewCount === 0) {
    return {
      label: "Choose targets",
      text: "Pick the broker or record sites to include in the first removal packet.",
      href: "#privacy-target-registry",
      tone: "primary",
    };
  }
  if (selectedTargetCount > 0 && draftReviewCount === 0) {
    return {
      label: "Create packet",
      text: "Turn selected targets into a local review packet. No outbound send happens.",
      href: "#privacy-review-packet",
      tone: "primary",
    };
  }
  if (draftReviewCount > 0) {
    return {
      label: "Review draft",
      text: "Submit the saved packet to AT-0 approval or archive it.",
      href: "#privacy-draft-inbox",
      tone: "review",
    };
  }
  if (approvalReviewCount > 0) {
    return {
      label: "Open approvals",
      text: "A privacy packet is waiting for human approval before handling.",
      href: "/approvals",
      tone: "review",
    };
  }
  if (readyToHandleCount > 0) {
    return {
      label: "Record handling",
      text: "Approved actions are ready for manual broker handling.",
      href: "#privacy-approved-actions",
      tone: "review",
    };
  }
  if (verificationCount > 0) {
    return {
      label: "Verify removals",
      text: "Manual handling is recorded. Add verification evidence to finish the case.",
      href: "#privacy-approved-actions",
      tone: "review",
    };
  }
  if (completedCaseCount > 0) {
    return {
      label: "Review report",
      text: "Verified cases are complete. Review readiness and evidence coverage.",
      href: "#privacy-removal-readiness",
      tone: "quiet",
    };
  }
  return {
    label: "Choose targets",
    text: "Continue setup by choosing broker or record sites.",
    href: "#privacy-target-registry",
    tone: "primary",
  };
}

function stateLabel({
  subjectReady,
  attentionCount,
  completedCaseCount,
}: {
  subjectReady: boolean;
  attentionCount: number;
  completedCaseCount: number;
}) {
  if (!subjectReady) return "Setup incomplete";
  if (attentionCount > 0) return "Needs review";
  if (completedCaseCount > 0) return "Protected";
  return "Ready to start";
}

function toneClass(
  tone: InboxLane["tone"],
  isDark: boolean,
  border: string,
) {
  if (tone === "ok") {
    return isDark
      ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-100"
      : "border-emerald-800/20 bg-emerald-50 text-emerald-900";
  }
  if (tone === "warn") {
    return isDark
      ? "border-amber-400/30 bg-amber-500/10 text-amber-100"
      : "border-amber-800/20 bg-amber-50 text-amber-900";
  }
  if (tone === "error") {
    return isDark
      ? "border-rose-400/30 bg-rose-500/10 text-rose-100"
      : "border-rose-800/20 bg-rose-50 text-rose-900";
  }
  return `${border} ${isDark ? "bg-white/[0.035]" : "bg-white/55"}`;
}

function primaryActionClass(tone: NextAction["tone"], isDark: boolean) {
  if (tone === "quiet") {
    return isDark
      ? "border-white/10 bg-white/5 text-white hover:border-white/25"
      : "border-[#141414]/12 bg-white text-[#141414] hover:border-[#141414]/30";
  }
  if (tone === "review") {
    return isDark
      ? "border-amber-400/30 bg-amber-500/15 text-amber-100 hover:bg-amber-500/25"
      : "border-amber-800/20 bg-amber-50 text-amber-950 hover:bg-amber-100";
  }
  return "border-emerald-500 bg-emerald-500 text-[#0A0A0A] hover:bg-emerald-400";
}

function ActionLink({
  href,
  children,
  className,
}: {
  href: string;
  children: ReactNode;
  className: string;
}) {
  if (href.startsWith("/")) {
    return (
      <Link to={href} className={className}>
        {children}
      </Link>
    );
  }
  return (
    <a href={href} className={className}>
      {children}
    </a>
  );
}

export function PrivacyCommandCenter({
  subjectReady,
  selectedTargetCount,
  targetCount,
  drafts,
  actions,
  completedCaseCount,
  border,
  panel,
  muted,
  isDark,
}: {
  subjectReady: boolean;
  selectedTargetCount: number;
  targetCount: number;
  drafts: CaseDraftSummary[];
  actions: ApprovedPrivacyAction[];
  completedCaseCount: number;
  border: string;
  panel: string;
  muted: string;
  isDark: boolean;
}) {
  const draftReviewCount = drafts.filter((draft) => draft.status === "draft").length;
  const approvalReviewCount = drafts.filter(
    (draft) => draft.status === "submitted_for_approval",
  ).length;
  const readyToHandleCount = actions.filter(
    (action) => action.status === "approved",
  ).length;
  const verificationCount = actions.filter(
    (action) => action.status === "sent",
  ).length;
  const blockedCount = actions.filter(
    (action) => action.status === "failed" || action.manual_disposition === "blocked",
  ).length;
  const openActionCount = actions.filter((action) => !isTerminalAction(action)).length;
  const attentionCount =
    draftReviewCount +
    approvalReviewCount +
    readyToHandleCount +
    verificationCount +
    blockedCount;
  const nextAction = deriveNextAction({
    subjectReady,
    selectedTargetCount,
    draftReviewCount,
    approvalReviewCount,
    readyToHandleCount,
    verificationCount,
    completedCaseCount,
  });
  const lanes: InboxLane[] = [
    {
      label: "Needs approval",
      detail: "Packets waiting on AT-0 review",
      count: approvalReviewCount,
      href: approvalReviewCount > 0 ? "/approvals" : "#privacy-draft-inbox",
      Icon: ShieldCheck,
      tone: approvalReviewCount > 0 ? "warn" : "neutral",
    },
    {
      label: "Ready to handle",
      detail: "Approved manual removals",
      count: readyToHandleCount,
      href: "#privacy-approved-actions",
      Icon: ClipboardCheck,
      tone: readyToHandleCount > 0 ? "warn" : "neutral",
    },
    {
      label: "Needs verification",
      detail: "Handled actions needing proof",
      count: verificationCount,
      href: "#privacy-approved-actions",
      Icon: ListChecks,
      tone: verificationCount > 0 ? "warn" : "neutral",
    },
    {
      label: "Blocked",
      detail: "Failures or blocked handling",
      count: blockedCount,
      href: "#privacy-approved-actions",
      Icon: AlertCircle,
      tone: blockedCount > 0 ? "error" : "neutral",
    },
  ];
  const status = stateLabel({ subjectReady, attentionCount, completedCaseCount });
  const statusTone =
    status === "Protected"
      ? "ok"
      : status === "Needs review"
        ? "warn"
        : "neutral";

  return (
    <section id="privacy-home" className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(340px,0.72fr)]">
      <div className={`rounded-xl border ${border} ${panel} p-5`}>
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded-md border px-2 py-1 text-xs font-medium ${border} ${muted}`}>
                AT-0 Privacy Agent
              </span>
              <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${toneClass(statusTone, isDark, border)}`}>
                {status}
              </span>
            </div>
            <h2 className="mt-3 text-2xl font-semibold tracking-tight">
              Privacy Home
            </h2>
            <p className={`mt-2 max-w-2xl text-sm leading-6 ${muted}`}>
              One thing at a time: set up the person, choose targets, approve the packet,
              then record handling and verification.
            </p>
          </div>
          <div className={`grid min-w-[12rem] grid-cols-2 overflow-hidden rounded-lg border text-center text-xs ${border}`}>
            <div className={`border-r px-3 py-3 ${border}`}>
              <p className="text-lg font-semibold">{targetCount}</p>
              <p className={muted}>targets</p>
            </div>
            <div className="px-3 py-3">
              <p className="text-lg font-semibold">{completedCaseCount}</p>
              <p className={muted}>verified</p>
            </div>
          </div>
        </div>

        <div className={`mt-5 rounded-lg border p-4 ${toneClass(nextAction.tone === "primary" ? "ok" : nextAction.tone === "review" ? "warn" : "neutral", isDark, border)}`}>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border ${border} ${isDark ? "bg-black/20" : "bg-white/65"}`}>
                <Fingerprint className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm font-semibold">Start here</p>
                <p className="mt-1 text-sm leading-6">{nextAction.text}</p>
              </div>
            </div>
            <ActionLink
              href={nextAction.href}
              className={`inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-lg border px-4 text-sm font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:focus-visible:outline-emerald-300 ${primaryActionClass(nextAction.tone, isDark)}`}
            >
              {nextAction.label}
              <ArrowRight className="h-4 w-4" />
            </ActionLink>
          </div>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <MiniState
            label="Profile"
            value={subjectReady ? "Created" : "Needed"}
            Icon={UserRound}
            border={border}
            muted={muted}
            isReady={subjectReady}
          />
          <MiniState
            label="Targets"
            value={selectedTargetCount > 0 ? `${selectedTargetCount} selected` : "Pick sites"}
            Icon={SearchCheck}
            border={border}
            muted={muted}
            isReady={selectedTargetCount > 0 || draftReviewCount > 0 || openActionCount > 0}
          />
          <MiniState
            label="Reports"
            value={completedCaseCount > 0 ? `${completedCaseCount} ready` : "None yet"}
            Icon={CheckCircle2}
            border={border}
            muted={muted}
            isReady={completedCaseCount > 0}
          />
        </div>
      </div>

      <div id="privacy-action-inbox" className={`rounded-xl border ${border} ${panel} p-5`}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border ${border}`}>
              <Inbox className={isDark ? "h-5 w-5 text-emerald-300" : "h-5 w-5 text-emerald-800"} />
            </div>
            <div>
              <h2 className="text-base font-semibold">Action inbox</h2>
              <p className={`mt-1 text-sm leading-6 ${muted}`}>
                The only items that need operator attention.
              </p>
            </div>
          </div>
          <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${toneClass(attentionCount > 0 ? "warn" : "ok", isDark, border)}`}>
            {attentionCount} waiting
          </span>
        </div>
        <div className="mt-4 space-y-2">
          {lanes.map((lane) => (
            <InboxLaneRow
              key={lane.label}
              lane={lane}
              border={border}
              muted={muted}
              isDark={isDark}
            />
          ))}
        </div>
        {attentionCount === 0 && (
          <div className={`mt-4 rounded-lg border px-3 py-2 text-sm ${toneClass("ok", isDark, border)}`}>
            No operator actions waiting. Start a new removal or review readiness.
          </div>
        )}
      </div>
    </section>
  );
}

function MiniState({
  label,
  value,
  Icon,
  border,
  muted,
  isReady,
}: {
  label: string;
  value: string;
  Icon: typeof Fingerprint;
  border: string;
  muted: string;
  isReady: boolean;
}) {
  return (
    <div className={`rounded-lg border p-3 ${border}`}>
      <div className="flex items-center gap-2">
        <Icon className={isReady ? "h-4 w-4 text-emerald-500" : `h-4 w-4 ${muted}`} />
        <p className={`text-xs font-medium ${muted}`}>{label}</p>
      </div>
      <p className="mt-2 text-sm font-semibold">{value}</p>
    </div>
  );
}

function InboxLaneRow({
  lane,
  border,
  muted,
  isDark,
}: {
  lane: InboxLane;
  border: string;
  muted: string;
  isDark: boolean;
}) {
  const Icon = lane.Icon;
  return (
    <ActionLink
      href={lane.href}
      className={`flex min-h-14 items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left transition hover:border-emerald-500/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:focus-visible:outline-emerald-300 ${toneClass(lane.tone, isDark, border)}`}
    >
      <span className="flex min-w-0 items-center gap-3">
        <Icon className="h-4 w-4 shrink-0" />
        <span className="min-w-0">
          <span className="block text-sm font-semibold">{lane.label}</span>
          <span className={`block truncate text-xs ${lane.tone === "neutral" ? muted : ""}`}>
            {lane.detail}
          </span>
        </span>
      </span>
      <span className="shrink-0 text-lg font-semibold">{lane.count}</span>
    </ActionLink>
  );
}
