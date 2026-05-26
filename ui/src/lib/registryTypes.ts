export interface SkillRuntimeManifest {
  timeout_s: number
  retry_policy: string
  rate_limit: string
}

export interface SkillCostManifest {
  mode: string
  max_usd_per_call: number
  model_policy: string | null
}

export interface SkillEgressManifest {
  mode: string
  provider: string | null
  allowed_hosts: string[]
}

export interface SkillAuditManifest {
  event_name: string
  redact_fields: string[]
}

export interface SkillManifest {
  manifest_version: 1
  data_classification: string
  side_effect_class: string
  input_schema_ref: string
  output_schema_ref: string
  runtime: SkillRuntimeManifest
  cost: SkillCostManifest
  egress: SkillEgressManifest
  audit: SkillAuditManifest
  compensation: string
  test_ref: string
  runbook_ref: string
}

export interface Skill {
  name: string
  domain: string
  action: string
  description: string
  approval_tier: string
  scope: string
  status: string
  mutates_state: boolean
  body_access: boolean
  idempotency_required: boolean
  owner: string
  manifest: SkillManifest | null
  metadata: Record<string, unknown>
}

export interface SkillList {
  count: number
  skills: Skill[]
}

export interface Agent {
  agent_id: string
  display_name: string
  purpose: string
  risk_tier: string
  status: string
  enabled: boolean
  owner: string
  cadence: string | null
  launch_label: string | null
  allowed_skills: string[]
  allowed_scopes: string[]
  cost_daily_cap_usd: number | null
  model_policy: Record<string, unknown>
  approval_policy: Record<string, unknown>
  metadata: Record<string, unknown>
}

export interface AgentList {
  count: number
  agents: Agent[]
}

export function compactJson(value: Record<string, unknown>): string {
  const entries = Object.entries(value)
  if (!entries.length) return 'None'
  return entries.map(([key, val]) => {
    const rendered =
      val && typeof val === 'object' ? JSON.stringify(val) : String(val)
    return `${key}: ${rendered}`
  }).join(' / ')
}

export function uniqueSorted(values: string[]): string[] {
  return Array.from(new Set(values)).sort((a, b) => a.localeCompare(b))
}
