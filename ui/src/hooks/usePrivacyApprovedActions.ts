import { useState } from "react";
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

export function usePrivacyApprovedActions() {
  const queryClient = useQueryClient();
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

  async function loadCaseWorkflow(caseId: string) {
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
  }

  return {
    actions: actionsQuery.data?.actions ?? [],
    count: actionsQuery.data?.count ?? 0,
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
