import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "../lib/apiFetch";
import type {
  SparkPersonalityMemoryApproveRequest,
  SparkPersonalityMemoryApproveResponse,
  SparkPersonalityMemoryArchiveRequest,
  SparkPersonalityMemoryArchiveResponse,
  SparkPersonalityMemoryProposeRequest,
  SparkPersonalityMemoryProposeResponse,
  SparkPersonalityMemoryRejectRequest,
  SparkPersonalityMemoryRejectResponse,
  SparkPersonalityMemoryReviewResponse,
} from "../types/spark";

export function useSparkPersonalityMemory(principalId = "ken") {
  const queryClient = useQueryClient();
  const queryKey = ["spark", "personality-memory", principalId];
  const query = useQuery({
    queryKey,
    queryFn: () =>
      apiJson<SparkPersonalityMemoryReviewResponse>(
        `/v1/spark/persona/memory?principal_id=${encodeURIComponent(principalId)}`,
      ),
    staleTime: 60_000,
  });

  const proposeMutation = useMutation({
    mutationFn: (request: SparkPersonalityMemoryProposeRequest) =>
      apiJson<SparkPersonalityMemoryProposeResponse>(
        "/v1/spark/persona/memory/propose",
        {
          method: "POST",
          body: JSON.stringify(request),
        },
      ),
  });

  const approveMutation = useMutation({
    mutationFn: (request: SparkPersonalityMemoryApproveRequest) =>
      apiJson<SparkPersonalityMemoryApproveResponse>(
        "/v1/spark/persona/memory/approve",
        {
          method: "POST",
          body: JSON.stringify(request),
        },
      ),
    onSuccess: () => {
      proposeMutation.reset();
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  const archiveMutation = useMutation({
    mutationFn: (request: SparkPersonalityMemoryArchiveRequest) =>
      apiJson<SparkPersonalityMemoryArchiveResponse>(
        "/v1/spark/persona/memory/archive",
        {
          method: "POST",
          body: JSON.stringify(request),
        },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  const rejectMutation = useMutation({
    mutationFn: (request: SparkPersonalityMemoryRejectRequest) =>
      apiJson<SparkPersonalityMemoryRejectResponse>(
        "/v1/spark/persona/memory/reject",
        {
          method: "POST",
          body: JSON.stringify(request),
        },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  return {
    memory: query.data ?? null,
    memoryLoading: query.isLoading,
    memoryError: query.error,
    refreshMemory: query.refetch,
    proposeMemory: proposeMutation.mutate,
    proposeMemoryLoading: proposeMutation.isPending,
    proposeMemoryError: proposeMutation.error,
    proposeMemoryResult: proposeMutation.data ?? null,
    clearProposedMemory: proposeMutation.reset,
    approveMemory: approveMutation.mutate,
    approveMemoryLoading: approveMutation.isPending,
    approveMemoryError: approveMutation.error,
    approveMemoryResult: approveMutation.data ?? null,
    archiveMemory: archiveMutation.mutate,
    archiveMemoryLoading: archiveMutation.isPending,
    archiveMemoryError: archiveMutation.error,
    archiveMemoryResult: archiveMutation.data ?? null,
    rejectMemory: rejectMutation.mutate,
    rejectMemoryLoading: rejectMutation.isPending,
    rejectMemoryError: rejectMutation.error,
    rejectMemoryResult: rejectMutation.data ?? null,
  };
}

export type SparkPersonalityMemoryState = ReturnType<
  typeof useSparkPersonalityMemory
>;
