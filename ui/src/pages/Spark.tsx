import { motion } from "framer-motion";
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
  Shield,
  ShieldCheck,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  UserRound,
  UsersRound,
  X,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { SparkGuardrailsPanel } from "../components/spark/SparkGuardrailsPanel";
import { SparkMemoryReviewPanel } from "../components/spark/SparkMemoryReviewPanel";
import {
  useSparkDraftReview,
  useSparkIMessageDraftTargets,
} from "../hooks/useSparkDraftReview";
import { useSparkGuardrails } from "../hooks/useSparkGuardrails";
import { useAppStore } from "../store";
import type {
  SparkDraftFeedbackLabel,
  SparkIMessageDraftContextMessage,
  SparkIMessageDraftResponse,
  SparkIMessageDraftTarget,
  SparkProtectedRelationship,
} from "../types/spark";

const SPARK_PRINCIPALS = [
  { id: "ken", label: "Ken" },
  { id: "sweta", label: "Sweta" },
  { id: "ryleigh", label: "Ryleigh" },
  { id: "sloane", label: "Sloane" },
  { id: "meagan", label: "Meagan" },
  { id: "mother", label: "Mother" },
];

const FEEDBACK_BUTTONS: Array<{
  label: string;
  value: SparkDraftFeedbackLabel;
  tone: "ok" | "warn";
}> = [
  { label: "Sounds like me", value: "sounds_like_me", tone: "ok" },
  { label: "Too robotic", value: "too_robotic", tone: "warn" },
  { label: "Too formal", value: "too_formal", tone: "warn" },
  { label: "Too much policy", value: "too_much_policy", tone: "warn" },
];

const DEFAULT_FAVORITE_TARGETS: SparkProtectedRelationship[] = [
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
    sensitivity: "custody",
    default_mode: "draft_only",
    approval_required: true,
  },
  {
    id: "mother",
    label: "Mother",
    relationship: "parent",
    sensitivity: "family",
    default_mode: "draft_only",
    approval_required: true,
  },
];

type DetailPanel = "thread" | "memory-debug" | "guardrails" | "memory-review";

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

function buildDraftTargetOptions(
  relationships: SparkProtectedRelationship[],
  targets: SparkIMessageDraftTarget[],
): DraftTargetOption[] {
  const targetByLabel = new Map(
    targets.map((target) => [normalizedKey(target.label), target]),
  );
  const usedApprovalIds = new Set<string>();
  const options: DraftTargetOption[] = relationships.map((relationship) => {
    const target =
      targetByLabel.get(normalizedKey(relationship.label)) ??
      targets.find((item) => normalizedKey(item.label) === normalizedKey(relationship.id));
    if (target) {
      usedApprovalIds.add(target.approval_id);
    }
    return {
      id: relationship.id,
      label: relationship.label,
      relationship: relationship.relationship,
      sensitivity: relationship.sensitivity,
      approvalId: target?.approval_id ?? null,
      channel: target?.channel ?? "iMessage",
      favorite: true,
      ready: Boolean(target?.approval_id),
    };
  });

  for (const target of targets) {
    if (usedApprovalIds.has(target.approval_id)) continue;
    options.push({
      id: `approval-${target.approval_id}`,
      label: target.label,
      relationship: target.relationship_marked ? "relationship" : "contact",
      sensitivity: target.legal_marked
        ? "custody/legal"
        : target.relationship_marked
          ? "relationship"
          : "standard",
      approvalId: target.approval_id,
      channel: target.channel,
      favorite: false,
      ready: true,
    });
  }
  return options;
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
  selectedPrincipalLabel,
  selectedTargetLabel,
  selectedTargetReady,
  border,
  panel,
  muted,
  okClass,
  warnClass,
}: {
  draft: SparkIMessageDraftResponse | null;
  selectedPrincipalLabel: string;
  selectedTargetLabel: string | null;
  selectedTargetReady: boolean;
  border: string;
  panel: string;
  muted: string;
  okClass: string;
  warnClass: string;
}) {
  const summary = draft?.conversation_summary;

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
            {summary?.last_message_preview ??
              "Generate a draft to see the last message Spark is replying to."}
          </p>
        </div>
      </div>
    </section>
  );
}

function DraftTargetPicker({
  targets,
  selectedTargetId,
  loading,
  onSelect,
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
        <StatusChip
          label={loading ? "loading approved threads" : "favorites"}
          className={loading ? warnClass : okClass}
        />
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-5">
        {targets.map((target) => {
          const selected = target.id === selectedTargetId;
          return (
            <button
              key={target.id}
              type="button"
              onClick={() => onSelect(target.id)}
              disabled={!target.ready}
              className={`min-h-24 rounded-lg border p-3 text-left transition ${border} ${
                selected
                  ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-200"
                  : ""
              } ${target.ready ? "hover:border-emerald-400" : "opacity-55"}`}
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
                  {target.ready ? "ready" : "needs source"}
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

function RecentThreadStrip({
  context,
  border,
  muted,
  okClass,
  warnClass,
}: {
  context: SparkIMessageDraftContextMessage[];
  border: string;
  muted: string;
  okClass: string;
  warnClass: string;
}) {
  const recent = context.slice(0, 5);
  return (
    <div className={`rounded-lg border p-3 ${border}`}>
      <div className="flex items-center justify-between gap-3">
        <span className={`text-[10px] font-mono uppercase ${muted}`}>
          Recent thread
        </span>
        <span className={`text-[10px] font-mono uppercase ${muted}`}>
          newest first
        </span>
      </div>
      {recent.length ? (
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
          Generate a draft to see the last 5 messages here.
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
  border,
  panel,
  muted,
  okClass,
  warnClass,
}: {
  draft: SparkIMessageDraftResponse | null;
  border: string;
  panel: string;
  muted: string;
  okClass: string;
  warnClass: string;
}) {
  const context = draft?.context_preview ?? [];

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

      {context.length ? (
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
            Generate a draft to view the last thread messages
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
  const memory = draft?.personality_memory_preview ?? [];
  const phrases = approval?.candidate_key_phrases ?? [];

  return (
    <section className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-emerald-400" />
          <h2
            className={`text-xs font-mono uppercase tracking-widest ${muted}`}
          >
            Draft memory debug
          </h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusChip label={`${memory.length} used`} className={okClass} />
          <StatusChip label="silent in draft" className={warnClass} />
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="space-y-3">
          <span
            className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
          >
            Reviewed memory used
          </span>
          {memory.length ? (
            memory.map((item, index) => (
              <div
                key={`${item.kind}-${item.evidence_ref_hash ?? index}`}
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
              No reviewed memory attached to this draft yet
            </div>
          )}
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
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-sm">
      <section
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`max-h-[90vh] w-full max-w-6xl overflow-y-auto rounded-xl border ${border} ${panel} p-4 shadow-xl`}
      >
        <div className="sticky top-0 z-10 mb-4 flex items-center justify-between gap-3 border-b border-current/10 pb-3 backdrop-blur">
          <div>
            <h2 className="text-lg font-bold">{title}</h2>
            <p className={`text-xs ${muted}`}>Review detail, no send action.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-bold ${border}`}
          >
            <X className="h-4 w-4" />
            Close
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

export default function Spark() {
  const { theme } = useAppStore();
  const [searchParams] = useSearchParams();
  const activeApproval = searchParams.get("approval");
  const [principalId, setPrincipalId] = useState("ken");
  const [draftTargetId, setDraftTargetId] = useState<string | null>(null);
  const [detailPanel, setDetailPanel] = useState<DetailPanel | null>(null);
  const guardrailsState = useSparkGuardrails();
  const targetState = useSparkIMessageDraftTargets(principalId);
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
        favoriteRelationships,
        targetState.data?.targets ?? [],
      ),
    [favoriteRelationships, targetState.data?.targets],
  );
  const selectedDraftTarget =
    draftTargets.find((target) => target.id === draftTargetId) ??
    draftTargets.find((target) => target.ready) ??
    draftTargets[0] ??
    null;
  const state = useSparkDraftReview(
    principalId,
    selectedDraftTarget?.approvalId ?? null,
  );
  const targetReady = draftTargets.length === 0 || Boolean(selectedDraftTarget?.ready);

  function selectPrincipal(nextPrincipalId: string) {
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
                  onClick={() => selectPrincipal(principal.id)}
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
        border={border}
        panel={panel}
        muted={muted}
        okClass={okClass}
        warnClass={warnClass}
      />

      <ConversationBriefPanel
        draft={state.draft}
        selectedPrincipalLabel={selectedPrincipal.label}
        selectedTargetLabel={selectedDraftTarget?.label ?? null}
        selectedTargetReady={Boolean(selectedDraftTarget?.ready)}
        border={border}
        panel={panel}
        muted={muted}
        okClass={okClass}
        warnClass={warnClass}
      />

      {activeApproval && (
        <div className={`rounded-lg border px-3 py-2 text-sm ${okClass}`}>
          Approval queue {activeApproval}
        </div>
      )}

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
            </label>
            {!targetReady && selectedDraftTarget && (
              <div className={`rounded-lg border px-3 py-2 text-sm ${warnClass}`}>
                {selectedDraftTarget.label} is in favorites, but no approved
                iMessage source is connected yet.
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
              context={state.draft?.context_preview ?? []}
              border={border}
              muted={muted}
              okClass={okClass}
              warnClass={warnClass}
            />
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
                  onClick={() => state.recordFeedback(feedback.value)}
                  disabled={!state.draft || state.feedbackLoading}
                  className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-xs font-bold transition ${
                    feedback.tone === "ok" ? okClass : warnClass
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
            {state.feedback?.feedback_recorded && (
              <div className={`rounded-lg border px-3 py-2 text-sm ${okClass}`}>
                Feedback recorded
              </div>
            )}
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
            {state.approval && (
              <div className={`space-y-2 rounded-lg border p-3 ${border}`}>
                <div className="flex items-center gap-2 text-sm">
                  <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                  <span className="font-semibold">
                    {state.approval.approval_status}
                  </span>
                </div>
                <MetricRow
                  label="Queue ID"
                  value={state.approval.queue_id}
                  muted={muted}
                />
              </div>
            )}
            {state.approval && (
              <div className={`rounded-lg border px-3 py-2 text-sm ${okClass}`}>
                Approval queued {state.approval.queue_id}
              </div>
            )}
          </div>
        </aside>
      </div>

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
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <DetailOverviewCard
            title="Thread context"
            detail="See the exact last messages Spark used for this draft."
            metric={`${state.draft?.context_preview.length ?? 0} shown`}
            icon={<MessagesSquare className="h-4 w-4 text-emerald-400" />}
            onOpen={() => setDetailPanel("thread")}
            border={border}
            muted={muted}
            okClass={okClass}
          />
          <DetailOverviewCard
            title="Draft memory"
            detail="Inspect reviewed personality memory used silently in the prompt."
            metric={`${state.draft?.personality_memory_preview.length ?? 0} used`}
            icon={<Brain className="h-4 w-4 text-emerald-400" />}
            onOpen={() => setDetailPanel("memory-debug")}
            border={border}
            muted={muted}
            okClass={okClass}
          />
          <DetailOverviewCard
            title="Guardrails"
            detail="Review protected topics, favorite relationships, and no-send posture."
            metric={`${favoriteRelationships.length} relationships`}
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

      {detailPanel === "guardrails" && (
        <DetailDialog
          title="Memory and guardrails"
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
    </motion.div>
  );
}
