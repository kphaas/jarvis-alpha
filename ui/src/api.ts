import type { AskResult, PipelineRow } from './types'

const BASE = '/api'

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText} [${path}]`)
  return res.json()
}

export const getHealth = () => apiFetch<{ status: string; db: string }>('/health')

export const getNodes = () =>
  apiFetch<{ nodes: Record<string, string> }>('/v1/state').then(d => d.nodes)

export const getPipeline = () => apiFetch<PipelineRow[]>('/v1/vault/pipeline')

export const confirmPipeline = (id: string) =>
  apiFetch<{ stage: string; tier: string; archive_path: string }>(
    `/v1/vault/pipeline/${id}/confirm`, { method: 'POST' }
  )

export const askBrain = (payload: {
  prompt: string
  mode: string
  session_id: string
  user_id: string
  workspace_id?: string
  persistent?: boolean
}) =>
  apiFetch<AskResult>('/v1/ask', { method: 'POST', body: JSON.stringify(payload) })

export const getCosts = () => apiFetch<{
  budget: { daily: { spent_usd: number; limit_usd: number; pct_used: number }
            weekly: { spent_usd: number; limit_usd: number; pct_used: number }
            monthly: { spent_usd: number; limit_usd: number; pct_used: number } }
  totals: { all_time_usd: number; all_time_calls: number }
  averages: { daily_avg_usd: number; monthly_avg_usd: number }
  by_provider: { provider: string; calls: number; cost_usd: number }[]
}>('/v1/costs')

export const verifyPin = (pin: string) =>
  apiFetch<{ valid: boolean }>('/v1/pin/verify', {
    method: 'POST', body: JSON.stringify({ pin }),
  }).then(r => r.valid).catch(() => false)
