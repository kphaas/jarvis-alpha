import { useState } from "react";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  Archive,
  Lightbulb,
  XCircle,
  LoaderCircle,
  Plus,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useSparkPersonalityMemory } from "../../hooks/useSparkPersonalityMemory";
import type {
  SparkPersonalityMemoryProposal,
  SparkPersonalityMemorySource,
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
  principalLabel: string;
}

function labelize(value: string) {
  return value.replace(/_/g, " ");
}

function sourceLabel(source: SparkPersonalityMemorySource) {
  if (source === "spark_feedback") return "reviewed edit";
  if (source === "spark_vault") return "guardrail";
  if (source === "buddy_proposal") return "buddy";
  return "approved";
}

export function SparkMemoryReviewPanel({
  border,
  panel,
  input,
  muted,
  okClass,
  warnClass,
  errorClass,
  principalId,
  principalLabel,
}: StyleProps) {
  const state = useSparkPersonalityMemory(principalId);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [memoryNote, setMemoryNote] = useState("");

  const proposedMemory = state.proposeMemoryResult?.proposal ?? null;
  const backendProposals = state.memory?.proposals ?? [];
  const proposals = proposedMemory
    ? [
        proposedMemory,
        ...backendProposals.filter(
          (proposal) => proposal.proposal_id !== proposedMemory.proposal_id,
        ),
      ]
    : backendProposals;
  const active = state.memory?.active ?? [];
  const scorecard = state.memory?.scorecard ?? null;
  const feedbackPhraseCount = state.memory?.buddy.feedback_phrase_count ?? 0;
  const pendingPhraseCount = proposals.filter(
    (proposal) => proposal.kind === "phrase",
  ).length;

  function editedContent(proposal: SparkPersonalityMemoryProposal) {
    return edits[proposal.proposal_id] ?? proposal.content;
  }

  function approve(proposal: SparkPersonalityMemoryProposal) {
    const content = editedContent(proposal).trim();
    if (!content || state.approveMemoryLoading) return;
    state.approveMemory({
      approved: true,
      proposal_id: proposal.proposal_id,
      principal_id: proposal.principal_id,
      kind: proposal.kind,
      content,
      source: proposal.source,
      evidence_ref_hash: proposal.evidence_ref_hash ?? null,
      importance_score: proposal.confidence,
    });
  }

  function reject(proposal: SparkPersonalityMemoryProposal) {
    if (state.rejectMemoryLoading) return;
    state.rejectMemory({
      principal_id: proposal.principal_id,
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
    if (!note || state.proposeMemoryLoading) return;
    state.proposeMemory({
      principal_id: principalId,
      note,
    });
  }

  if (state.memoryLoading) {
    return (
      <section className={`rounded-xl border ${border} ${panel} p-5`}>
        <div className="flex min-h-32 items-center justify-center gap-2 text-sm opacity-60">
          <LoaderCircle className="h-4 w-4 animate-spin" />
          Loading memory review
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
          Memory review unavailable
        </div>
      </section>
    );
  }

  return (
    <section className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-emerald-400" />
          <h2
            className={`text-xs font-mono uppercase tracking-widest ${muted}`}
          >
            Memory review
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${okClass}`}
          >
            {principalLabel}
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
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-400" />
              <span
                className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
              >
                Memory scorecard
              </span>
            </div>
            <span
              className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${
                scorecard.readiness === "strong" ? okClass : warnClass
              }`}
            >
              {labelize(scorecard.readiness)}
            </span>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            <div className={`rounded-md border px-3 py-2 ${border}`}>
              <div className={`text-[10px] font-mono uppercase ${muted}`}>
                Active
              </div>
              <div className="text-lg font-bold">{scorecard.active_count}</div>
            </div>
            <div className={`rounded-md border px-3 py-2 ${border}`}>
              <div className={`text-[10px] font-mono uppercase ${muted}`}>
                Proposals
              </div>
              <div className="text-lg font-bold">{scorecard.proposal_count}</div>
            </div>
            <div className={`rounded-md border px-3 py-2 ${border}`}>
              <div className={`text-[10px] font-mono uppercase ${muted}`}>
                Edit phrases
              </div>
              <div className="text-lg font-bold">
                {scorecard.feedback_phrase_count}
              </div>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {scorecard.kinds_present.map((kind) => (
              <span
                key={kind}
                className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${okClass}`}
              >
                {labelize(kind)}
              </span>
            ))}
            {scorecard.missing_core_kinds.map((kind) => (
              <span
                key={kind}
                className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${warnClass}`}
              >
                Missing {labelize(kind)}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
        <div className="space-y-3">
          <div className={`rounded-lg border p-3 ${border}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Lightbulb className="h-4 w-4 text-emerald-400" />
                <span
                  className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
                >
                  Ask Buddy
                </span>
              </div>
              <span
                className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${okClass}`}
              >
                proposal only
              </span>
            </div>
            <textarea
              value={memoryNote}
              onChange={(event) => setMemoryNote(event.target.value)}
              rows={3}
              maxLength={800}
              placeholder="Remember that I prefer short bullets when decisions are time-sensitive."
              className={`mt-3 w-full resize-y rounded-lg border p-3 text-sm outline-none transition focus:border-emerald-400 ${input}`}
            />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <span className={`text-xs ${muted}`}>
                Buddy drafts it. Approval still writes it.
              </span>
              <button
                type="button"
                onClick={proposeFromNote}
                disabled={!memoryNote.trim() || state.proposeMemoryLoading}
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
                Propose memory
              </button>
            </div>
            {state.proposeMemoryResult?.status === "not_proposed" && (
              <div
                className={`mt-3 flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${warnClass}`}
              >
                <AlertTriangle className="h-4 w-4 shrink-0" />
                Memory note needs a safer rewrite
              </div>
            )}
            {state.proposeMemoryError && (
              <div
                className={`mt-3 flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${errorClass}`}
              >
                <AlertTriangle className="h-4 w-4 shrink-0" />
                Buddy proposal failed
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <span
              className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
            >
              Proposed phrases/rules
            </span>
            <span className={`text-xs ${muted}`}>
              {pendingPhraseCount} key phrases,{" "}
              {proposals.length - pendingPhraseCount} rules,{" "}
              {feedbackPhraseCount} from reviewed edits
            </span>
          </div>
          {proposals.length ? (
            proposals.map((proposal) => (
              <div
                key={proposal.proposal_id}
                className={`rounded-lg border p-3 ${border}`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${okClass}`}
                  >
                    {labelize(proposal.kind)}
                  </span>
                  <span
                    className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${warnClass}`}
                  >
                    {sourceLabel(proposal.source)}
                  </span>
                  <span className={`text-[10px] font-mono uppercase ${muted}`}>
                    {Math.round(proposal.confidence * 100)} confidence
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
                  maxLength={500}
                  className={`mt-3 w-full resize-y rounded-lg border p-3 text-sm outline-none transition focus:border-emerald-400 ${input}`}
                />
                <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                  <span className={`min-w-0 text-xs ${muted}`}>
                    {proposal.reason}
                  </span>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => reject(proposal)}
                      disabled={state.rejectMemoryLoading}
                      className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-bold transition ${border}`}
                    >
                      {state.rejectMemoryLoading ? (
                        <LoaderCircle className="h-4 w-4 animate-spin" />
                      ) : (
                        <XCircle className="h-4 w-4" />
                      )}
                      Reject
                    </button>
                    <button
                      type="button"
                      onClick={() => approve(proposal)}
                      disabled={
                        state.approveMemoryLoading ||
                        !editedContent(proposal).trim()
                      }
                      className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-bold transition ${border} ${
                        editedContent(proposal).trim()
                          ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300"
                          : "opacity-45"
                      }`}
                    >
                      {state.approveMemoryLoading ? (
                        <LoaderCircle className="h-4 w-4 animate-spin" />
                      ) : (
                        <ShieldCheck className="h-4 w-4" />
                      )}
                      Approve
                    </button>
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className={`rounded-lg border p-4 text-sm ${border} ${muted}`}>
              No memory proposals waiting
            </div>
          )}
        </div>

        <div className="space-y-3">
          <span
            className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}
          >
            Approved memory
          </span>
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
                    {sourceLabel(item.source)}
                  </span>
                </div>
                <p className="mt-2 text-sm leading-relaxed">{item.content}</p>
                <div className="mt-3 flex justify-end">
                  <button
                    type="button"
                    onClick={() => archive(item.id)}
                    disabled={state.archiveMemoryLoading}
                    className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-bold transition ${border}`}
                  >
                    {state.archiveMemoryLoading ? (
                      <LoaderCircle className="h-4 w-4 animate-spin" />
                    ) : (
                      <Archive className="h-4 w-4" />
                    )}
                    Archive
                  </button>
                </div>
              </div>
            ))
          ) : (
            <div className={`rounded-lg border p-4 text-sm ${border} ${muted}`}>
              No approved Spark memory yet
            </div>
          )}
          {state.approveMemoryError && (
            <div
              className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${errorClass}`}
            >
              <AlertTriangle className="h-4 w-4 shrink-0" />
              Approval failed
            </div>
          )}
          {state.archiveMemoryError && (
            <div
              className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${errorClass}`}
            >
              <AlertTriangle className="h-4 w-4 shrink-0" />
              Archive failed
            </div>
          )}
          {state.rejectMemoryError && (
            <div
              className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${errorClass}`}
            >
              <AlertTriangle className="h-4 w-4 shrink-0" />
              Reject failed
            </div>
          )}
          {state.approveMemoryResult?.status === "saved" && (
            <div
              className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${okClass}`}
            >
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              Memory approved
            </div>
          )}
          {state.archiveMemoryResult?.status === "archived" && (
            <div
              className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${okClass}`}
            >
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              Memory archived
            </div>
          )}
          {state.rejectMemoryResult?.status === "rejected" && (
            <div
              className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${okClass}`}
            >
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              Proposal rejected
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
