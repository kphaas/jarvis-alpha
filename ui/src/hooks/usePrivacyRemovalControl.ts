import { useQuery } from '@tanstack/react-query'
import { privacyGetJson } from '../lib/privacyIntake'
import type { PrivacyRemovalControlSummaryResponse } from '../types/privacy'

export function usePrivacyRemovalControl() {
  const query = useQuery({
    queryKey: ['privacy', 'removal-control'],
    queryFn: () =>
      privacyGetJson<PrivacyRemovalControlSummaryResponse>(
        '/v1/privacy/removal-control/summary',
      ),
    staleTime: 60 * 1000,
  })

  return {
    summary: query.data ?? null,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refreshSummary: query.refetch,
  }
}

export type PrivacyRemovalControlState = ReturnType<
  typeof usePrivacyRemovalControl
>
