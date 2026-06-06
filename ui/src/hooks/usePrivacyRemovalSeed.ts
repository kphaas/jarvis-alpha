import { useMutation } from "@tanstack/react-query";
import { privacyJson } from "../lib/privacyIntake";
import type { PrivacyRemovalSeedResponse } from "../types/privacy";

export function usePrivacyRemovalSeed(
  subjectId: string | null,
  onSeeded: (response: PrivacyRemovalSeedResponse) => void,
) {
  const mutation = useMutation({
    mutationFn: () => {
      if (!subjectId) throw new Error("privacy_subject_required");
      return privacyJson<PrivacyRemovalSeedResponse>(
        `/v1/privacy/subjects/${subjectId}/removal-control/seed`,
        { confirmed_authorization: true },
      );
    },
    onSuccess: onSeeded,
  });

  return {
    result: mutation.data ?? null,
    error: mutation.error,
    isSeeding: mutation.isPending,
    canSeed: Boolean(subjectId) && !mutation.isPending,
    seedSubject: mutation.mutateAsync,
  };
}

export type PrivacyRemovalSeedState = ReturnType<typeof usePrivacyRemovalSeed>;
