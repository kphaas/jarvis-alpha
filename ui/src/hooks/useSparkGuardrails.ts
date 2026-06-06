import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiJson } from '../lib/apiFetch'
import type { SparkGuardrailState } from '../types/spark'

const QUERY_KEY = ['spark', 'guardrails']

export function useSparkGuardrails() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => apiJson<SparkGuardrailState>('/v1/spark/persona/guardrails'),
    staleTime: 60_000,
  })
  const saveMutation = useMutation({
    mutationFn: (state: SparkGuardrailState) =>
      apiJson<SparkGuardrailState>('/v1/spark/persona/guardrails', {
        method: 'PUT',
        body: JSON.stringify(state),
      }),
    onSuccess: (state) => {
      queryClient.setQueryData(QUERY_KEY, state)
    },
  })

  return {
    guardrails: query.data ?? null,
    guardrailsLoading: query.isLoading,
    guardrailsError: query.error,
    saveGuardrails: saveMutation.mutate,
    saveGuardrailsLoading: saveMutation.isPending,
    saveGuardrailsError: saveMutation.error,
    saveGuardrailsResult: saveMutation.data ?? null,
  }
}

export type SparkGuardrailsState = ReturnType<typeof useSparkGuardrails>
