import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  SparkIMessageOutboxListResponse,
  SparkIMessageDraftTargetsResponse,
  SparkIMessageTargetPreviewResponse,
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

const FEEDBACK_RETRY_ADJUSTMENTS: Record<SparkDraftFeedbackLabel, string> = {
  sounds_like_me:
    "Keep this direction. Stay natural, specific, and in the same thread.",
  voice_rewrite:
    "Use my edited draft as the strongest voice example. Match its wording length, directness, and level of warmth instead of generic polishing.",
  out_of_context:
    "The previous draft missed the thread context. Answer only the latest inbound ask first, stay on the same subject, and do not introduce any new logistics or facts unless they were already in the thread.",
  too_robotic:
    "Make the reply less robotic and more like Ken texting. Use plain spoken language, contractions, and no assistant wrap-up.",
  too_formal:
    "Make the reply more casual and text-message natural. No email phrasing.",
  too_much_policy:
    "Strip policy or process language. Keep the reply personal, concrete, and human.",
  too_wordy:
    "Cut this down to one or two short text-message sentences while preserving the useful answer.",
};

function mergeStyleAdjustments(
  selected: string[],
  feedbackLabels: SparkDraftFeedbackLabel[],
) {
  return [
    ...feedbackLabels.map((feedbackLabel) => FEEDBACK_RETRY_ADJUSTMENTS[feedbackLabel]),
    ...selected,
  ]
    .filter((item, index, all) => item.trim() && all.indexOf(item) === index)
    .slice(0, 3);
}

function baseRequest(
  principalId: string,
  approvalId: string | null,
  replyGoal: string,
  maxContextMessages: number,
  styleAdjustments: string[],
): SparkIMessageDraftRequest {
  return {
    principal_id: principalId,
    approval_id: approvalId,
    reply_goal: replyGoal.trim() || null,
    max_context_messages: maxContextMessages,
    style_adjustments: styleAdjustments,
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

export function useSparkIMessageTargetPreview(
  principalId = "ken",
  approvalId: string | null = null,
) {
  return useQuery({
    queryKey: ["spark", "imessage-target-preview", principalId, approvalId],
    queryFn: () => {
      const params = new URLSearchParams({
        principal_id: principalId,
        approval_id: approvalId ?? "",
        limit: "8",
      });
      return apiJson<SparkIMessageTargetPreviewResponse>(
        `/v1/spark/drafts/imessage/target-preview?${params.toString()}`,
      );
    },
    enabled: Boolean(approvalId),
    staleTime: 30_000,
  });
}

export function useSparkIMessageOutbox(principalId = "ken") {
  return useQuery({
    queryKey: ["spark", "imessage-outbox", principalId],
    queryFn: () => {
      const params = new URLSearchParams({
        principal_id: principalId,
        limit: "25",
      });
      return apiJson<SparkIMessageOutboxListResponse>(
        `/v1/spark/drafts/imessage/outbox?${params.toString()}`,
      );
    },
    staleTime: 15_000,
  });
}

export function useSparkDraftReview(principalId = "ken", approvalId: string | null = null) {
  const queryClient = useQueryClient();
  const [replyGoal, setReplyGoal] = useState("");
  const [maxContextMessages, setMaxContextMessages] = useState(8);
  const [styleAdjustments, setStyleAdjustments] = useState<string[]>([]);
  const [draftText, setDraftText] = useState("");
  const [selectedFeedbackLabels, setSelectedFeedbackLabels] = useState<
    SparkDraftFeedbackLabel[]
  >([]);
  const [lastSubmittedFeedbackLabels, setLastSubmittedFeedbackLabels] = useState<
    SparkDraftFeedbackLabel[]
  >([]);

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
            styleAdjustments,
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
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["spark", "imessage-outbox", principalId],
      });
    },
  });

  const feedbackMutation = useMutation({
    mutationFn: async (feedbackLabels: SparkDraftFeedbackLabel[]) => {
      if (!draftMutation.data) {
        throw new Error("no_draft_for_feedback");
      }
      const responses = await Promise.all(
        feedbackLabels.map((feedbackLabel) => {
          const request: SparkIMessageDraftFeedbackRequest = {
            principal_id: principalId,
            feedback_label: feedbackLabel,
            draft_version: draftMutation.data!.draft_version,
            approval_ref_hash: draftMutation.data!.approval_ref_hash,
            source_reference_hash: draftMutation.data!.source_reference_hash,
            chat_guid_hash: draftMutation.data!.chat_guid_hash,
            draft_text_override:
              feedbackLabel === "voice_rewrite" ? draftText.trim() || null : null,
          };
          return apiJson<SparkIMessageDraftFeedbackResponse>(
            "/v1/spark/drafts/imessage/feedback",
            {
              method: "POST",
              body: JSON.stringify(request),
            },
          );
        }),
      );
      return {
        feedbackLabels,
        responses,
      };
    },
    onSuccess: (result) => {
      setLastSubmittedFeedbackLabels(result.feedbackLabels);
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
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["spark", "imessage-outbox", principalId],
      });
    },
  });

  const trustedLiveSendMutation = useMutation({
    mutationFn: (outboxId: string) =>
      apiJson<SparkIMessageApprovedSendResponse>(
        `/v1/spark/drafts/imessage/outbox/${outboxId}/trusted-live-send`,
        {
          method: "POST",
        },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["spark", "imessage-outbox", principalId],
      });
    },
  });

  function generateDraft() {
    approvalMutation.reset();
    feedbackMutation.reset();
    approvedSendMutation.reset();
    trustedLiveSendMutation.reset();
    setSelectedFeedbackLabels([]);
    setLastSubmittedFeedbackLabels([]);
    draftMutation.mutate(
      baseRequest(
        principalId,
        approvalId,
        replyGoal,
        maxContextMessages,
        styleAdjustments,
      ),
    );
  }

  async function regenerateWithFeedback() {
    if (!selectedFeedbackLabels.length) {
      throw new Error("no_feedback_for_retry");
    }
    approvalMutation.reset();
    approvedSendMutation.reset();
    trustedLiveSendMutation.reset();
    await feedbackMutation.mutateAsync(selectedFeedbackLabels);
    draftMutation.mutate(
      baseRequest(
        principalId,
        approvalId,
        replyGoal,
        maxContextMessages,
        mergeStyleAdjustments(styleAdjustments, selectedFeedbackLabels),
      ),
    );
  }

  function generateComparisons() {
    approvalMutation.reset();
    feedbackMutation.reset();
    approvedSendMutation.reset();
    trustedLiveSendMutation.reset();
    comparisonMutation.mutate();
  }

  function submitForApproval() {
    const request: SparkIMessageDraftApprovalRequest = {
      ...baseRequest(
        principalId,
        approvalId,
        replyGoal,
        maxContextMessages,
        styleAdjustments,
      ),
      draft_text_override: draftText.trim() || null,
    };
    approvalMutation.mutate(request);
  }

  function toggleFeedbackLabel(feedbackLabel: SparkDraftFeedbackLabel) {
    setSelectedFeedbackLabels((current) => {
      if (current.includes(feedbackLabel)) {
        return current.filter((item) => item !== feedbackLabel);
      }
      if (current.length >= 3) {
        return current;
      }
      return [...current, feedbackLabel];
    });
  }

  function sendApprovedOutbox(outboxId?: string | null) {
    const resolvedOutboxId = outboxId ?? approvalMutation.data?.outbox_id;
    if (!resolvedOutboxId) {
      throw new Error("no_outbox_for_send");
    }
    approvedSendMutation.mutate(resolvedOutboxId);
  }

  function sendTrustedLiveOutbox(outboxId?: string | null) {
    const resolvedOutboxId = outboxId ?? approvalMutation.data?.outbox_id;
    if (!resolvedOutboxId) {
      throw new Error("no_outbox_for_send");
    }
    trustedLiveSendMutation.mutate(resolvedOutboxId);
  }

  function hasSendableOutbox(outboxId?: string | null) {
    const resolvedOutboxId = outboxId ?? approvalMutation.data?.outbox_id;
    return (
      Boolean(resolvedOutboxId) &&
      !approvedSendMutation.isPending &&
      !trustedLiveSendMutation.isPending
    );
  }

  function resetDraftSurface() {
    setDraftText("");
    setStyleAdjustments([]);
    setSelectedFeedbackLabels([]);
    setLastSubmittedFeedbackLabels([]);
    draftMutation.reset();
    comparisonMutation.reset();
    approvalMutation.reset();
    feedbackMutation.reset();
    approvedSendMutation.reset();
    trustedLiveSendMutation.reset();
  }

  return {
    replyGoal,
    setReplyGoal,
    maxContextMessages,
    setMaxContextMessages,
    styleAdjustments,
    setStyleAdjustments,
    draftText,
    setDraftText,
    draft: draftMutation.data ?? null,
    draftLoading: draftMutation.isPending,
    draftError: draftMutation.error,
    generateDraft,
    regenerateWithFeedback,
    canRegenerateWithFeedback:
      Boolean(selectedFeedbackLabels.length) &&
      Boolean(draftText.trim()) &&
      !draftMutation.isPending &&
      !feedbackMutation.isPending,
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
    toggleFeedbackLabel,
    feedback: feedbackMutation.data?.responses ?? [],
    selectedFeedbackLabels,
    lastSubmittedFeedbackLabels,
    feedbackLoading: feedbackMutation.isPending,
    feedbackError: feedbackMutation.error,
    approvedSend: approvedSendMutation.data ?? null,
    approvedSendLoading: approvedSendMutation.isPending,
    approvedSendError: approvedSendMutation.error,
    sendApprovedOutbox,
    trustedLiveSend: trustedLiveSendMutation.data ?? null,
    trustedLiveSendLoading: trustedLiveSendMutation.isPending,
    trustedLiveSendError: trustedLiveSendMutation.error,
    sendTrustedLiveOutbox,
    hasSendableOutbox,
    canSendApprovedOutbox:
      Boolean(approvalMutation.data?.outbox_id) &&
      !approvedSendMutation.isPending &&
      !trustedLiveSendMutation.isPending,
    resetDraftSurface,
    canSelectMoreFeedback: selectedFeedbackLabels.length < 3,
    feedbackRecorded:
      lastSubmittedFeedbackLabels.length > 0 &&
      Boolean(feedbackMutation.data?.responses.every((item) => item.feedback_recorded)),
  };
}

export type SparkDraftReviewState = ReturnType<typeof useSparkDraftReview>;
