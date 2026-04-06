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
  tables: { table: string; rls: string; policy: string }[]
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
