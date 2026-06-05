import { useEffect, useState } from "react";
import { privacyJson } from "../lib/privacyIntake";
import type { CaseDraftCreateResponse } from "../types/privacy";

export function usePrivacyCaseDraft(
  subjectId: string | null,
  selectedTargetIds: string[],
) {
  const [draft, setDraft] = useState<CaseDraftCreateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canCreate =
    Boolean(subjectId) && selectedTargetIds.length > 0 && !loading;

  useEffect(() => {
    setDraft(null);
    setError(null);
  }, [subjectId]);

  async function createDraft() {
    if (!subjectId || !canCreate) return null;

    setLoading(true);
    setError(null);
    try {
      const response = await privacyJson<CaseDraftCreateResponse>(
        `/v1/privacy/subjects/${subjectId}/case-drafts`,
        { target_ids: selectedTargetIds },
      );
      setDraft(response);
      return response;
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "privacy_case_draft_failed",
      );
      return null;
    } finally {
      setLoading(false);
    }
  }

  function clearDraft() {
    setDraft(null);
    setError(null);
  }

  return {
    draft,
    loading,
    error,
    canCreate,
    createDraft,
    clearDraft,
  };
}

export type PrivacyCaseDraftState = ReturnType<typeof usePrivacyCaseDraft>;
