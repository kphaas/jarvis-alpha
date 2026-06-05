import { useQuery, useQueryClient } from "@tanstack/react-query";
import { privacyGetJson } from "../lib/privacyIntake";
import type { ApprovedPrivacyActionsResponse } from "../types/privacy";

const APPROVED_ACTIONS_KEY = ["privacy", "approved-actions"] as const;

export function usePrivacyApprovedActions() {
  const queryClient = useQueryClient();
  const actionsQuery = useQuery({
    queryKey: APPROVED_ACTIONS_KEY,
    queryFn: () =>
      privacyGetJson<ApprovedPrivacyActionsResponse>(
        "/v1/privacy/actions/approved",
      ),
    staleTime: 60 * 1000,
  });

  function refreshActions() {
    void queryClient.invalidateQueries({ queryKey: APPROVED_ACTIONS_KEY });
  }

  return {
    actions: actionsQuery.data?.actions ?? [],
    count: actionsQuery.data?.count ?? 0,
    isLoading: actionsQuery.isLoading,
    error: actionsQuery.error,
    refreshActions,
  };
}

export type PrivacyApprovedActionsState = ReturnType<
  typeof usePrivacyApprovedActions
>;
