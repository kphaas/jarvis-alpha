import { useCallback, useEffect, useState } from 'react'
import { apiJson } from '../../lib/apiFetch'
import type { IdentitySettings } from './types'

export function useIdentitySettings(errorMessage = 'Failed to load identity settings') {
  const [identity, setIdentity] = useState<IdentitySettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setIdentity(await apiJson<IdentitySettings>('/v1/settings/identity'))
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : errorMessage)
    } finally {
      setLoading(false)
    }
  }, [errorMessage])

  useEffect(() => {
    void load()
  }, [load])

  return { identity, loading, error, reload: load }
}
