import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiJson } from "../lib/apiFetch";
import type {
  SparkDraftFeedbackLabel,
  SparkIMessageApprovedSendResponse,
  SparkIMessageDraftApprovalRequest,
  SparkIMessageDraftApprovalResponse,
  SparkIMessageDraftFeedbackRequest,
  SparkIMessageDraftFeedbackResponse,
  SparkIMessageDraftRequest,
  SparkIMessageDraftResponse,
  SparkIMessageDraftTargetsResponse,
} from "../types/spark";

export const SPARK_COMPARISON_SCENARIOS = [
  {
    id: "short_text",
    label: "Short text",
    goal: "Write this as a short, warm text reply.",
  },
  {
    id: "warmer",
    label: "Warmer",
    goal: "Write this with a warmer, more thoughtful tone.",
  },
  {
    id: "direct",
    label: "More direct",
    goal: "Write this clearly and directly with tact.",
  },
] as const;

function baseRequest(
  principalId: string,
  approvalId: string | null,
  replyGoal: string,
  maxContextMessages: number,
): SparkIMessageDraftRequest {
  return {
    principal_id: principalId,
    approval_id: approvalId,
    reply_goal: replyGoal.trim() || null,
    max_context_messages: maxContextMessages,
    include_context_preview: true,
    context_preview_limit: Math.min(maxContextMessages, 10),
    include_memory_preview: true,
  };
}

export function useSparkIMessageDraftTargets(principalId = "ken") {
  return useQuery({
    queryKey: ["spark", "imessage-draft-targets", principalId],
    queryFn: () => {
      const params = new URLSearchParams({ principal_id: principalId });
      return apiJson<SparkIMessageDraftTargetsResponse>(
        `/v1/spark/drafts/imessage/targets?${params.toString()}`,
      );
    },
    staleTime: 60_000,
  });
}

export function useSparkDraftReview(principalId = "ken", approvalId: string | null = null) {
  const [replyGoal, setReplyGoal] = useState("");
  const [maxContextMessages, setMaxContextMessages] = useState(20);
  const [draftText, setDraftText] = useState("");

  const draftMutation = useMutation({
    mutationFn: (request: SparkIMessageDraftRequest) =>
      apiJson<SparkIMessageDraftResponse>("/v1/spark/drafts/imessage", {
        method: "POST",
        body: JSON.stringify(request),
      }),
    onSuccess: (result) => {
      setDraftText(result.draft_text);
    },
  });

  const comparisonMutation = useMutation({
    mutationFn: async () =>
      Promise.all(
        SPARK_COMPARISON_SCENARIOS.map(async (scenario) => {
          const request = baseRequest(
            principalId,
            approvalId,
            `${replyGoal.trim() || "Draft a reply."} ${scenario.goal}`,
            maxContextMessages,
          );
          const draft = await apiJson<SparkIMessageDraftResponse>(
            "/v1/spark/drafts/imessage",
            {
              method: "POST",
              body: JSON.stringify(request),
            },
          );
          return {
            ...scenario,
            draft,
          };
        }),
      ),
  });

  const approvalMutation = useMutation({
    mutationFn: (request: SparkIMessageDraftApprovalRequest) =>
      apiJson<SparkIMessageDraftApprovalResponse>(
        "/v1/spark/drafts/imessage/approval-request",
        {
          method: "POST",
          body: JSON.stringify(request),
        },
      ),
  });

  const feedbackMutation = useMutation({
    mutationFn: (feedbackLabel: SparkDraftFeedbackLabel) => {
      if (!draftMutation.data) {
        throw new Error("no_draft_for_feedback");
      }
      const request: SparkIMessageDraftFeedbackRequest = {
        principal_id: principalId,
        feedback_label: feedbackLabel,
        draft_version: draftMutation.data.draft_version,
        approval_ref_hash: draftMutation.data.approval_ref_hash,
        source_reference_hash: draftMutation.data.source_reference_hash,
        chat_guid_hash: draftMutation.data.chat_guid_hash,
      };
      return apiJson<SparkIMessageDraftFeedbackResponse>(
        "/v1/spark/drafts/imessage/feedback",
        {
          method: "POST",
          body: JSON.stringify(request),
        },
      );
    },
  });

  const approvedSendMutation = useMutation({
    mutationFn: (outboxId: string) =>
      apiJson<SparkIMessageApprovedSendResponse>(
        `/v1/spark/drafts/imessage/outbox/${outboxId}/send`,
        {
          method: "POST",
        },
      ),
  });

  function generateDraft() {
    approvalMutation.reset();
    feedbackMutation.reset();
    approvedSendMutation.reset();
    draftMutation.mutate(
      baseRequest(principalId, approvalId, replyGoal, maxContextMessages),
    );
  }

  function generateComparisons() {
    approvalMutation.reset();
    feedbackMutation.reset();
    approvedSendMutation.reset();
    comparisonMutation.mutate();
  }

  function submitForApproval() {
    const request: SparkIMessageDraftApprovalRequest = {
      ...baseRequest(principalId, approvalId, replyGoal, maxContextMessages),
      draft_text_override: draftText.trim() || null,
    };
    approvalMutation.mutate(request);
  }

  function recordFeedback(feedbackLabel: SparkDraftFeedbackLabel) {
    feedbackMutation.mutate(feedbackLabel);
  }

  function sendApprovedOutbox() {
    const outboxId = approvalMutation.data?.outbox_id;
    if (!outboxId) {
      throw new Error("no_outbox_for_send");
    }
    approvedSendMutation.mutate(outboxId);
  }

  function resetDraftSurface() {
    setDraftText("");
    draftMutation.reset();
    comparisonMutation.reset();
    approvalMutation.reset();
    feedbackMutation.reset();
    approvedSendMutation.reset();
  }

  return {
    replyGoal,
    setReplyGoal,
    maxContextMessages,
    setMaxContextMessages,
    draftText,
    setDraftText,
    draft: draftMutation.data ?? null,
    draftLoading: draftMutation.isPending,
    draftError: draftMutation.error,
    generateDraft,
    comparisonDrafts: comparisonMutation.data ?? [],
    comparisonLoading: comparisonMutation.isPending,
    comparisonError: comparisonMutation.error,
    generateComparisons,
    approval: approvalMutation.data ?? null,
    approvalLoading: approvalMutation.isPending,
    approvalError: approvalMutation.error,
    submitForApproval,
    canSubmitForApproval:
      Boolean(draftText.trim()) && !approvalMutation.isPending,
    recordFeedback,
    feedback: feedbackMutation.data ?? null,
    feedbackLoading: feedbackMutation.isPending,
    feedbackError: feedbackMutation.error,
    approvedSend: approvedSendMutation.data ?? null,
    approvedSendLoading: approvedSendMutation.isPending,
    approvedSendError: approvedSendMutation.error,
    sendApprovedOutbox,
    canSendApprovedOutbox:
      Boolean(approvalMutation.data?.outbox_id) && !approvedSendMutation.isPending,
    resetDraftSurface,
  };
}

export type SparkDraftReviewState = ReturnType<typeof useSparkDraftReview>;
