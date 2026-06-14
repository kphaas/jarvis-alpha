import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiJson } from '../lib/apiFetch'
import type {
  SparkPersonalityMemoryApproveRequest,
  SparkPersonalityMemoryApproveResponse,
  SparkPersonalityMemoryReviewResponse,
} from '../types/spark'

const QUERY_KEY = ['spark', 'personality-memory', 'ken']

export function useSparkPersonalityMemory() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () =>
      apiJson<SparkPersonalityMemoryReviewResponse>(
        '/v1/spark/persona/memory?principal_id=ken',
      ),
    staleTime: 60_000,
  })

  const approveMutation = useMutation({
    mutationFn: (request: SparkPersonalityMemoryApproveRequest) =>
      apiJson<SparkPersonalityMemoryApproveResponse>(
        '/v1/spark/persona/memory/approve',
        {
          method: 'POST',
          body: JSON.stringify(request),
        },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY })
    },
  })

  return {
    memory: query.data ?? null,
    memoryLoading: query.isLoading,
    memoryError: query.error,
    refreshMemory: query.refetch,
    approveMemory: approveMutation.mutate,
    approveMemoryLoading: approveMutation.isPending,
    approveMemoryError: approveMutation.error,
    approveMemoryResult: approveMutation.data ?? null,
  }
}

export type SparkPersonalityMemoryState = ReturnType<
  typeof useSparkPersonalityMemory
>
