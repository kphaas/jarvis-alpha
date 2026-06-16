import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Archive,
  BookMarked,
  CheckCircle2,
  Clock3,
  LoaderCircle,
  Plus,
  RefreshCw,
  StickyNote,
  XCircle,
} from "lucide-react";
import { useSparkTargetMemory } from "../../hooks/useSparkTargetMemory";
import type {
  SparkIMessageTargetPreviewResponse,
  SparkTargetMemoryKind,
  SparkTargetMemoryProposal,
} from "../../types/spark";

interface StyleProps {
  border: string;
  panel: string;
  input: string;
  muted: string;
  okClass: string;
  warnClass: string;
  errorClass: string;
  principalId: string;
  approvalId: string | null;
  targetLabel: string | null;
  preview: SparkIMessageTargetPreviewResponse | null;
}

const TARGET_MEMORY_KINDS: Array<{
  value: SparkTargetMemoryKind;
  label: string;
  hint: string;
}> = [
  {
    value: "open_loop",
    label: "Open loop",
    hint: "Unresolved follow-up or next step with this person.",
  },
  {
    value: "preference",
    label: "Preference",
    hint: "How they like updates, planning, or follow-through.",
  },
  {
    value: "profile_fact",
    label: "Profile fact",
    hint: "Stable fact about this person that improves replies.",
  },
];

function shortHash(value: string | null | undefined) {
  if (!value) return "not set";
  return `${value.slice(0, 10)}...${value.slice(-8)}`;
}

function labelize(value: string) {
  return value.replace(/_/g, " ");
}

export function SparkTargetMemoryPanel({
  border,
  panel,
  input,
  muted,
  okClass,
  warnClass,
  errorClass,
  principalId,
  approvalId,
  targetLabel,
  preview,
}: StyleProps) {
  const state = useSparkTargetMemory(principalId, approvalId);
  const [memoryNote, setMemoryNote] = useState("");
  const [memoryKind, setMemoryKind] = useState<SparkTargetMemoryKind>("open_loop");
  const [edits, setEdits] = useState<Record<string, string>>({});

  const active = state.memory?.active ?? [];
  const proposedMemory = state.proposeMemoryResult?.proposal ?? null;
  const proposals = useMemo(
    () => {
      const backendProposals = state.memory?.proposals ?? [];
      return proposedMemory
        ? [
            proposedMemory,
            ...backendProposals.filter(
              (proposal) => proposal.proposal_id !== proposedMemory.proposal_id,
            ),
          ]
        : backendProposals;
    },
    [state.memory?.proposals, proposedMemory],
  );
  const scorecard = state.memory?.scorecard ?? null;

  function editedContent(proposal: SparkTargetMemoryProposal) {
    return edits[proposal.proposal_id] ?? proposal.content;
  }

  function approve(proposal: SparkTargetMemoryProposal) {
    const content = editedContent(proposal).trim();
    if (!content || state.approveMemoryLoading) return;
    state.approveMemory({
      approved: true,
      proposal_id: proposal.proposal_id,
      principal_id: proposal.principal_id,
      target_ref_hash: proposal.target_ref_hash,
      target_label: proposal.target_label,
      kind: proposal.kind,
      content,
      source: proposal.source,
      evidence_ref_hash: proposal.evidence_ref_hash ?? null,
      importance_score: proposal.confidence,
    });
  }

  function reject(proposal: SparkTargetMemoryProposal) {
    if (state.rejectMemoryLoading) return;
    state.rejectMemory({
      principal_id: proposal.principal_id,
      target_ref_hash: proposal.target_ref_hash,
      proposal_id: proposal.proposal_id,
    });
  }

  function archive(memoryId: string) {
    if (state.archiveMemoryLoading) return;
    state.archiveMemory({
      principal_id: principalId,
      memory_id: memoryId,
    });
  }

  function proposeFromNote() {
    const note = memoryNote.trim();
    const chatGuidHash = preview?.chat_guid_hash ?? "";
    if (!note || !approvalId || !chatGuidHash || state.proposeMemoryLoading) return;
    state.proposeMemory({
      principal_id: principalId,
      approval_id: approvalId,
      kind: memoryKind,
      note,
      chat_guid_hash: chatGuidHash,
    });
  }

  if (!approvalId) {
    return (
      <section className={`rounded-xl border ${border} ${panel} p-5`}>
        <div className={`rounded-lg border px-3 py-2 text-sm ${warnClass}`}>
          Pick a ready draft target first.
        </div>
      </section>
    );
  }

  if (state.memoryLoading) {
    return (
      <section className={`rounded-xl border ${border} ${panel} p-5`}>
        <div className="flex min-h-32 items-center justify-center gap-2 text-sm opacity-60">
          <LoaderCircle className="h-4 w-4 animate-spin" />
          Loading target memory
        </div>
      </section>
    );
  }

  if (state.memoryError || !state.memory) {
    return (
      <section className={`rounded-xl border ${border} ${panel} p-5`}>
        <div
          className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${errorClass}`}
        >
          <AlertTriangle className="h-4 w-4 shrink-0" />
          Target memory review unavailable
        </div>
      </section>
    );
  }

  return (
    <section className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <BookMarked className="h-4 w-4 text-emerald-400" />
          <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>
            Target memory
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${okClass}`}
          >
            {targetLabel ?? state.memory.target_label}
          </span>
          <span
            className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${okClass}`}
          >
            {active.length} active
          </span>
          <span
            className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${warnClass}`}
          >
            {proposals.length} proposals
          </span>
          <button
            type="button"
            onClick={() => void state.refreshMemory()}
            className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-bold transition ${border}`}
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
        </div>
      </div>

      {scorecard && (
        <div className={`mt-4 rounded-lg border p-3 ${border}`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className={`text-[10px] font-mono uppercase ${muted}`}>
              Selected-target scorecard
            </span>
            <span
              className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${
                scorecard.readiness === "strong" ? okClass : warnClass
              }`}
            >
              {labelize(scorecard.readiness)}
            </span>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-4">
            <MetricBox label="Open loops" value={scorecard.open_loop_count} border={border} muted={muted} />
            <MetricBox label="Preferences" value={scorecard.preference_count} border={border} muted={muted} />
            <MetricBox label="Profile facts" value={scorecard.profile_fact_count} border={border} muted={muted} />
            <MetricBox label="Proposals" value={scorecard.proposal_count} border={border} muted={muted} />
          </div>
        </div>
      )}

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(320px,0.95fr)_minmax(0,1.05fr)]">
        <div className="space-y-4">
          <div className={`rounded-lg border p-3 ${border}`}>
            <div className="flex items-center gap-2">
              <Clock3 className="h-4 w-4 text-emerald-400" />
              <span className={`text-[10px] font-mono uppercase ${muted}`}>
                Evidence hashes only
              </span>
            </div>
            <div className="mt-3 space-y-1">
              <HashRow label="Approval" value={shortHash(preview?.approval_ref_hash)} muted={muted} />
              <HashRow label="Source" value={shortHash(preview?.source_reference_hash)} muted={muted} />
              <HashRow label="Thread" value={shortHash(preview?.chat_guid_hash)} muted={muted} />
              <HashRow label="Preview texts" value={String(preview?.context_preview.length ?? 0)} muted={muted} />
            </div>
          </div>

          <div className={`rounded-lg border p-3 ${border}`}>
            <div className="flex items-center gap-2">
              <StickyNote className="h-4 w-4 text-emerald-400" />
              <span className={`text-[10px] font-mono uppercase ${muted}`}>
                Mark for memory update
              </span>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              {TARGET_MEMORY_KINDS.map((item) => {
                const selected = item.value === memoryKind;
                return (
                  <button
                    key={item.value}
                    type="button"
                    onClick={() => setMemoryKind(item.value)}
                    className={`min-h-14 rounded-lg border px-3 py-2 text-left text-sm font-semibold transition ${border} ${
                      selected
                        ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300"
                        : ""
                    }`}
                  >
                    <div>{item.label}</div>
                    <div className={`mt-1 text-xs font-normal ${muted}`}>
                      {item.hint}
                    </div>
                  </button>
                );
              })}
            </div>
            <textarea
              value={memoryNote}
              onChange={(event) => setMemoryNote(event.target.value)}
              rows={4}
              maxLength={800}
              placeholder="Example: Open loop: send camp waiver tonight."
              className={`mt-3 w-full resize-y rounded-lg border p-3 text-sm outline-none transition focus:border-emerald-400 ${input}`}
            />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <span className={`text-xs ${muted}`}>
                Stored note plus hashes only. No message bodies saved.
              </span>
              <button
                type="button"
                onClick={proposeFromNote}
                disabled={!memoryNote.trim() || !preview?.chat_guid_hash || state.proposeMemoryLoading}
                className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-bold transition ${border} ${
                  memoryNote.trim()
                    ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300"
                    : "opacity-45"
                }`}
              >
                {state.proposeMemoryLoading ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="h-4 w-4" />
                )}
                Mark for memory update
              </button>
            </div>
            {state.proposeMemoryResult?.status === "not_proposed" && (
              <div
                className={`mt-3 flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${warnClass}`}
              >
                <AlertTriangle className="h-4 w-4 shrink-0" />
                Rewrite the note without message-body copy or sensitive tokens.
              </div>
            )}
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-400" />
              <span className={`text-[10px] font-mono uppercase ${muted}`}>
                Pending proposals
              </span>
            </div>
            <div className="mt-3 space-y-3">
              {proposals.length ? (
                proposals.map((proposal) => (
                  <div
                    key={proposal.proposal_id}
                    className={`rounded-lg border p-3 ${border}`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${warnClass}`}
                      >
                        {labelize(proposal.kind)}
                      </span>
                      <span className={`text-[10px] font-mono uppercase ${muted}`}>
                        {proposal.reason}
                      </span>
                    </div>
                    <textarea
                      value={editedContent(proposal)}
                      onChange={(event) =>
                        setEdits((current) => ({
                          ...current,
                          [proposal.proposal_id]: event.target.value,
                        }))
                      }
                      rows={3}
                      className={`mt-3 w-full resize-y rounded-lg border p-3 text-sm outline-none transition focus:border-emerald-400 ${input}`}
                    />
                    <div className={`mt-3 rounded-md border px-3 py-2 text-xs ${border}`}>
                      <div className={`font-mono ${muted}`}>
                        approval {shortHash(proposal.approval_ref_hash)}
                      </div>
                      <div className={`mt-1 font-mono ${muted}`}>
                        source {shortHash(proposal.source_reference_hash)}
                      </div>
                      <div className={`mt-1 font-mono ${muted}`}>
                        thread {shortHash(proposal.chat_guid_hash)}
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => approve(proposal)}
                        className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-bold ${okClass}`}
                      >
                        <CheckCircle2 className="h-4 w-4" />
                        Approve
                      </button>
                      <button
                        type="button"
                        onClick={() => reject(proposal)}
                        className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-bold ${errorClass}`}
                      >
                        <XCircle className="h-4 w-4" />
                        Reject
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <div className={`rounded-lg border p-4 text-sm ${border} ${muted}`}>
                  No pending target-memory proposals for this person.
                </div>
              )}
            </div>
          </div>

          <div>
            <div className="flex items-center gap-2">
              <BookMarked className="h-4 w-4 text-emerald-400" />
              <span className={`text-[10px] font-mono uppercase ${muted}`}>
                Active target memory
              </span>
            </div>
            <div className="mt-3 space-y-3">
              {active.length ? (
                active.map((item) => (
                  <div key={item.id} className={`rounded-lg border p-3 ${border}`}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${okClass}`}
                      >
                        {labelize(item.kind)}
                      </span>
                      <span className={`text-[10px] font-mono uppercase ${muted}`}>
                        approved by {item.approved_by}
                      </span>
                    </div>
                    <p className="mt-2 text-sm leading-relaxed">{item.content}</p>
                    <div className={`mt-3 text-[10px] font-mono uppercase ${muted}`}>
                      evidence {shortHash(item.evidence_ref_hash)}
                    </div>
                    <button
                      type="button"
                      onClick={() => archive(item.id)}
                      className={`mt-3 inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-bold ${warnClass}`}
                    >
                      <Archive className="h-4 w-4" />
                      Archive
                    </button>
                  </div>
                ))
              ) : (
                <div className={`rounded-lg border p-4 text-sm ${border} ${muted}`}>
                  No active target memory yet for this person.
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function MetricBox({
  label,
  value,
  border,
  muted,
}: {
  label: string;
  value: number;
  border: string;
  muted: string;
}) {
  return (
    <div className={`rounded-md border px-3 py-2 ${border}`}>
      <div className={`text-[10px] font-mono uppercase ${muted}`}>{label}</div>
      <div className="text-lg font-bold">{value}</div>
    </div>
  );
}

function HashRow({
  label,
  value,
  muted,
}: {
  label: string;
  value: string;
  muted: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-current/10 py-2 last:border-b-0">
      <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
        {label}
      </span>
      <span className="text-xs font-semibold">{value}</span>
    </div>
  );
}
