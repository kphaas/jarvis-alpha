export interface JwtCheck {
  total: number
  passing: number
  failing: number
  checks: {
    route: string
    expected: number
    actual: number
    pass: boolean
    type: string
  }[]
}

export interface RlsStatus {
  total_tables: number
  rls_enabled: number
  rls_disabled: number
  force_rls_enabled?: number
  force_rls_disabled?: number
  protected_tables?: number
  tables: {
    table: string
    rls: string
    force_rls?: string
    policy: string
    policy_count?: number
    protected?: boolean
  }[]
}

export interface ChildProfile {
  name: string
  age: number
  app_layer: boolean
  db_layer: boolean
  content_filter: boolean
  notes: string
}

export interface ChildProfileStatus {
  profiles: ChildProfile[]
  overall: string
  recommendation: string
}

export interface PortCheck {
  node: string
  port: number
  service: string
  reachable: boolean
  expected: boolean
}

export interface Perimeter {
  cors: { allowed_origins: string[]; locked: boolean }
  ports: PortCheck[]
  tailscale: { active: boolean; node_count: number }
}

export interface CertRow {
  node: string
  domain: string
  expires: string
  days_remaining: number
  status: string
  source: string
}

export interface LogEntry {
  ts: string
  level: string
  service: string
  node: string
  message: string
}

export interface LogsQueryResponse {
  status: string
  entries?: LogEntry[]
}

export interface RotatableKey {
  key_name: string
  provider: string
  prefix: string
  min_length: number
}

export interface RotationResult {
  status: string
  rotation_id: string
  key_name: string
  error: string | null
  old_key_health: string | null
  new_key_health: string | null
  approval_queue_id?: string | null
  approval_status?: string | null
}

export interface SecretAuditEvent {
  key: string
  source: string
  accessed_at: string
  node: string
}

export interface SecretsAuditResponse {
  total_events: number
  unique_keys?: number
  events: SecretAuditEvent[]
  error?: string
}

export interface HoneypotEvent {
  ts: string
  path: string
  trap_type: string
  client_ip: string
  user_agent: string
  method: string
}

export interface HoneypotData {
  total: number
  events: HoneypotEvent[]
  traps_active: number
  traps: string[]
}

export interface McpServer {
  name: string
  id: string
  endpoint: string
  status: string
  permissions: string[]
  backlog_ref: string
  description: string
}

export interface McpRegistry {
  total: number
  active: number
  planned: number
  servers: McpServer[]
}

export interface PorchlightCheck {
  name: string
  status: "pass" | "warn" | "fail" | string
  severity: "info" | "low" | "medium" | "high" | "critical" | string
  summary: string
  detail?: string
  metadata?: Record<string, unknown>
}

export interface PorchlightReport {
  agent: string
  generated_at: string
  status: "pass" | "warn" | "fail" | string
  severity: "info" | "low" | "medium" | "high" | "critical" | string
  counts: {
    checks: number
    failing: number
    warning: number
    passing: number
  }
  checks: PorchlightCheck[]
}

export interface PorchlightResponse {
  report_path: string
  report: PorchlightReport
}

export interface AgentManualRunResponse {
  agent_id: string
  executed: boolean
  run_id: string | null
  status: string | null
  trace_id: string | null
  skipped_reason: string | null
  error_text: string | null
}

export interface KeyturnerSecret {
  secret_name: string
  description: string
  secret_class: string
  rotation_days: number
  requires_approval: boolean
  status: "healthy" | "due_soon" | "due" | "failed" | "untracked" | string
  last_rotated_at: string | null
  next_due_at: string | null
  days_until_due: number | null
  verify_status: string | null
}

export interface KeyturnerStatus {
  agent_id: string
  display_name: string
  mode: string
  counts: {
    managed: number
    healthy: number
    attention: number
    approval_gated: number
  }
  secrets: KeyturnerSecret[]
}
