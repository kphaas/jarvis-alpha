import { useQuery } from '@tanstack/react-query'
import { apiJson } from '../lib/apiFetch'
import type {
  BudgetRow,
  CostsSummary,
  HardwarePayload,
  OutcomeRow,
  PerplexityPayload,
  PowerPayload,
  SubscriptionRow,
} from '../types/costs'

export function useCostsSummary() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['costs', 'summary'],
    queryFn: () => apiJson<CostsSummary>('/v1/costs/summary'),
    staleTime: 5 * 60 * 1000,
  })
  return { data, isLoading, error, refetch }
}

export function useCostsPower() {
  return useQuery({
    queryKey: ['costs', 'power'],
    queryFn: async () => {
      const [power, hardware] = await Promise.all([
        apiJson<PowerPayload>('/v1/costs/power'),
        apiJson<HardwarePayload>('/v1/costs/hardware'),
      ])
      return { power, hardware }
    },
    staleTime: 5 * 60 * 1000,
  })
}

export function useCostsSubscriptions() {
  return useQuery({
    queryKey: ['costs', 'subscriptions'],
    queryFn: () => apiJson<SubscriptionRow[]>('/v1/costs/subscriptions'),
    staleTime: 5 * 60 * 1000,
  })
}

export function useCostsOutcomes() {
  return useQuery({
    queryKey: ['costs', 'outcomes'],
    queryFn: () => apiJson<OutcomeRow[]>('/v1/costs/outcomes'),
    staleTime: 5 * 60 * 1000,
  })
}

export function useCostsBudget() {
  return useQuery({
    queryKey: ['costs', 'budget'],
    queryFn: () => apiJson<BudgetRow[]>('/v1/costs/budget'),
    staleTime: 5 * 60 * 1000,
  })
}

export function useCostsPerplexity() {
  return useQuery({
    queryKey: ['costs', 'perplexity'],
    queryFn: () => apiJson<PerplexityPayload>('/v1/costs/perplexity'),
    staleTime: 5 * 60 * 1000,
  })
}

export function usePowerLive() {
  return useQuery({
    queryKey: ['metrics', 'power', 'current'],
    queryFn: () => apiJson<any>('/v1/metrics/power/current').catch(() => null),
    staleTime: 30 * 1000,
    refetchInterval: 30 * 1000,
  })
}
