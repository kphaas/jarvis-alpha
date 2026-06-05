import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { privacyGetJson } from "../lib/privacyIntake";
import type {
  CaseDraftDetailResponse,
  CaseDraftListResponse,
} from "../types/privacy";

const DRAFT_LIST_KEY = ["privacy", "case-drafts"] as const;

export function usePrivacyDraftInbox() {
  const queryClient = useQueryClient();
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
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

  function refreshDrafts() {
    void queryClient.invalidateQueries({ queryKey: DRAFT_LIST_KEY });
    if (selectedCaseId) {
      void queryClient.invalidateQueries({
        queryKey: ["privacy", "case-drafts", selectedCaseId],
      });
    }
  }

  return {
    drafts: listQuery.data?.drafts ?? [],
    count: listQuery.data?.count ?? 0,
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    refreshDrafts,
    selectedCaseId,
    selectCase: setSelectedCaseId,
    selectedDraft: detailQuery.data ?? null,
    detailLoading: detailQuery.isLoading,
    detailError: detailQuery.error,
  };
}

export type PrivacyDraftInboxState = ReturnType<typeof usePrivacyDraftInbox>;
