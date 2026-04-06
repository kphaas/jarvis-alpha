export interface ErrorLogEntry {
  ts_ns: string
  node: string
  raw: string
  ts: string
  level: string
  service: string
  trace_id: string
  message: string
}

export interface QueryResponse {
  status: string
  count?: number
  entries?: ErrorLogEntry[]
  error?: string
}

export interface DiagnoseResponse {
  status?: string
  provider?: string
  diagnosis?: string
}

export interface LlmPatternRow {
  severity?: string
  title?: string
  count?: number
  nodes?: string[]
  root_cause?: string
  fix?: string
  related_to?: string | null
}

export interface PatternAnalysisPayload {
  patterns?: LlmPatternRow[]
  summary?: string
}

export interface AnalyzePatternsApiResponse {
  status: string
  error?: string
  pattern_count?: number
  raw_log_count?: number
  analysis?: PatternAnalysisPayload
}

export type PatternPanelState =
  | null
  | { phase: 'loading'; startedAt: Date }
  | { phase: 'error'; at: Date; message: string }
  | { phase: 'done'; at: Date; data: AnalyzePatternsApiResponse }
