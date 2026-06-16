import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "../lib/apiFetch";
import type {
  SparkTargetMemoryApproveRequest,
  SparkTargetMemoryApproveResponse,
  SparkTargetMemoryArchiveRequest,
  SparkTargetMemoryArchiveResponse,
  SparkTargetMemoryProposeRequest,
  SparkTargetMemoryProposeResponse,
  SparkTargetMemoryRejectRequest,
  SparkTargetMemoryRejectResponse,
  SparkTargetMemoryReviewResponse,
} from "../types/spark";

export function useSparkTargetMemory(
  principalId = "ken",
  approvalId: string | null = null,
) {
  const queryClient = useQueryClient();
  const queryKey = ["spark", "target-memory", principalId, approvalId];
  const query = useQuery({
    queryKey,
    queryFn: () => {
      const params = new URLSearchParams({
        principal_id: principalId,
        approval_id: approvalId ?? "",
      });
      return apiJson<SparkTargetMemoryReviewResponse>(
        `/v1/spark/persona/target-memory?${params.toString()}`,
      );
    },
    enabled: Boolean(approvalId),
    staleTime: 30_000,
  });

  const proposeMutation = useMutation({
    mutationFn: (request: SparkTargetMemoryProposeRequest) =>
      apiJson<SparkTargetMemoryProposeResponse>(
        "/v1/spark/persona/target-memory/propose",
        {
          method: "POST",
          body: JSON.stringify(request),
        },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  const approveMutation = useMutation({
    mutationFn: (request: SparkTargetMemoryApproveRequest) =>
      apiJson<SparkTargetMemoryApproveResponse>(
        "/v1/spark/persona/target-memory/approve",
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
    mutationFn: (request: SparkTargetMemoryArchiveRequest) =>
      apiJson<SparkTargetMemoryArchiveResponse>(
        "/v1/spark/persona/target-memory/archive",
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
    mutationFn: (request: SparkTargetMemoryRejectRequest) =>
      apiJson<SparkTargetMemoryRejectResponse>(
        "/v1/spark/persona/target-memory/reject",
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

export type SparkTargetMemoryState = ReturnType<typeof useSparkTargetMemory>;
