export interface CostsSummary {
  subscriptions_monthly_usd?: number
  credit: { balance_usd: number; spent_usd: number; pending_usd: number }
  perplexity?: { balance_usd: number; spent_usd: number }
  power_monthly_usd: number
  hardware_monthly_usd?: number
  true_monthly_tco: number
  forge_monthly_usd: number
  api: {
    anthropic: { total_usd: number; jarvis_core_usd?: number; jarvis_forge_usd?: number }
    gemini: { total_usd: number; source?: string }
    perplexity_mtd_usd?: number
  }
  budget?: Array<{ provider: string; monthly_limit_usd: number; mtd_usd: number; pct_used: number }>
  outcomes?: Array<{ session_type: string | null; run_count: number; avg_usd: number }>
  savings_vs_cloud_usd?: number
  local_routing_pct?: number
  generated_at: string
}

export interface BudgetRow {
  provider: string
  monthly_limit_usd: number
  mtd_usd: number
  remaining_usd: number
  pct_used: number
}

export interface OutcomeRow {
  session_type: string | null
  run_count: number
  total_usd: number
  avg_usd: number
}

export interface SubscriptionRow {
  id: string
  name: string
  url: string | null
  cost_usd: number
  billing: string
  next_renewal: string
  days_until_renewal: number
}

export interface PowerNode {
  name: string
  watts: number
  kwh_monthly: number
  cost_monthly: number
}

export interface PowerPayload {
  rate_per_kwh: number
  nodes: PowerNode[]
  total_watts: number
  total_cost_monthly: number
}

export interface HardwareNode {
  node_name: string
  cost_usd: number
  years: number
  monthly_usd: number
}

export interface HardwarePayload {
  nodes: HardwareNode[]
  total_monthly_usd: number
}

export interface PerplexityPayload {
  balance_usd: number
  spent_usd: number
  updated_at: string | null
}

export function fmtMoney(n: number) {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}
