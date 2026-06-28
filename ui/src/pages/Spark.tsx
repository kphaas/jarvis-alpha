import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  CircleCheck,
  Copy,
  GitCompareArrows,
  Heart,
  Lightbulb,
  ListChecks,
  LoaderCircle,
  Mail,
  MessagesSquare,
  MessageSquareText,
  PanelTopOpen,
  RefreshCw,
  Send,
  Shield,
  ShieldCheck,
  Sparkles,
  StickyNote,
  ThumbsDown,
  ThumbsUp,
  UserRound,
  UsersRound,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { SparkGuardrailsPanel } from "../components/spark/SparkGuardrailsPanel";
import { SparkMemoryReviewPanel } from "../components/spark/SparkMemoryReviewPanel";
import { SparkTargetMemoryPanel } from "../components/spark/SparkTargetMemoryPanel";
import {
  useSparkDraftReview,
  useSparkIMessageDraftTargets,
  useSparkIMessageOutbox,
  useSparkIMessageTargetPreview,
} from "../hooks/useSparkDraftReview";
import { useSparkGuardrails } from "../hooks/useSparkGuardrails";
import { useAppStore } from "../store";
import type {
  SparkDraftFeedbackLabel,
  SparkIMessageDraftContextMessage,
  SparkIMessageDraftResponse,
  SparkIMessageOutboxItem,
  SparkIMessageDraftTarget,
  SparkIMessageTargetPreviewResponse,
  SparkProtectedRelationship,
} from "../types/spark";

const SPARK_PRINCIPALS = [
  { id: "ken", label: "Ken" },
  { id: "sweta", label: "Sweta" },
  { id: "ryleigh", label: "Ryleigh" },
  { id: "sloane", label: "Sloane" },
];

type SparkPrincipalId = "ken" | "sweta" | "ryleigh" | "sloane";
type SparkTargetId = SparkPrincipalId | "meagan";

const SPARK_DRAFT_TARGETS = [
  ...SPARK_PRINCIPALS,
  { id: "meagan", label: "Meagan" },
];

const SPARK_PRINCIPAL_LABELS: Record<SparkPrincipalId, string> = {
  ken: "Ken",
  sweta: "Sweta",
  ryleigh: "Ryleigh",
  sloane: "Sloane",
};

const SPARK_TARGET_LABELS: Record<SparkTargetId, string> = {
  ...SPARK_PRINCIPAL_LABELS,
  meagan: "Meagan",
};

const FEEDBACK_BUTTONS: Array<{
  label: string;
  value: SparkDraftFeedbackLabel;
  tone: "ok" | "warn";
}> = [
  { label: "Keep this direction", value: "sounds_like_me", tone: "ok" },
  { label: "Wrong context", value: "out_of_context", tone: "warn" },
  { label: "Too robotic", value: "too_robotic", tone: "warn" },
  { label: "Too formal", value: "too_formal", tone: "warn" },
  { label: "Too wordy", value: "too_wordy", tone: "warn" },
  { label: "Too much policy", value: "too_much_policy", tone: "warn" },
];

const TONE_OPTIONS = [
  { label: "Happier", value: "Make the reply a little happier." },
  { label: "Sweeter", value: "Make the reply sweeter and more affectionate." },
  { label: "Relaxed", value: "Make the reply sound relaxed and natural." },
  { label: "Serious", value: "Make the reply more serious and grounded." },
  { label: "Confident", value: "Make the reply more confident and decisive." },
  { label: "Smart", value: "Make the reply sharper and more thoughtful." },
  { label: "Blunt", value: "Make the reply direct and blunt, but still respectful." },
];

function feedbackDisplayLabels(values: SparkDraftFeedbackLabel[]) {
  if (!values.length) return null;
  return values
    .map((value) => FEEDBACK_BUTTONS.find((item) => item.value === value)?.label ?? value)
    .join(" + ");
}

const DEFAULT_FAVORITE_TARGETS: SparkProtectedRelationship[] = [
  {
    id: "ken",
    label: "Ken",
    relationship: "family",
    sensitivity: "family",
    default_mode: "draft_only",
    approval_required: true,
  },
  {
    id: "sweta",
    label: "Sweta",
    relationship: "partner",
    sensitivity: "relationship",
    default_mode: "hybrid_review",
    approval_required: true,
  },
  {
    id: "ryleigh",
    label: "Ryleigh",
    relationship: "child",
    sensitivity: "minor",
    default_mode: "draft_only",
    approval_required: true,
  },
  {
    id: "sloane",
    label: "Sloane",
    relationship: "child",
    sensitivity: "minor",
    default_mode: "draft_only",
    approval_required: true,
  },
  {
    id: "meagan",
    label: "Meagan",
    relationship: "co-parent",
    sensitivity: "relationship",
    default_mode: "draft_only",
    approval_required: true,
  },
];

type DetailPanel =
  | "thread"
  | "memory-debug"
  | "guardrails"
  | "memory-review"
  | "target-memory";

interface DraftTargetOption {
  id: string;
  label: string;
  relationship: string;
  sensitivity: string;
  approvalId: string | null;
  channel: string;
  favorite: boolean;
  ready: boolean;
}

type CockpitStepStatus = "complete" | "active" | "blocked" | "idle" | "error";

interface CockpitStep {
  id: string;
  label: string;
  detail: string;
  status: CockpitStepStatus;
}

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

function shortHash(value: string) {
  return `${value.slice(0, 10)}...${value.slice(-8)}`;
}

function normalizedKey(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function displayLabel(value: string) {
  if (value.trim().toLowerCase() === "minor") return "child";
  return value.replace(/_/g, " ");
}

function isChildPrincipal(principalId: SparkPrincipalId) {
  return principalId === "ryleigh" || principalId === "sloane";
}

function parseSparkPrincipalId(value: string | null): SparkPrincipalId | null {
  if (!value) return null;
  const match = SPARK_PRINCIPALS.find(
    (principal) => principal.id === normalizedKey(value),
  );
  return (match?.id as SparkPrincipalId | undefined) ?? null;
}

function targetIdFromLabel(value: string | null): SparkTargetId | null {
  if (!value) return null;
  const normalized = normalizedKey(value);
  const match = SPARK_DRAFT_TARGETS.find(
    (target) =>
      normalizedKey(target.id) === normalized ||
      normalizedKey(target.label) === normalized,
  );
  return (match?.id as SparkTargetId | undefined) ?? null;
}

function pairRelationship(
  principalId: SparkPrincipalId,
  targetId: SparkTargetId,
) {
  const principalIsChild = isChildPrincipal(principalId);
  const targetIsChild = targetId !== "meagan" && isChildPrincipal(targetId);
  if (!principalIsChild && !targetIsChild) return "partner";
  if (principalIsChild && targetIsChild) return "sibling";
  return targetIsChild ? "child" : "parent";
}

function fallbackSensitivity(
  principalId: SparkPrincipalId,
  targetId: SparkTargetId,
) {
  if (targetId !== "meagan" && isChildPrincipal(targetId)) return "minor";
  if (pairRelationship(principalId, targetId) === "partner") return "relationship";
  return "family";
}

function buildDraftTargetOptions(
  principalId: SparkPrincipalId,
  relationships: SparkProtectedRelationship[],
  targets: SparkIMessageDraftTarget[],
): DraftTargetOption[] {
  const relationshipById = new Map(
    relationships.map((relationship) => [
      normalizedKey(relationship.id),
      relationship,
    ]),
  );
  const targetByLabel = new Map(
    targets.map((target) => [normalizedKey(target.label), target]),
  );
  const candidateIds = SPARK_DRAFT_TARGETS.map(
    (target) => target.id as SparkTargetId,
  ).filter((targetId) => targetId !== principalId);

  return candidateIds.map((targetId) => {
    const configuredRelationship =
      relationshipById.get(normalizedKey(targetId)) ??
      DEFAULT_FAVORITE_TARGETS.find((relationship) => relationship.id === targetId) ??
      null;
    const label =
      configuredRelationship?.label ?? SPARK_TARGET_LABELS[targetId];
    const target =
      targetByLabel.get(normalizedKey(label)) ??
      targets.find((item) => normalizedKey(item.label) === normalizedKey(targetId));
    return {
      id: targetId,
      label,
      relationship:
        configuredRelationship?.relationship ?? pairRelationship(principalId, targetId),
      sensitivity:
        configuredRelationship?.sensitivity ??
        fallbackSensitivity(principalId, targetId),
      approvalId: target?.approval_id ?? null,
      channel: target?.channel ?? "iMessage",
      favorite: true,
      ready: Boolean(target?.approval_id),
    };
  });
}

function ErrorLine({ text, className }: { text: string; className: string }) {
  return (
    <div
      className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${className}`}
    >
      <AlertTriangle className="h-4 w-4 shrink-0" />
      <span>{text}</span>
    </div>
  );
}

function StatusChip({
  label,
  className,
}: {
  label: string;
  className: string;
}) {
  return (
    <span
      className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${className}`}
    >
      {label}
    </span>
  );
}

function stepTone(
  status: CockpitStepStatus,
  okClass: string,
  warnClass: string,
  errorClass: string,
  border: string,
) {
  if (status === "complete") return okClass;
  if (status === "active") return warnClass;
  if (status === "error") return errorClass;
  if (status === "blocked") return `${warnClass} opacity-75`;
  return `${border} opacity-70`;
}

function MetricRow({
  label,
  value,
  muted,
}: {
  label: string;
  value: string | number;
  muted: string;
}) {
  return (
    <div className="flex min-h-11 items-center justify-between gap-3 border-b border-current/10 py-2 last:border-b-0">
      <span
        className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
      >
        {label}
      </span>
      <span className="min-w-0 truncate text-right text-sm font-semibold">
        {value}
      </span>
    </div>
  );
}

function labelize(value: string) {
  return displayLabel(value);
}

function formatTimestamp(value: string | null | undefined) {
  if (!value) return "not yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function outboxHint(item: SparkIMessageOutboxItem) {
  if (item.status === "sent") return "Sent and recorded";
  if (item.status === "send_failed") return "Last send attempt failed";
  if (item.status === "sending") return "Send in progress";
  if (item.status === "pending_approval") return "Waiting for approval before send";
  if (item.status === "cancelled") return "Final, cancelled";
  return "Review status before action";
}

function DraftMetadata({
  draft,
  muted,
}: {
  draft: SparkIMessageDraftResponse;
  muted: string;
}) {
  return (
    <div className="space-y-1">
      <MetricRow
        label="Context read"
        value={draft.context_messages_read}
        muted={muted}
      />
      <MetricRow
        label="Sent examples"
        value={draft.principal_sent_messages}
        muted={muted}
      />
      <MetricRow
        label="Runtime context"
        value={draft.runtime_context_messages}
        muted={muted}
      />
      <MetricRow
        label="Draft engine"
        value={draft.draft_engine.replace(/_/g, " ")}
        muted={muted}
      />
      <MetricRow
        label="Approval hash"
        value={shortHash(draft.approval_ref_hash)}
        muted={muted}
      />
      <MetricRow
        label="Thread hash"
        value={shortHash(draft.chat_guid_hash)}
        muted={muted}
      />
      <MetricRow
        label="Sensitivity"
        value={
          draft.detected_sensitivity.length
            ? draft.detected_sensitivity.join(", ")
            : "clear"
        }
        muted={muted}
      />
    </div>
  );
}

function ConversationBriefPanel({
  draft,
  preview,
  previewLoading,
  previewError,
  selectedPrincipalLabel,
  selectedTargetLabel,
  selectedTargetReady,
  onRefreshPreview,
  border,
  panel,
  muted,
  okClass,
  warnClass,
}: {
  draft: SparkIMessageDraftResponse | null;
  preview: SparkIMessageTargetPreviewResponse | null;
  previewLoading: boolean;
  previewError: unknown;
  selectedPrincipalLabel: string;
  selectedTargetLabel: string | null;
  selectedTargetReady: boolean;
  onRefreshPreview: () => void;
  border: string;
  panel: string;
  muted: string;
  okClass: string;
  warnClass: string;
}) {
  const summary = draft?.conversation_summary ?? preview?.conversation_summary;
  const statusLabel = draft
    ? "draft context"
    : previewLoading
      ? "loading thread"
      : preview
        ? "target preview"
        : "pick target";

  return (
    <section className={`rounded-xl border ${border} ${panel} p-4`}>
      <div className="grid gap-3 lg:grid-cols-[minmax(220px,0.7fr)_minmax(0,1.3fr)]">
        <div className="flex flex-wrap items-center gap-2">
          <UserRound className="h-4 w-4 text-emerald-400" />
          <span className={`text-[10px] font-mono uppercase ${muted}`}>
            Drafting to
          </span>
          <span
            className={`rounded-md border px-2 py-1 text-sm font-bold ${okClass}`}
          >
            {summary?.reply_target_label ??
              selectedTargetLabel ??
              "Pick target first"}
          </span>
          <span
            className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${warnClass}`}
          >
            Voice: {summary?.voice_principal_label ?? selectedPrincipalLabel}
          </span>
          <span
            className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${
              previewError ? warnClass : okClass
            }`}
          >
            {statusLabel}
          </span>
          {selectedTargetReady && (
            <button
              type="button"
              onClick={onRefreshPreview}
              className={`inline-flex min-h-8 items-center gap-1.5 rounded-md border px-2 text-[10px] font-mono uppercase ${okClass}`}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh preview
            </button>
          )}
          {!summary && selectedTargetLabel && !selectedTargetReady && (
            <span
              className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${warnClass}`}
            >
              needs approved thread
            </span>
          )}
        </div>
        <div className={`min-w-0 rounded-lg border p-3 ${border}`}>
          <div className="flex flex-wrap items-center gap-2">
            <MessagesSquare className="h-4 w-4 text-emerald-400" />
            <span className={`text-[10px] font-mono uppercase ${muted}`}>
              Last thread message
            </span>
            {summary?.last_message_speaker && (
              <span
                className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${
                  summary.last_message_speaker === "Ken" ? okClass : warnClass
                }`}
              >
                {summary.last_message_speaker}
              </span>
            )}
          </div>
          <p className="mt-2 line-clamp-3 text-sm leading-relaxed">
            {previewError
              ? "Thread preview is unavailable for this target."
              : summary?.last_message_preview ??
                "Pick a ready target to load the last 8 texts before drafting."}
          </p>
        </div>
      </div>
    </section>
  );
}

function ReplyCockpitStepper({
  steps,
  border,
  panel,
  muted,
  okClass,
  warnClass,
  errorClass,
}: {
  steps: CockpitStep[];
  border: string;
  panel: string;
  muted: string;
  okClass: string;
  warnClass: string;
  errorClass: string;
}) {
  return (
    <section className={`rounded-xl border ${border} ${panel} p-4`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ListChecks className="h-4 w-4 text-emerald-400" />
          <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>
            Reply cockpit
          </h2>
        </div>
        <StatusChip label="approval before send" className={warnClass} />
      </div>
      <div className="mt-4 grid gap-2 md:grid-cols-3 2xl:grid-cols-6">
        {steps.map((step, index) => {
          const className = stepTone(
            step.status,
            okClass,
            warnClass,
            errorClass,
            border,
          );
          return (
            <div key={step.id} className={`rounded-lg border p-3 ${className}`}>
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-bold">{step.label}</span>
                <span className="font-mono text-[10px]">
                  {String(index + 1).padStart(2, "0")}
                </span>
              </div>
              <p className="mt-2 min-h-10 text-xs leading-relaxed">{step.detail}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function DraftTargetPicker({
  targets,
  selectedTargetId,
  loading,
  onSelect,
  onManageRelationships,
  border,
  panel,
  muted,
  okClass,
  warnClass,
}: {
  targets: DraftTargetOption[];
  selectedTargetId: string | null;
  loading: boolean;
  onSelect: (targetId: string) => void;
  onManageRelationships: () => void;
  border: string;
  panel: string;
  muted: string;
  okClass: string;
  warnClass: string;
}) {
  return (
    <section className={`rounded-xl border ${border} ${panel} p-4`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <UsersRound className="h-4 w-4 text-emerald-400" />
          <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>
            Draft target
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusChip
            label={loading ? "loading approved threads" : "core family"}
            className={loading ? warnClass : okClass}
          />
          <button
            type="button"
            onClick={onManageRelationships}
            className={`inline-flex min-h-9 items-center gap-2 rounded-lg border px-3 text-xs font-bold transition hover:border-emerald-400 ${border}`}
          >
            Relationships
          </button>
        </div>
      </div>
      <p className={`mt-3 text-xs ${muted}`}>
        Spark hides the active voice profile here and only shows the other core-family targets.
      </p>

      <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-5">
        {targets.map((target) => {
          const selected = target.id === selectedTargetId;
          return (
            <button
              key={target.id}
              type="button"
              onClick={() => onSelect(target.id)}
              className={`min-h-24 rounded-lg border p-3 text-left transition ${border} ${
                selected
                  ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-200"
                  : ""
              } hover:border-emerald-400 ${target.ready ? "" : "opacity-70"}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-bold">{target.label}</div>
                  <div className={`mt-1 text-xs ${muted}`}>
                    {displayLabel(target.relationship)}
                  </div>
                </div>
                <Heart
                  className={`h-4 w-4 shrink-0 ${
                    target.favorite ? "fill-emerald-400 text-emerald-400" : muted
                  }`}
                />
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <span
                  className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${
                    target.ready ? okClass : warnClass
                  }`}
                >
                  {target.ready ? "ready" : "needs approved thread"}
                </span>
                <span
                  className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${warnClass}`}
                >
                  {displayLabel(target.sensitivity)}
                </span>
              </div>
            </button>
          );
        })}
      </div>

      {!targets.length && (
        <div className={`mt-3 rounded-lg border p-3 text-sm ${border} ${muted}`}>
          No favorite targets loaded yet.
        </div>
      )}
    </section>
  );
}

function ApprovedThreadOnboardingPanel({
  principalLabel,
  targets,
  border,
  panel,
  muted,
  okClass,
  warnClass,
}: {
  principalLabel: string;
  targets: DraftTargetOption[];
  border: string;
  panel: string;
  muted: string;
  okClass: string;
  warnClass: string;
}) {
  const readyTargets = targets.filter((target) => target.ready);
  const missingTargets = targets.filter((target) => !target.ready);

  return (
    <section className={`rounded-xl border ${border} ${panel} p-4`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Shield className="h-4 w-4 text-emerald-400" />
          <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>
            Approved-thread onboarding
          </h2>
        </div>
        <StatusChip
          label={`${readyTargets.length}/${targets.length || 1} ready`}
          className={missingTargets.length ? warnClass : okClass}
        />
      </div>
      <p className={`mt-3 text-sm leading-relaxed ${muted}`}>
        Favorites and relationship labels shape the roster. Spark can only draft
        against approved iMessage threads for the active voice profile.
      </p>

      {missingTargets.length ? (
        <div className="mt-4 grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
          {missingTargets.map((target) => (
            <article key={`${target.id}-onboarding`} className={`rounded-lg border p-3 ${border}`}>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-sm font-bold">{target.label}</div>
                  <div className={`mt-1 text-xs ${muted}`}>
                    {principalLabel} to {target.label} · {displayLabel(target.relationship)}
                  </div>
                </div>
                <StatusChip label="needs thread" className={warnClass} />
              </div>
              <p className={`mt-3 text-xs leading-relaxed ${muted}`}>
                Approve one iMessage source record for this pair, then refresh Spark
                to unlock thread preview, drafting, and approved send.
              </p>
            </article>
          ))}
        </div>
      ) : (
        <div className={`mt-4 rounded-lg border px-3 py-3 text-sm ${okClass}`}>
          All core-family targets for {principalLabel} already have approved iMessage
          threads.
        </div>
      )}
    </section>
  );
}

function RecentThreadStrip({
  context,
  loading,
  error,
  border,
  muted,
  okClass,
  warnClass,
}: {
  context: SparkIMessageDraftContextMessage[];
  loading: boolean;
  error: unknown;
  border: string;
  muted: string;
  okClass: string;
  warnClass: string;
}) {
  const recent = context.slice(0, 8);
  return (
    <div className={`rounded-lg border p-3 ${border}`}>
      <div className="flex items-center justify-between gap-3">
        <span className={`text-[10px] font-mono uppercase ${muted}`}>
          Recent thread
        </span>
        <span className={`text-[10px] font-mono uppercase ${muted}`}>
          last {recent.length || 8} texts
        </span>
      </div>
      {loading ? (
        <div className="mt-3 space-y-2">
          {Array.from({ length: 3 }).map((_, index) => (
            <div
              key={index}
              className={`h-14 animate-pulse rounded-lg border ${border}`}
            />
          ))}
        </div>
      ) : error ? (
        <p className={`mt-3 text-sm ${muted}`}>
          Thread preview is unavailable for this target.
        </p>
      ) : recent.length ? (
        <div className="mt-3 space-y-2">
          {recent.map((message) => (
            <div key={`${message.message_ref_hash}-brief`}>
              <div className="flex items-center gap-2">
                <span
                  className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${
                    message.is_from_me ? okClass : warnClass
                  }`}
                >
                  {message.speaker}
                </span>
                <span className={`truncate text-[10px] font-mono ${muted}`}>
                  {shortHash(message.message_ref_hash)}
                </span>
              </div>
              <p className="mt-1 line-clamp-2 text-sm leading-relaxed">
                {message.body_text}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <p className={`mt-3 text-sm ${muted}`}>
          Click a ready draft target to load the last 8 texts here.
        </p>
      )}
    </div>
  );
}

function DraftQualityPanel({
  draft,
  border,
  muted,
  okClass,
  warnClass,
  errorClass,
}: {
  draft: SparkIMessageDraftResponse | null;
  border: string;
  muted: string;
  okClass: string;
  warnClass: string;
  errorClass: string;
}) {
  if (!draft) return null;
  const quality = draft.draft_quality;
  const scoreClass =
    quality.verdict === "strong"
      ? okClass
      : quality.verdict === "needs_edit"
        ? errorClass
        : warnClass;

  return (
    <div className={`rounded-lg border p-3 ${border}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <CircleCheck className="h-4 w-4 text-emerald-400" />
          <span className={`text-[10px] font-mono uppercase ${muted}`}>
            Ken-like score
          </span>
        </div>
        <span
          className={`rounded-md border px-2 py-1 text-sm font-bold ${scoreClass}`}
        >
          {quality.score}% {labelize(quality.verdict)}
        </span>
      </div>
      <div className="mt-3 space-y-2">
        {quality.checks.map((check) => (
          <div key={check.key} className="flex gap-2 text-sm">
            <CheckCircle2
              className={`mt-0.5 h-4 w-4 shrink-0 ${
                check.passed ? "text-emerald-400" : "text-amber-400"
              }`}
            />
            <div className="min-w-0">
              <div className="font-semibold">{check.label}</div>
              <div className={`text-xs ${muted}`}>{check.detail}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SourceReadinessPanel({
  draft,
  border,
  muted,
  okClass,
  warnClass,
}: {
  draft: SparkIMessageDraftResponse | null;
  border: string;
  muted: string;
  okClass: string;
  warnClass: string;
}) {
  if (!draft) return null;
  return (
    <div className={`rounded-lg border p-3 ${border}`}>
      <div className="flex items-center gap-2">
        <Mail className="h-4 w-4 text-emerald-400" />
        <span className={`text-[10px] font-mono uppercase ${muted}`}>
          Channel parity
        </span>
      </div>
      <div className="mt-3 space-y-2">
        {draft.source_readiness.map((item) => (
          <div key={`${item.source}-${item.status}`} className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${
                  item.status === "live_runtime_context" ? okClass : warnClass
                }`}
              >
                {item.channel}
              </span>
              <span className={`text-[10px] font-mono uppercase ${muted}`}>
                {labelize(item.status)}
              </span>
            </div>
            <p className={`text-xs ${muted}`}>{item.detail}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function ThreadContextPanel({
  draft,
  preview,
  previewLoading,
  previewError,
  border,
  panel,
  muted,
  okClass,
  warnClass,
}: {
  draft: SparkIMessageDraftResponse | null;
  preview: SparkIMessageTargetPreviewResponse | null;
  previewLoading: boolean;
  previewError: unknown;
  border: string;
  panel: string;
  muted: string;
  okClass: string;
  warnClass: string;
}) {
  const context = draft?.context_preview ?? preview?.context_preview ?? [];

  return (
    <section className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <MessagesSquare className="h-4 w-4 text-emerald-400" />
          <h2
            className={`text-xs font-mono uppercase tracking-widest ${muted}`}
          >
            Thread context
          </h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusChip label="runtime only" className={okClass} />
          <StatusChip label="newest first" className={warnClass} />
        </div>
      </div>

      {previewLoading ? (
        <div className="mt-4 space-y-3">
          {Array.from({ length: 4 }).map((_, index) => (
            <div
              key={index}
              className={`h-20 animate-pulse rounded-lg border ${border}`}
            />
          ))}
        </div>
      ) : previewError ? (
        <div
          className={`mt-4 flex min-h-28 items-center justify-center rounded-lg border ${border}`}
        >
          <span className={`text-sm ${muted}`}>
            Thread preview is unavailable for this target.
          </span>
        </div>
      ) : context.length ? (
        <div className="mt-4 space-y-3">
          {context.map((message) => (
            <div
              key={`${message.message_ref_hash}-${message.index}`}
              className={`rounded-lg border p-3 ${border}`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span
                  className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${
                    message.is_from_me ? okClass : warnClass
                  }`}
                >
                  {message.speaker}
                </span>
                <span className={`text-[10px] font-mono uppercase ${muted}`}>
                  {shortHash(message.message_ref_hash)}
                </span>
              </div>
              <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-relaxed">
                {message.body_text}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <div
          className={`mt-4 flex min-h-28 items-center justify-center rounded-lg border ${border}`}
        >
          <span className={`text-sm ${muted}`}>
            Click a ready draft target to view the last 8 texts.
          </span>
        </div>
      )}
    </section>
  );
}

function DraftMemoryDebugPanel({
  draft,
  approval,
  border,
  panel,
  muted,
  okClass,
  warnClass,
}: {
  draft: SparkIMessageDraftResponse | null;
  approval: ReturnType<typeof useSparkDraftReview>["approval"];
  border: string;
  panel: string;
  muted: string;
  okClass: string;
  warnClass: string;
}) {
  const voiceMemory = draft?.personality_memory_preview ?? [];
  const targetMemory = draft?.target_memory_preview ?? [];
  const phrases = approval?.candidate_key_phrases ?? [];
  const lessons = approval?.calibration_lessons ?? [];

  return (
    <section className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-emerald-400" />
          <h2
            className={`text-xs font-mono uppercase tracking-widest ${muted}`}
          >
            Draft memory
          </h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusChip label={`${voiceMemory.length} voice`} className={okClass} />
          <StatusChip label={`${targetMemory.length} target`} className={okClass} />
          <StatusChip label="silent in draft" className={warnClass} />
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <div className="space-y-3">
          <div className="space-y-3">
            <span
              className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
            >
              Voice profile memory
            </span>
            {voiceMemory.length ? (
              voiceMemory.map((item, index) => (
                <div
                  key={`voice-${item.kind}-${item.evidence_ref_hash ?? index}`}
                  className={`rounded-lg border p-3 ${border}`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${okClass}`}
                    >
                      {labelize(item.kind)}
                    </span>
                    <span className={`text-[10px] font-mono uppercase ${muted}`}>
                      {labelize(item.source)}
                    </span>
                  </div>
                  <p className="mt-2 text-sm leading-relaxed">{item.content}</p>
                </div>
              ))
            ) : (
              <div className={`rounded-lg border p-4 text-sm ${border} ${muted}`}>
                No reviewed voice memory attached to this draft yet
              </div>
            )}
          </div>

          <div className="space-y-3">
            <span
              className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
            >
              Selected target memory
            </span>
            {targetMemory.length ? (
              targetMemory.map((item, index) => (
                <div
                  key={`target-${item.kind}-${item.evidence_ref_hash ?? index}`}
                  className={`rounded-lg border p-3 ${border}`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${warnClass}`}
                    >
                      {labelize(item.kind)}
                    </span>
                    <span className={`text-[10px] font-mono uppercase ${muted}`}>
                      {labelize(item.source)}
                    </span>
                  </div>
                  <p className="mt-2 text-sm leading-relaxed">{item.content}</p>
                  {item.reason && (
                    <p className={`mt-2 text-xs ${muted}`}>{item.reason}</p>
                  )}
                </div>
              ))
            ) : (
              <div className={`rounded-lg border p-4 text-sm ${border} ${muted}`}>
                No selected-target memory was used for this draft
              </div>
            )}
          </div>
        </div>

        <div className="space-y-3">
          <span
            className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
          >
            Edit learning
          </span>
          {approval?.voice_feedback_recorded ? (
            <div className={`rounded-lg border p-3 ${border}`}>
              <div className="flex items-center gap-2 text-sm font-semibold">
                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                Spark captured this edit for review
              </div>
              {phrases.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {phrases.map((phrase) => (
                    <span
                      key={phrase}
                      className={`rounded-md border px-2 py-1 text-xs ${warnClass}`}
                    >
                      {phrase}
                    </span>
                  ))}
                </div>
              )}
              {lessons.length > 0 && (
                <div className="mt-3 space-y-2">
                  {lessons.map((lesson) => (
                    <div
                      key={lesson}
                      className={`rounded-md border px-2 py-1 text-xs ${okClass}`}
                    >
                      {lesson}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className={`rounded-lg border p-4 text-sm ${border} ${muted}`}>
              Edit the draft, submit for approval, and Spark will turn useful
              changes into reviewed memory proposals
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function OutboxCockpitPanel({
  items,
  loading,
  error,
  onRefresh,
  border,
  panel,
  muted,
  okClass,
  warnClass,
  errorClass,
}: {
  items: SparkIMessageOutboxItem[];
  loading: boolean;
  error: unknown;
  onRefresh: () => void;
  border: string;
  panel: string;
  muted: string;
  okClass: string;
  warnClass: string;
  errorClass: string;
}) {
  return (
    <section className={`rounded-xl border ${border} ${panel} p-4`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Send className="h-4 w-4 text-emerald-400" />
          <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>
            Outbox cockpit
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusChip label="metadata only" className={okClass} />
          <button
            type="button"
            onClick={onRefresh}
            className={`inline-flex min-h-9 items-center gap-2 rounded-lg border px-3 text-xs font-bold ${border}`}
          >
            <RefreshCw className="h-4 w-4" />
            Refresh outbox
          </button>
        </div>
      </div>

      {loading ? (
        <div className="mt-4 grid gap-3 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <div
              key={index}
              className={`h-32 animate-pulse rounded-lg border ${border}`}
            />
          ))}
        </div>
      ) : error ? (
        <div className={`mt-4 rounded-lg border px-3 py-2 text-sm ${errorClass}`}>
          Outbox metadata is unavailable
        </div>
      ) : items.length ? (
        <div className="mt-4 grid gap-3 lg:grid-cols-3">
          {items.map((item) => {
            const statusClass =
              item.status === "sent"
                ? okClass
                : item.status === "send_failed"
                  ? errorClass
                  : warnClass;
            return (
              <article key={item.outbox_id} className={`rounded-lg border p-3 ${border}`}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-bold">
                      {item.target_label}
                    </div>
                    <div className={`mt-1 text-xs ${muted}`}>
                      {formatTimestamp(item.updated_at)}
                    </div>
                  </div>
                  <StatusChip label={labelize(item.status)} className={statusClass} />
                </div>
                <p className={`mt-3 text-xs leading-relaxed ${muted}`}>
                  {outboxHint(item)}
                </p>
                <div className="mt-3 space-y-1">
                  <MetricRow
                    label="Attempts"
                    value={item.send_attempt_count}
                    muted={muted}
                  />
                  <MetricRow
                    label="Approval"
                    value={shortHash(item.approval_queue_id)}
                    muted={muted}
                  />
                  <MetricRow
                    label="Draft hash"
                    value={shortHash(item.draft_text_hash)}
                    muted={muted}
                  />
                  <MetricRow
                    label="Sent"
                    value={formatTimestamp(item.sent_at)}
                    muted={muted}
                  />
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className={`mt-4 rounded-lg border p-4 text-sm ${border} ${muted}`}>
          No Spark outbox records yet. Submit approval to create the first
          metadata-only outbox item.
        </div>
      )}
    </section>
  );
}

function DetailOverviewCard({
  title,
  detail,
  metric,
  icon,
  onOpen,
  border,
  muted,
  okClass,
}: {
  title: string;
  detail: string;
  metric: string;
  icon: ReactNode;
  onOpen: () => void;
  border: string;
  muted: string;
  okClass: string;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={`min-h-32 rounded-lg border p-4 text-left transition hover:border-emerald-400 ${border}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          {icon}
          <span className="text-sm font-bold">{title}</span>
        </div>
        <PanelTopOpen className="h-4 w-4 shrink-0 text-emerald-400" />
      </div>
      <p className={`mt-3 text-sm leading-relaxed ${muted}`}>{detail}</p>
      <span
        className={`mt-4 inline-flex rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${okClass}`}
      >
        {metric}
      </span>
    </button>
  );
}

function DetailDialog({
  title,
  children,
  onClose,
  border,
  panel,
  muted,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  border: string;
  panel: string;
  muted: string;
}) {
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 overflow-y-auto bg-black/65 px-4 py-6 backdrop-blur-md md:px-6 md:py-10"
    >
      <div className="flex min-h-full items-start justify-center md:items-center">
        <motion.section
          initial={{ opacity: 0, y: 18, scale: 0.985 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 12, scale: 0.99 }}
          transition={{ duration: 0.18, ease: "easeOut" }}
          role="dialog"
          aria-modal="true"
          aria-label={title}
          className={`grid w-full max-w-6xl grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-[26px] border ${border} ${panel} shadow-[0_28px_90px_-28px_rgba(0,0,0,0.85)]`}
        >
          <div className={`border-b ${border}`}>
            <div
              className={`flex items-center justify-between gap-4 border-b px-4 py-3 ${border} md:px-5`}
            >
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full bg-rose-400/80" />
                <span className="h-2.5 w-2.5 rounded-full bg-amber-300/80" />
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-400/80" />
              </div>
              <span className={`text-[10px] font-mono uppercase tracking-[0.24em] ${muted}`}>
                Spark detail window
              </span>
              <div className="w-14 shrink-0" />
            </div>
            <div className="flex items-start justify-between gap-4 px-4 py-4 md:px-5 md:py-5">
              <div className="space-y-2">
                <div>
                  <h2 className="text-xl font-bold">{title}</h2>
                  <p className={`mt-1 text-sm ${muted}`}>
                    Review context and memory here. Keep send actions outside this window.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-bold transition hover:border-emerald-400 ${border}`}
              >
                <X className="h-4 w-4" />
                Close
              </button>
            </div>
          </div>
          <div className="min-h-0 overflow-y-auto px-4 pb-4 pt-4 md:px-5 md:pb-5">
            {children}
          </div>
        </motion.section>
      </div>
    </motion.div>
  );
}

function ToneSelect({
  border,
  input,
  muted,
  value,
  onChange,
}: {
  border: string;
  input: string;
  muted: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span
        className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
      >
        Tone direction
      </span>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className={`h-11 min-w-0 flex-1 rounded-lg border px-3 text-sm outline-none transition focus:border-emerald-400 ${input}`}
        >
          <option value="">Default</option>
          {TONE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        {value && (
          <button
            type="button"
            onClick={() => onChange("")}
            className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm font-bold transition hover:border-emerald-400 ${border}`}
          >
            Clear
          </button>
        )}
      </div>
      <p className={`mt-2 text-xs ${muted}`}>
        Optional adjustment for the next draft.
      </p>
    </label>
  );
}

function FeedbackSelectionHint({
  muted,
  selectedCount,
}: {
  muted: string;
  selectedCount: number;
}) {
  const remaining = Math.max(0, 2 - selectedCount);
  return (
    <p className={`text-xs ${muted}`}>
      {selectedCount
        ? `${selectedCount} selected, ${remaining} slot${remaining === 1 ? "" : "s"} left.`
        : "Pick up to 2 signals before retrying."}
    </p>
  );
}

export default function Spark() {
  const { theme } = useAppStore();
  const [searchParams] = useSearchParams();
  const activeApproval = searchParams.get("approval");
  const requestedPrincipalId =
    parseSparkPrincipalId(searchParams.get("principal")) ?? "ken";
  const requestedTargetId = targetIdFromLabel(searchParams.get("target"));
  const [principalId, setPrincipalId] = useState<SparkPrincipalId>(
    requestedPrincipalId,
  );
  const [draftTargetId, setDraftTargetId] = useState<string | null>(null);
  const [detailPanel, setDetailPanel] = useState<DetailPanel | null>(null);
  const guardrailsState = useSparkGuardrails();
  const targetState = useSparkIMessageDraftTargets(principalId);
  const outboxState = useSparkIMessageOutbox(principalId);
  const isDark = theme === "dark";
  const border = isDark ? "border-white/10" : "border-[#141414]/10";
  const panel = isDark ? "bg-white/5" : "bg-[#141414]/5";
  const input = isDark
    ? "bg-[#0A0A0A] border-white/10"
    : "bg-[#E4E3E0] border-[#141414]/15";
  const muted = isDark ? "text-white/45" : "text-[#141414]/50";
  const strong = isDark ? "text-white" : "text-[#141414]";
  const okClass = tone(isDark, "ok");
  const warnClass = tone(isDark, "warn");
  const errorClass = tone(isDark, "error");
  const selectedPrincipal =
    SPARK_PRINCIPALS.find((principal) => principal.id === principalId) ??
    SPARK_PRINCIPALS[0];
  const favoriteRelationships =
    guardrailsState.guardrails?.protected_relationships ?? DEFAULT_FAVORITE_TARGETS;
  const draftTargets = useMemo(
    () =>
      buildDraftTargetOptions(
        principalId,
        favoriteRelationships,
        targetState.data?.targets ?? [],
      ),
    [principalId, favoriteRelationships, targetState.data?.targets],
  );
  const activeApprovalOutbox = useMemo(
    () =>
      activeApproval
        ? (outboxState.data?.items.find(
            (item) => item.approval_queue_id === activeApproval,
          ) ?? null)
        : null,
    [activeApproval, outboxState.data?.items],
  );
  const activeApprovalTargetId = useMemo(
    () => targetIdFromLabel(activeApprovalOutbox?.target_label ?? null),
    [activeApprovalOutbox?.target_label],
  );
  const anchoredTargetId =
    activeApprovalTargetId ?? requestedTargetId ?? draftTargetId;
  const selectedDraftTarget =
    draftTargets.find((target) => target.id === anchoredTargetId) ??
    draftTargets.find((target) => target.ready) ??
    draftTargets[0] ??
    null;
  const targetPreviewState = useSparkIMessageTargetPreview(
    principalId,
    selectedDraftTarget?.approvalId ?? null,
  );
  const state = useSparkDraftReview(
    principalId,
    selectedDraftTarget?.approvalId ?? null,
  );
  const reloadTargetPreview = targetPreviewState.refetch;
  const reloadOutbox = outboxState.refetch;
  const targetReady = draftTargets.length === 0 || Boolean(selectedDraftTarget?.ready);
  const displayContext =
    state.draft?.context_preview ?? targetPreviewState.data?.context_preview ?? [];
  const previewContextCount = targetPreviewState.data?.context_preview.length ?? 0;
  const hasDraftText = Boolean(state.draftText.trim());
  const hasRecordedFeedback = state.feedbackRecorded;
  const selectedFeedbackLabel = feedbackDisplayLabels(state.selectedFeedbackLabels);
  const recordedFeedbackLabel = feedbackDisplayLabels(
    state.lastSubmittedFeedbackLabels,
  );
  const approvalQueueId =
    state.approval?.queue_id ??
    activeApprovalOutbox?.approval_queue_id ??
    activeApproval;
  const resolvedOutboxId =
    state.approval?.outbox_id ?? activeApprovalOutbox?.outbox_id ?? null;
  const resolvedOutboxStatus =
    state.approval?.outbox_status ?? activeApprovalOutbox?.status ?? null;
  const resolvedOutboxTextHash =
    state.approval?.outbox_text_hash ??
    activeApprovalOutbox?.draft_text_hash ??
    null;
  const resolvedOutboxRecorded =
    state.approval?.outbox_recorded ?? Boolean(activeApprovalOutbox);
  const canSendResolvedOutbox = state.hasSendableOutbox(resolvedOutboxId);
  const hasApproval = Boolean(approvalQueueId);
  const hasOutbox = Boolean(resolvedOutboxId);
  const hasSendResult = Boolean(state.approvedSend);
  const selectedTone = state.styleAdjustments[0] ?? "";
  const workflowSteps: CockpitStep[] = [
    {
      id: "target",
      label: "Pick target",
      detail: selectedDraftTarget?.ready
        ? `${selectedDraftTarget.label} is selected`
        : selectedDraftTarget
          ? `${selectedDraftTarget.label} needs an approved thread`
          : "Choose who this reply is for",
      status: selectedDraftTarget?.ready ? "complete" : "active",
    },
    {
      id: "thread",
      label: "Review thread",
      detail: targetPreviewState.isLoading
        ? "Loading the last 8 texts"
        : targetPreviewState.error
          ? "Thread preview could not load"
          : previewContextCount
            ? `${previewContextCount} recent texts loaded`
            : "Open a ready target first",
      status: targetPreviewState.error
        ? "error"
        : previewContextCount
          ? "complete"
          : selectedDraftTarget?.ready
            ? "active"
            : "blocked",
    },
    {
      id: "generate",
      label: "Generate",
      detail: state.draftLoading
        ? "Spark is drafting"
        : state.draft
          ? "Draft is ready to edit"
          : targetReady
            ? "Generate after checking context"
            : "Target source required",
      status: state.draft ? "complete" : targetReady ? "active" : "blocked",
    },
    {
      id: "rate",
      label: "Rate or edit",
      detail: hasRecordedFeedback
        ? "Feedback recorded"
        : selectedFeedbackLabel
          ? `${selectedFeedbackLabel} selected`
        : hasDraftText
          ? "Rate it or edit the text"
          : "Generate a draft first",
      status: hasRecordedFeedback
        ? "complete"
        : hasDraftText
          ? "active"
          : "blocked",
    },
    {
      id: "approval",
      label: "Approval",
      detail: hasApproval
        ? state.approval
          ? `Queued ${state.approval.approval_status ?? "pending"}`
          : activeApprovalOutbox
            ? "Approval handoff loaded from outbox"
            : "Approval queue linked"
        : hasDraftText
          ? "Submit approval to create outbox"
          : "Draft text required",
      status: hasApproval ? "complete" : hasDraftText ? "active" : "blocked",
    },
    {
      id: "send",
      label: "Send",
      detail: hasSendResult
        ? `Send result: ${state.approvedSend?.outbox_status ?? "done"}`
        : hasOutbox
          ? activeApprovalOutbox
            ? "Send can resume from the persisted outbox"
            : "Send only after approval passes"
          : hasApproval
            ? "Outbox not recorded"
            : "Approval required first",
      status: hasSendResult
        ? "complete"
        : state.approvedSendError
          ? "error"
          : hasOutbox
            ? "active"
            : "blocked",
    },
  ];

  function selectPrincipal(nextPrincipalId: SparkPrincipalId) {
    state.resetDraftSurface();
    setDraftTargetId(null);
    setPrincipalId(nextPrincipalId);
  }

  function selectDraftTarget(nextTargetId: string) {
    state.resetDraftSurface();
    setDraftTargetId(nextTargetId);
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className="max-w-[1500px] space-y-4"
    >
      <section className={`rounded-xl border ${border} ${panel} p-4`}>
        <div className="grid gap-4 xl:grid-cols-[minmax(210px,0.8fr)_minmax(0,1.6fr)_minmax(250px,0.8fr)] xl:items-center">
          <div className="flex items-center gap-3">
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-lg border ${border} ${panel}`}
            >
              <Sparkles className="h-5 w-5 text-emerald-400" />
            </div>
            <div>
              <h1 className={`font-serif italic text-3xl ${strong}`}>
                Spark
              </h1>
              <p
                className={`mt-1 text-[10px] font-mono uppercase tracking-widest ${muted}`}
              >
                Review console
              </p>
            </div>
          </div>

          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
              >
                Voice profile
              </span>
              {SPARK_PRINCIPALS.map((principal) => (
                <button
                  key={principal.id}
                  type="button"
                  onClick={() =>
                    selectPrincipal(principal.id as SparkPrincipalId)
                  }
                  className={`min-h-9 rounded-lg border px-3 text-sm font-bold transition ${border} ${
                    principal.id === principalId
                      ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300"
                      : ""
                  }`}
                >
                  {principal.label}
                </button>
              ))}
            </div>
          </div>

          <div
            className={`grid min-w-64 grid-cols-3 overflow-hidden rounded-lg border text-center text-[10px] font-mono uppercase ${border}`}
          >
            <div className={`px-3 py-2 ${panel}`}>draft only</div>
            <div className={`border-x px-3 py-2 ${border}`}>local</div>
            <div className={`px-3 py-2 ${panel}`}>approval</div>
          </div>
        </div>
      </section>

      <DraftTargetPicker
        targets={draftTargets}
        selectedTargetId={selectedDraftTarget?.id ?? null}
        loading={targetState.isLoading}
        onSelect={selectDraftTarget}
        onManageRelationships={() => setDetailPanel("guardrails")}
        border={border}
        panel={panel}
        muted={muted}
        okClass={okClass}
        warnClass={warnClass}
      />

      <ApprovedThreadOnboardingPanel
        principalLabel={selectedPrincipal.label}
        targets={draftTargets}
        border={border}
        panel={panel}
        muted={muted}
        okClass={okClass}
        warnClass={warnClass}
      />

      <ConversationBriefPanel
        draft={state.draft}
        preview={targetPreviewState.data ?? null}
        previewLoading={targetPreviewState.isLoading}
        previewError={targetPreviewState.error}
        selectedPrincipalLabel={selectedPrincipal.label}
        selectedTargetLabel={selectedDraftTarget?.label ?? null}
        selectedTargetReady={Boolean(selectedDraftTarget?.ready)}
        onRefreshPreview={() => {
          void reloadTargetPreview();
        }}
        border={border}
        panel={panel}
        muted={muted}
        okClass={okClass}
        warnClass={warnClass}
      />

      {activeApproval && (
        <div className={`rounded-lg border px-3 py-2 text-sm ${okClass}`}>
          Approval queue {activeApproval}
          {activeApprovalOutbox
            ? ` · ${selectedPrincipal.label} -> ${activeApprovalOutbox.target_label} · outbox ${labelize(activeApprovalOutbox.status)}`
            : " · waiting for outbox metadata"}
        </div>
      )}

      <ReplyCockpitStepper
        steps={workflowSteps}
        border={border}
        panel={panel}
        muted={muted}
        okClass={okClass}
        warnClass={warnClass}
        errorClass={errorClass}
      />

      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)] 2xl:grid-cols-[320px_minmax(0,1fr)_340px]">
        <section className={`rounded-xl border ${border} ${panel} p-4`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <MessageSquareText className="h-4 w-4 text-emerald-400" />
              <h2
                className={`text-xs font-mono uppercase tracking-widest ${muted}`}
              >
                Request
              </h2>
            </div>
            <StatusChip label="Thread preview" className={warnClass} />
          </div>
          <div className="mt-4 space-y-3">
            <label className="block">
              <span
                className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
              >
                Reply goal
              </span>
              <textarea
                value={state.replyGoal}
                onChange={(event) => state.setReplyGoal(event.target.value)}
                rows={4}
                maxLength={1000}
                className={`mt-2 w-full resize-y rounded-lg border p-3 text-sm outline-none transition focus:border-emerald-400 ${input}`}
              />
            </label>
            <label className="block">
              <span
                className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
              >
                Context messages
              </span>
              <div className="mt-2 flex items-center gap-3">
                <input
                  type="range"
                  min={1}
                  max={50}
                  value={state.maxContextMessages}
                  onChange={(event) =>
                    state.setMaxContextMessages(Number(event.target.value))
                  }
                  className="min-w-0 flex-1"
                />
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={state.maxContextMessages}
                  onChange={(event) =>
                    state.setMaxContextMessages(Number(event.target.value))
                  }
                  className={`h-11 w-20 rounded-lg border px-3 text-sm ${input}`}
                />
              </div>
              <p className={`mt-2 text-xs ${muted}`}>
                Default to 8. Use 12 for messy logistics, 15 only when the thread spans multiple beats.
              </p>
            </label>
            <ToneSelect
              border={border}
              input={input}
              muted={muted}
              value={selectedTone}
              onChange={(value) =>
                state.setStyleAdjustments(value ? [value] : [])
              }
            />
            {!targetReady && selectedDraftTarget && (
              <div className={`rounded-lg border px-3 py-2 text-sm ${warnClass}`}>
                {selectedDraftTarget.label} is in the core-family roster, but no
                approved iMessage thread is connected yet.
              </div>
            )}
            <div className="grid gap-2 sm:grid-cols-3 xl:grid-cols-1">
              <button
                type="button"
                onClick={state.generateDraft}
                disabled={state.draftLoading || !targetReady}
                className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-emerald-600 px-4 text-sm font-bold text-white transition hover:bg-emerald-500 disabled:opacity-45"
              >
                {state.draftLoading ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                {selectedDraftTarget
                  ? `Generate for ${selectedDraftTarget.label}`
                  : "Generate draft"}
              </button>
              <button
                type="button"
                onClick={state.submitForApproval}
                disabled={!state.canSubmitForApproval}
                className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-4 text-sm font-bold transition ${border} ${
                  state.canSubmitForApproval
                    ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300"
                    : "opacity-45"
                }`}
              >
                {state.approvalLoading ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <ShieldCheck className="h-4 w-4" />
                )}
                Submit approval
              </button>
              <button
                type="button"
                onClick={state.generateComparisons}
                disabled={state.comparisonLoading || !targetReady}
                className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-4 text-sm font-bold transition ${border}`}
              >
                {state.comparisonLoading ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <GitCompareArrows className="h-4 w-4" />
                )}
                Compare
              </button>
            </div>
            <RecentThreadStrip
              context={displayContext}
              loading={targetPreviewState.isLoading}
              error={targetPreviewState.error}
              border={border}
              muted={muted}
              okClass={okClass}
              warnClass={warnClass}
            />
            <button
              type="button"
              onClick={() => setDetailPanel("target-memory")}
              disabled={!selectedDraftTarget?.ready}
              className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border px-4 text-sm font-bold transition ${border} ${
                selectedDraftTarget?.ready
                  ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300"
                  : "opacity-45"
              }`}
            >
              <StickyNote className="h-4 w-4" />
              Mark for memory update
            </button>
            {state.draftError && (
              <ErrorLine
                text="Draft route unavailable"
                className={errorClass}
              />
            )}
            {state.comparisonError && (
              <ErrorLine
                text="Comparison route unavailable"
                className={errorClass}
              />
            )}
            {state.approvalError && (
              <ErrorLine
                text="Approval handoff failed"
                className={errorClass}
              />
            )}
            {state.feedbackError && (
              <ErrorLine
                text="Feedback capture failed"
                className={errorClass}
              />
            )}
          </div>
        </section>

        <section className={`rounded-xl border ${border} ${panel} p-4`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Copy className="h-4 w-4 text-emerald-400" />
              <h2
                className={`text-xs font-mono uppercase tracking-widest ${muted}`}
              >
                Draft
              </h2>
            </div>
            <div className="flex flex-wrap gap-2">
              <StatusChip label="no send" className={warnClass} />
              <StatusChip label="runtime only" className={okClass} />
              <StatusChip label="human gate" className={okClass} />
            </div>
          </div>

          <div className="mt-4 space-y-4">
            <label className="block">
              <span
                className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
              >
                Draft text
              </span>
              <textarea
                value={state.draftText}
                onChange={(event) => state.setDraftText(event.target.value)}
                rows={16}
                maxLength={4000}
                className={`mt-2 min-h-[390px] w-full resize-y rounded-lg border p-3 text-sm outline-none transition focus:border-emerald-400 ${input}`}
              />
            </label>
            <div className="flex flex-wrap gap-2">
              {FEEDBACK_BUTTONS.map((feedback) => (
                <button
                  key={feedback.value}
                  type="button"
                  onClick={() => state.toggleFeedbackLabel(feedback.value)}
                  disabled={
                    !state.draft ||
                    state.feedbackLoading ||
                    (!state.selectedFeedbackLabels.includes(feedback.value) &&
                      !state.canSelectMoreFeedback)
                  }
                  className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-xs font-bold transition ${
                    feedback.tone === "ok" ? okClass : warnClass
                  } ${
                    state.selectedFeedbackLabels.includes(feedback.value)
                      ? "ring-2 ring-emerald-400/60"
                      : ""
                  } ${!state.draft ? "opacity-45" : ""}`}
                >
                  {feedback.tone === "ok" ? (
                    <ThumbsUp className="h-4 w-4" />
                  ) : (
                    <ThumbsDown className="h-4 w-4" />
                  )}
                  {feedback.label}
                </button>
              ))}
            </div>
            <FeedbackSelectionHint
              muted={muted}
              selectedCount={state.selectedFeedbackLabels.length}
            />
            {hasRecordedFeedback && (
              <div className={`rounded-lg border px-3 py-2 text-sm ${okClass}`}>
                Feedback captured
                {recordedFeedbackLabel ? `, ${recordedFeedbackLabel}` : ""}
              </div>
            )}
            <div className={`rounded-lg border p-3 ${border}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div
                    className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
                  >
                    Feedback retry
                  </div>
                  <p className={`mt-1 text-xs ${muted}`}>
                    {selectedFeedbackLabel
                      ? `${selectedFeedbackLabel} will shape the next draft`
                      : "Rate the draft, then regenerate with that feedback"}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={state.regenerateWithFeedback}
                  disabled={!state.canRegenerateWithFeedback}
                  className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-xs font-bold transition ${border} ${
                    state.canRegenerateWithFeedback
                      ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300"
                      : "opacity-45"
                  }`}
                >
                  {state.draftLoading ? (
                    <LoaderCircle className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCw className="h-4 w-4" />
                  )}
                  Try again with feedback
                </button>
              </div>
            </div>
          </div>
        </section>

        <aside
          className={`rounded-xl border ${border} ${panel} p-4 xl:col-span-2 2xl:col-span-1`}
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <CircleCheck className="h-4 w-4 text-emerald-400" />
              <h2
                className={`text-xs font-mono uppercase tracking-widest ${muted}`}
              >
                Decision rail
              </h2>
            </div>
            <StatusChip label={selectedPrincipal.label} className={okClass} />
          </div>

          <div className="mt-4 space-y-4">
            {state.draft ? (
              <>
                <DraftQualityPanel
                  draft={state.draft}
                  border={border}
                  muted={muted}
                  okClass={okClass}
                  warnClass={warnClass}
                  errorClass={errorClass}
                />
                <SourceReadinessPanel
                  draft={state.draft}
                  border={border}
                  muted={muted}
                  okClass={okClass}
                  warnClass={warnClass}
                />
                <DraftMetadata draft={state.draft} muted={muted} />
                <div className="flex flex-wrap gap-2">
                  {state.draft.warnings.map((warning) => (
                    <StatusChip
                      key={warning}
                      label={warning.replace(/_/g, " ")}
                      className={warnClass}
                    />
                  ))}
                </div>
              </>
            ) : (
              <div
                className={`flex min-h-40 items-center justify-center rounded-lg border ${border}`}
              >
                <span className={`text-sm ${muted}`}>No draft loaded</span>
              </div>
            )}
            {approvalQueueId && (
              <div className={`space-y-2 rounded-lg border p-3 ${border}`}>
                <div className="flex items-center gap-2 text-sm">
                  <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                  <span className="font-semibold">
                    {state.approval?.approval_status ??
                      (activeApprovalOutbox ? "handoff_loaded" : "pending")}
                  </span>
                </div>
                <MetricRow
                  label="Queue ID"
                  value={approvalQueueId}
                  muted={muted}
                />
                <MetricRow
                  label="Outbox"
                  value={resolvedOutboxRecorded ? resolvedOutboxStatus ?? "recorded" : "not recorded"}
                  muted={muted}
                />
                {resolvedOutboxId && (
                  <MetricRow
                    label="Outbox ID"
                    value={resolvedOutboxId}
                    muted={muted}
                  />
                )}
                {resolvedOutboxTextHash && (
                  <MetricRow
                    label="Draft hash"
                    value={shortHash(resolvedOutboxTextHash)}
                    muted={muted}
                  />
                )}
                {resolvedOutboxId && (
                  <button
                    type="button"
                    onClick={() => state.sendApprovedOutbox(resolvedOutboxId)}
                    disabled={!canSendResolvedOutbox}
                    className={`inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold transition ${border} ${
                      canSendResolvedOutbox
                        ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300"
                        : "opacity-45"
                    }`}
                  >
                    {state.approvedSendLoading ? (
                      <LoaderCircle className="h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="h-4 w-4" />
                    )}
                    Send approved
                  </button>
                )}
                {activeApproval && !activeApprovalOutbox && !outboxState.isLoading && (
                  <div className={`rounded-lg border px-3 py-2 text-sm ${warnClass}`}>
                    Approval handoff exists, but no persisted outbox metadata was found yet.
                  </div>
                )}
                {state.approvedSend && (
                  <MetricRow
                    label="Send"
                    value={state.approvedSend.outbox_status}
                    muted={muted}
                  />
                )}
                {state.approvedSendError && (
                  <div className={`rounded-lg border px-3 py-2 text-sm ${warnClass}`}>
                    Send blocked until the outbox item is approved and persisted
                  </div>
                )}
              </div>
            )}
            {approvalQueueId && (
              <div className={`rounded-lg border px-3 py-2 text-sm ${okClass}`}>
                Approval queued {approvalQueueId}
              </div>
            )}
          </div>
        </aside>
      </div>

      <OutboxCockpitPanel
        items={outboxState.data?.items ?? []}
        loading={outboxState.isLoading}
        error={outboxState.error}
        onRefresh={() => {
          void reloadOutbox();
        }}
        border={border}
        panel={panel}
        muted={muted}
        okClass={okClass}
        warnClass={warnClass}
        errorClass={errorClass}
      />

      {state.comparisonDrafts.length > 0 && (
        <section className={`rounded-xl border ${border} ${panel} p-5`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <GitCompareArrows className="h-4 w-4 text-emerald-400" />
              <h2
                className={`text-xs font-mono uppercase tracking-widest ${muted}`}
              >
                Side-by-side
              </h2>
            </div>
            <StatusChip label={selectedPrincipal.label} className={okClass} />
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-3">
            {state.comparisonDrafts.map((comparison) => (
              <div
                key={comparison.id}
                className={`rounded-lg border p-3 ${border}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
                  >
                    {comparison.label}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      state.setDraftText(comparison.draft.draft_text)
                    }
                    className={`min-h-9 rounded-lg border px-3 text-xs font-bold ${border}`}
                  >
                    Use
                  </button>
                </div>
                <p className="mt-3 text-sm leading-relaxed">
                  {comparison.draft.draft_text}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className={`rounded-xl border ${border} ${panel} p-4`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ListChecks className="h-4 w-4 text-emerald-400" />
            <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>
              Review details
            </h2>
          </div>
          <StatusChip label="click to inspect" className={warnClass} />
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <DetailOverviewCard
            title="Thread context"
            detail="See the exact last messages Spark used for this draft."
            metric={`${displayContext.length} shown`}
            icon={<MessagesSquare className="h-4 w-4 text-emerald-400" />}
            onOpen={() => setDetailPanel("thread")}
            border={border}
            muted={muted}
            okClass={okClass}
          />
          <DetailOverviewCard
            title="Draft memory"
            detail="Inspect reviewed voice memory and selected-target memory used silently in the prompt."
            metric={`${state.draft?.personality_memory_preview.length ?? 0} voice / ${state.draft?.target_memory_preview.length ?? 0} target`}
            icon={<Brain className="h-4 w-4 text-emerald-400" />}
            onOpen={() => setDetailPanel("memory-debug")}
            border={border}
            muted={muted}
            okClass={okClass}
          />
          <DetailOverviewCard
            title="Target memory"
            detail="Review open loops, preferences, and profile facts for the selected recipient."
            metric={selectedDraftTarget?.label ?? "pick target"}
            icon={<StickyNote className="h-4 w-4 text-emerald-400" />}
            onOpen={() => setDetailPanel("target-memory")}
            border={border}
            muted={muted}
            okClass={okClass}
          />
          <DetailOverviewCard
            title="Relationships"
            detail="Review the core-family target roster, protected topics, and no-send posture."
            metric={`${favoriteRelationships.length} core family`}
            icon={<Shield className="h-4 w-4 text-emerald-400" />}
            onOpen={() => setDetailPanel("guardrails")}
            border={border}
            muted={muted}
            okClass={okClass}
          />
          <DetailOverviewCard
            title="Memory review"
            detail="Open Buddy proposals, scorecards, approved memory, and archive controls."
            metric={selectedPrincipal.label}
            icon={<Lightbulb className="h-4 w-4 text-emerald-400" />}
            onOpen={() => setDetailPanel("memory-review")}
            border={border}
            muted={muted}
            okClass={okClass}
          />
        </div>
      </section>

      <AnimatePresence>
        {detailPanel === "thread" && (
          <DetailDialog
            title="Thread context"
            onClose={() => setDetailPanel(null)}
            border={border}
            panel={panel}
            muted={muted}
          >
            <ThreadContextPanel
              draft={state.draft}
              preview={targetPreviewState.data ?? null}
              previewLoading={targetPreviewState.isLoading}
              previewError={targetPreviewState.error}
              border={border}
              panel={panel}
              muted={muted}
              okClass={okClass}
              warnClass={warnClass}
            />
          </DetailDialog>
        )}

        {detailPanel === "memory-debug" && (
          <DetailDialog
            title="Draft memory"
            onClose={() => setDetailPanel(null)}
            border={border}
            panel={panel}
            muted={muted}
          >
            <DraftMemoryDebugPanel
              draft={state.draft}
              approval={state.approval}
              border={border}
              panel={panel}
              muted={muted}
              okClass={okClass}
              warnClass={warnClass}
            />
          </DetailDialog>
        )}

        {detailPanel === "target-memory" && (
          <DetailDialog
            title="Target memory"
            onClose={() => setDetailPanel(null)}
            border={border}
            panel={panel}
            muted={muted}
          >
            <SparkTargetMemoryPanel
              border={border}
              panel={panel}
              input={input}
              muted={muted}
              okClass={okClass}
              warnClass={warnClass}
              errorClass={errorClass}
              principalId={principalId}
              approvalId={selectedDraftTarget?.approvalId ?? null}
              targetLabel={selectedDraftTarget?.label ?? null}
              preview={targetPreviewState.data ?? null}
            />
          </DetailDialog>
        )}

        {detailPanel === "guardrails" && (
          <DetailDialog
            title="Relationships and guardrails"
            onClose={() => setDetailPanel(null)}
            border={border}
            panel={panel}
            muted={muted}
          >
            <SparkGuardrailsPanel
              border={border}
              panel={panel}
              input={input}
              muted={muted}
              okClass={okClass}
              warnClass={warnClass}
              errorClass={errorClass}
            />
          </DetailDialog>
        )}

        {detailPanel === "memory-review" && (
          <DetailDialog
            title="Memory review"
            onClose={() => setDetailPanel(null)}
            border={border}
            panel={panel}
            muted={muted}
          >
            <SparkMemoryReviewPanel
              border={border}
              panel={panel}
              input={input}
              muted={muted}
              okClass={okClass}
              warnClass={warnClass}
              errorClass={errorClass}
              principalId={principalId}
              principalLabel={selectedPrincipal.label}
            />
          </DetailDialog>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
