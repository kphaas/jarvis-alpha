import { useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { apiJson } from "../lib/apiFetch"
import type {
  SparkIMessageDraftApprovalRequest,
  SparkIMessageDraftApprovalResponse,
  SparkIMessageDraftRequest,
  SparkIMessageDraftResponse,
} from "../types/spark"

function baseRequest(
  replyGoal: string,
  maxContextMessages: number,
): SparkIMessageDraftRequest {
  return {
    principal_id: "ken",
    reply_goal: replyGoal.trim() || null,
    max_context_messages: maxContextMessages,
  }
}

export function useSparkDraftReview() {
  const [replyGoal, setReplyGoal] = useState("")
  const [maxContextMessages, setMaxContextMessages] = useState(20)
  const [draftText, setDraftText] = useState("")

  const draftMutation = useMutation({
    mutationFn: (request: SparkIMessageDraftRequest) =>
      apiJson<SparkIMessageDraftResponse>("/v1/spark/drafts/imessage", {
        method: "POST",
        body: JSON.stringify(request),
      }),
    onSuccess: (result) => {
      setDraftText(result.draft_text)
    },
  })

  const approvalMutation = useMutation({
    mutationFn: (request: SparkIMessageDraftApprovalRequest) =>
      apiJson<SparkIMessageDraftApprovalResponse>(
        "/v1/spark/drafts/imessage/approval-request",
        {
          method: "POST",
          body: JSON.stringify(request),
        },
      ),
  })

  function generateDraft() {
    approvalMutation.reset()
    draftMutation.mutate(baseRequest(replyGoal, maxContextMessages))
  }

  function submitForApproval() {
    const request: SparkIMessageDraftApprovalRequest = {
      ...baseRequest(replyGoal, maxContextMessages),
      draft_text_override: draftText.trim() || null,
    }
    approvalMutation.mutate(request)
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
    approval: approvalMutation.data ?? null,
    approvalLoading: approvalMutation.isPending,
    approvalError: approvalMutation.error,
    submitForApproval,
    canSubmitForApproval: Boolean(draftText.trim()) && !approvalMutation.isPending,
  }
}

export type SparkDraftReviewState = ReturnType<typeof useSparkDraftReview>
