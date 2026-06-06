import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { privacyGetJson, privacyJson } from "../lib/privacyIntake";
import type {
  CaseDraftDetailResponse,
  CaseDraftDispositionResponse,
  CaseDraftListResponse,
} from "../types/privacy";

const DRAFT_LIST_KEY = ["privacy", "case-drafts"] as const;
type DispositionPath = "submit-approval" | "archive";

export function usePrivacyDraftInbox(initialCaseId: string | null = null) {
  const queryClient = useQueryClient();
  const [manualSelectedCaseId, setManualSelectedCaseId] = useState<
    string | null
  >(null);
  const [pendingDispositionPath, setPendingDispositionPath] =
    useState<DispositionPath | null>(null);
  const selectedCaseId = manualSelectedCaseId ?? initialCaseId;

  const listQuery = useQuery({
    queryKey: DRAFT_LIST_KEY,
    queryFn: () =>
      privacyGetJson<CaseDraftListResponse>("/v1/privacy/case-drafts"),
    staleTime: 60 * 1000,
  });
  const detailQuery = useQuery({
    queryKey: ["privacy", "case-drafts", selectedCaseId],
    queryFn: () =>
      privacyGetJson<CaseDraftDetailResponse>(
        `/v1/privacy/case-drafts/${selectedCaseId}`,
      ),
    enabled: Boolean(selectedCaseId),
    staleTime: 60 * 1000,
  });
  const dispositionMutation = useMutation({
    mutationFn: ({
      caseId,
      path,
    }: {
      caseId: string;
      path: DispositionPath;
    }) =>
      privacyJson<CaseDraftDispositionResponse>(
        `/v1/privacy/case-drafts/${caseId}/${path}`,
        {},
      ),
    onMutate: (variables) => {
      setPendingDispositionPath(variables.path);
    },
    onSuccess: (result) => {
      setManualSelectedCaseId(result.case_id);
      void queryClient.invalidateQueries({ queryKey: DRAFT_LIST_KEY });
      void queryClient.invalidateQueries({
        queryKey: ["privacy", "case-drafts", result.case_id],
      });
    },
    onSettled: () => {
      setPendingDispositionPath(null);
    },
  });

  function refreshDrafts() {
    void queryClient.invalidateQueries({ queryKey: DRAFT_LIST_KEY });
    if (selectedCaseId) {
      void queryClient.invalidateQueries({
        queryKey: ["privacy", "case-drafts", selectedCaseId],
      });
    }
  }

  function submitSelectedDraftForApproval() {
    if (!selectedCaseId) return;
    dispositionMutation.mutate({
      caseId: selectedCaseId,
      path: "submit-approval",
    });
  }

  function archiveSelectedDraft() {
    if (!selectedCaseId) return;
    dispositionMutation.mutate({
      caseId: selectedCaseId,
      path: "archive",
    });
  }

  return {
    drafts: listQuery.data?.drafts ?? [],
    count: listQuery.data?.count ?? 0,
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    refreshDrafts,
    selectedCaseId,
    selectCase: setManualSelectedCaseId,
    selectedDraft: detailQuery.data ?? null,
    detailLoading: detailQuery.isLoading,
    detailError: detailQuery.error,
    submitSelectedDraftForApproval,
    archiveSelectedDraft,
    dispositionLoading: dispositionMutation.isPending,
    pendingDispositionPath,
    dispositionError: dispositionMutation.error,
    dispositionResult: dispositionMutation.data ?? null,
  };
}

export type PrivacyDraftInboxState = ReturnType<typeof usePrivacyDraftInbox>;
