export type Theme = 'light' | 'dark'

export interface NodeHealth {
  id: string
  name: string
  status: 'ok' | 'error' | 'pending'
  latency_ms: number | null
}

export interface PipelineRow {
  id: string
  filename: string
  content_type: string
  stage: string
  size_bytes: number
  created_at: string
}

export interface AskResult {
  mode: string
  result: string
  refined_prompt?: string
  claude_response?: string
  gemini_response?: string
  synthesis?: string
  steps_completed?: number
  error?: string
}
