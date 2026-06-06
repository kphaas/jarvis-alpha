export interface SparkIMessageDraftRequest {
  principal_id: string
  approval_id?: string | null
  reply_goal?: string | null
  max_context_messages: number
}

export interface SparkIMessageDraftApprovalRequest extends SparkIMessageDraftRequest {
  draft_text_override?: string | null
}

export interface SparkIMessageDraftResponse {
  draft_version: string
  principal_id: string
  draft_text: string
  can_send: boolean
  requires_human_approval: boolean
  body_access: boolean
  durable_storage_allowed: boolean
  context_messages_read: number
  principal_sent_messages: number
  runtime_context_messages: number
  approval_ref_hash: string
  source_reference_hash: string
  chat_guid_hash: string
  warnings: string[]
}

export interface SparkIMessageDraftApprovalResponse extends SparkIMessageDraftResponse {
  queue_id: string
  approval_status: string
}

export type SparkMode = 'draft_only' | 'hybrid_review' | 'auto_guarded'

export type SparkSensitivity =
  | 'relationship'
  | 'minor'
  | 'family'
  | 'legal'
  | 'medical'
  | 'financial'
  | 'security'
  | 'custody'

export interface SparkProtectedRelationship {
  id: string
  label: string
  relationship: string
  sensitivity: SparkSensitivity
  default_mode: SparkMode
  approval_required: boolean
  notes?: string | null
}

export interface SparkPersonaCalibration {
  target_voice: string[]
  avoid_voice: string[]
  signature_phrases: string[]
  response_length: 'short' | 'short_medium' | 'medium'
  uncertainty_policy: string
  escalation_style: string
  urgency_policy: string
}

export interface SparkGuardrailState {
  principal_id: string
  active_mode: SparkMode
  auto_send_enabled: boolean
  protected_topics: SparkSensitivity[]
  protected_relationships: SparkProtectedRelationship[]
  calibration: SparkPersonaCalibration
  updated_at: string
}
