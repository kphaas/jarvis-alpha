import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { apiJson } from "../lib/apiFetch";
import type {
  SparkDraftFeedbackLabel,
  SparkIMessageDraftApprovalRequest,
  SparkIMessageDraftApprovalResponse,
  SparkIMessageDraftFeedbackRequest,
  SparkIMessageDraftFeedbackResponse,
  SparkIMessageDraftRequest,
  SparkIMessageDraftResponse,
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
  replyGoal: string,
  maxContextMessages: number,
): SparkIMessageDraftRequest {
  return {
    principal_id: principalId,
    reply_goal: replyGoal.trim() || null,
    max_context_messages: maxContextMessages,
    include_context_preview: true,
    context_preview_limit: Math.min(maxContextMessages, 10),
    include_memory_preview: true,
  };
}

export function useSparkDraftReview(principalId = "ken") {
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

  function generateDraft() {
    approvalMutation.reset();
    feedbackMutation.reset();
    draftMutation.mutate(
      baseRequest(principalId, replyGoal, maxContextMessages),
    );
  }

  function generateComparisons() {
    approvalMutation.reset();
    feedbackMutation.reset();
    comparisonMutation.mutate();
  }

  function submitForApproval() {
    const request: SparkIMessageDraftApprovalRequest = {
      ...baseRequest(principalId, replyGoal, maxContextMessages),
      draft_text_override: draftText.trim() || null,
    };
    approvalMutation.mutate(request);
  }

  function recordFeedback(feedbackLabel: SparkDraftFeedbackLabel) {
    feedbackMutation.mutate(feedbackLabel);
  }

  function resetDraftSurface() {
    setDraftText("");
    draftMutation.reset();
    comparisonMutation.reset();
    approvalMutation.reset();
    feedbackMutation.reset();
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
    resetDraftSurface,
  };
}

export type SparkDraftReviewState = ReturnType<typeof useSparkDraftReview>;
