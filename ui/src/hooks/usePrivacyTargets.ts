import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { privacyGetJson, privacyJson } from '../lib/privacyIntake'
import type {
  PrivacyTarget,
  PrivacyTargetsRefreshResponse,
  PrivacyTargetsResponse,
} from '../types/privacy'

export function usePrivacyTargets() {
  const queryClient = useQueryClient()
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const query = useQuery({
    queryKey: ['privacy', 'targets'],
    queryFn: () => privacyGetJson<PrivacyTargetsResponse>('/v1/privacy/targets'),
    staleTime: 5 * 60 * 1000,
  })
  const refreshMutation = useMutation({
    mutationFn: () => privacyJson<PrivacyTargetsRefreshResponse>('/v1/privacy/targets/refresh', {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['privacy', 'targets'] }),
  })
  const targetData = query.data
  const targets = useMemo(() => targetData?.targets ?? [], [targetData])
  const selectedTargets = useMemo(
    () => targets.filter((target) => selectedIds.includes(target.id)),
    [selectedIds, targets],
  )

  function toggleTarget(target: PrivacyTarget) {
    setSelectedIds((current) => (
      current.includes(target.id)
        ? current.filter((id) => id !== target.id)
        : [...current, target.id]
    ))
  }

  function clearSelection() {
    setSelectedIds([])
  }

  return {
    targets,
    selectedIds,
    selectedTargets,
    selectedCount: selectedIds.length,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refreshError: refreshMutation.error,
    refreshResult: refreshMutation.data,
    refreshLoading: refreshMutation.isPending,
    refetch: query.refetch,
    refreshTargets: refreshMutation.mutate,
    toggleTarget,
    clearSelection,
  }
}

export type PrivacyTargetsState = ReturnType<typeof usePrivacyTargets>
