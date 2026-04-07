import { useQuery } from '@tanstack/react-query'
import { apiJson } from '../lib/apiFetch'

export interface BriefingSummary {
  pass: number
  fail: number
  skip: number
  total_cost_usd: number
  per_batch_usd?: number
  duration_seconds?: number
  budget_utilization_pct?: number
}

export interface BriefingResult {
  feature_id: string
  outcome: string
  outcome_display: string
  cost_usd: number
  iterations_used: number
  iterations_max?: number
  duration_seconds: number
  error_message?: string
}

export interface BriefingFull {
  id: number
  batch_run_id: string
  briefing_date: string
  started_at: string
  source: string
  summary: BriefingSummary
  results: BriefingResult[]
  markdown: string | null
  created_at: string
}

export function useLatestBriefing() {
  return useQuery<BriefingFull | null>({
    queryKey: ['briefings', 'latest'],
    queryFn: async () => {
      try {
        return await apiJson<BriefingFull>('/v1/briefings/latest')
      } catch (err: unknown) {
        // 404 = no briefings yet, return null instead of throwing.
        if (err instanceof Error && err.message === 'HTTP 404') return null
        throw err
      }
    },
    staleTime: 60 * 1000,
  })
}

export function useBriefingByBatchRunId(batchRunId: string | undefined) {
  return useQuery<BriefingFull | null>({
    queryKey: ['briefings', 'detail', batchRunId],
    queryFn: async () => {
      if (!batchRunId) return null
      try {
        return await apiJson<BriefingFull>(`/v1/briefings/${batchRunId}`)
      } catch (err: unknown) {
        if (err instanceof Error && err.message === 'HTTP 404') return null
        throw err
      }
    },
    enabled: !!batchRunId,
    staleTime: 60 * 1000,
  })
}
