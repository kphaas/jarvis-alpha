import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { privacyGetJson, privacyJson } from "../lib/privacyIntake";
import type {
  ActionWorkflowResponse,
  ApprovedPrivacyActionsResponse,
  ManualDisposition,
  PrivacyCaseReportResponse,
  PrivacyCaseTimelineResponse,
  VerificationOutcome,
} from "../types/privacy";

const APPROVED_ACTIONS_KEY = ["privacy", "approved-actions"] as const;

type ManualDispositionInput = {
  actionId: string;
  disposition: ManualDisposition;
  operator_note?: string;
  evidence_reference?: string;
  verification_due_at?: string | null;
};

type VerificationInput = {
  actionId: string;
  outcome: VerificationOutcome;
  operator_note?: string;
  evidence_reference?: string;
  verification_due_at?: string | null;
};

export function usePrivacyApprovedActions(
  initialActionId: string | null = null,
  initialCaseId: string | null = null,
) {
  const queryClient = useQueryClient();
  const [manualSelectedActionId, setManualSelectedActionId] = useState<
    string | null
  >(null);
  const [caseWorkflow, setCaseWorkflow] = useState<{
    caseId: string;
    timeline: PrivacyCaseTimelineResponse;
    report: PrivacyCaseReportResponse;
  } | null>(null);
  const [caseWorkflowError, setCaseWorkflowError] = useState<Error | null>(null);
  const [caseWorkflowLoading, setCaseWorkflowLoading] = useState(false);
  const actionsQuery = useQuery({
    queryKey: APPROVED_ACTIONS_KEY,
    queryFn: () =>
      privacyGetJson<ApprovedPrivacyActionsResponse>(
        "/v1/privacy/actions/approved",
      ),
    staleTime: 60 * 1000,
  });
  const actions = useMemo(
    () => actionsQuery.data?.actions ?? [],
    [actionsQuery.data?.actions],
  );
  const deepLinkedCaseActionId =
    initialCaseId && !initialActionId
      ? actions.find((action) => action.case_id === initialCaseId)?.action_id ??
        null
      : null;
  const selectedActionId =
    manualSelectedActionId ?? initialActionId ?? deepLinkedCaseActionId;
  const manualDispositionMutation = useMutation({
    mutationFn: (input: ManualDispositionInput) =>
      privacyJson<ActionWorkflowResponse>(
        `/v1/privacy/actions/${input.actionId}/manual-disposition`,
        {
          disposition: input.disposition,
          operator_note: input.operator_note,
          evidence_reference: input.evidence_reference,
          verification_due_at: input.verification_due_at,
        },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: APPROVED_ACTIONS_KEY });
    },
  });
  const verificationMutation = useMutation({
    mutationFn: (input: VerificationInput) =>
      privacyJson<ActionWorkflowResponse>(
        `/v1/privacy/actions/${input.actionId}/verification`,
        {
          outcome: input.outcome,
          operator_note: input.operator_note,
          evidence_reference: input.evidence_reference,
          verification_due_at: input.verification_due_at,
        },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: APPROVED_ACTIONS_KEY });
    },
  });

  function refreshActions() {
    void queryClient.invalidateQueries({ queryKey: APPROVED_ACTIONS_KEY });
  }

  async function recordManualDisposition(input: ManualDispositionInput) {
    return manualDispositionMutation.mutateAsync(input);
  }

  async function recordVerification(input: VerificationInput) {
    return verificationMutation.mutateAsync(input);
  }

  const loadCaseWorkflow = useCallback(async (caseId: string) => {
    setCaseWorkflowLoading(true);
    setCaseWorkflowError(null);
    try {
      const [timeline, report] = await Promise.all([
        privacyGetJson<PrivacyCaseTimelineResponse>(
          `/v1/privacy/case-drafts/${caseId}/timeline`,
        ),
        privacyGetJson<PrivacyCaseReportResponse>(
          `/v1/privacy/case-drafts/${caseId}/report`,
        ),
      ]);
      setCaseWorkflow({ caseId, timeline, report });
    } catch (error) {
      setCaseWorkflowError(
        error instanceof Error ? error : new Error("case workflow unavailable"),
      );
    } finally {
      setCaseWorkflowLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedActionId) return;
    const selectedAction = actions.find(
      (action) => action.action_id === selectedActionId,
    );
    if (selectedAction && selectedAction.case_id !== caseWorkflow?.caseId) {
      void loadCaseWorkflow(selectedAction.case_id);
    }
  }, [actions, caseWorkflow?.caseId, loadCaseWorkflow, selectedActionId]);

  return {
    actions,
    count: actionsQuery.data?.count ?? 0,
    selectedActionId,
    selectedAction:
      actions.find((action) => action.action_id === selectedActionId) ?? null,
    selectAction: setManualSelectedActionId,
    isLoading: actionsQuery.isLoading,
    error: actionsQuery.error,
    workflowError:
      manualDispositionMutation.error ??
      verificationMutation.error ??
      caseWorkflowError,
    isSaving:
      manualDispositionMutation.isPending || verificationMutation.isPending,
    caseWorkflow,
    caseWorkflowLoading,
    refreshActions,
    recordManualDisposition,
    recordVerification,
    loadCaseWorkflow,
  };
}

export type PrivacyApprovedActionsState = ReturnType<
  typeof usePrivacyApprovedActions
>;
