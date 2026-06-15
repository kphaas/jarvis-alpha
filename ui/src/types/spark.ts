export interface SparkIMessageDraftRequest {
  principal_id: string;
  approval_id?: string | null;
  reply_goal?: string | null;
  max_context_messages: number;
}

export interface SparkIMessageDraftApprovalRequest extends SparkIMessageDraftRequest {
  draft_text_override?: string | null;
}

export type SparkDraftFeedbackLabel =
  | "sounds_like_me"
  | "too_robotic"
  | "too_formal"
  | "too_much_policy";

export interface SparkIMessageDraftFeedbackRequest {
  principal_id: string;
  feedback_label: SparkDraftFeedbackLabel;
  draft_version: string;
  approval_ref_hash: string;
  source_reference_hash: string;
  chat_guid_hash: string;
}

export interface SparkIMessageDraftFeedbackResponse {
  status: string;
  feedback_recorded: boolean;
  feedback_ref_hash?: string | null;
  feedback_label?: SparkDraftFeedbackLabel | null;
}

export interface SparkIMessageDraftResponse {
  draft_version: string;
  principal_id: string;
  draft_text: string;
  can_send: boolean;
  requires_human_approval: boolean;
  body_access: boolean;
  durable_storage_allowed: boolean;
  context_messages_read: number;
  principal_sent_messages: number;
  runtime_context_messages: number;
  approval_ref_hash: string;
  source_reference_hash: string;
  chat_guid_hash: string;
  warnings: string[];
  detected_sensitivity: string[];
  blocked_sensitivity: string[];
  draft_engine: string;
}

export interface SparkIMessageDraftApprovalResponse extends SparkIMessageDraftResponse {
  queue_id: string;
  approval_status: string;
}

export type SparkMode = "draft_only" | "hybrid_review" | "auto_guarded";

export type SparkSensitivity =
  | "relationship"
  | "minor"
  | "family"
  | "legal"
  | "medical"
  | "financial"
  | "security"
  | "custody";

export interface SparkProtectedRelationship {
  id: string;
  label: string;
  relationship: string;
  sensitivity: SparkSensitivity;
  default_mode: SparkMode;
  approval_required: boolean;
  notes?: string | null;
}

export interface SparkPersonaCalibration {
  target_voice: string[];
  avoid_voice: string[];
  signature_phrases: string[];
  response_length: "short" | "short_medium" | "medium";
  uncertainty_policy: string;
  escalation_style: string;
  urgency_policy: string;
}

export interface SparkGuardrailState {
  principal_id: string;
  active_mode: SparkMode;
  auto_send_enabled: boolean;
  protected_topics: SparkSensitivity[];
  protected_relationships: SparkProtectedRelationship[];
  calibration: SparkPersonaCalibration;
  updated_at: string;
}

export type SparkPersonalityMemoryKind =
  | "voice"
  | "avoid"
  | "phrase"
  | "boundary"
  | "relationship"
  | "value"
  | "style"
  | "preference";

export type SparkPersonalityMemorySource =
  | "spark_approved"
  | "spark_feedback"
  | "spark_vault"
  | "buddy_proposal";

export interface SparkPersonalityMemoryItem {
  id: string;
  principal_id: string;
  kind: SparkPersonalityMemoryKind;
  content: string;
  source: SparkPersonalityMemorySource;
  evidence_ref_hash?: string | null;
  importance_score: number;
  approved_by: string;
  approved_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface SparkPersonalityMemoryProposal {
  proposal_id: string;
  principal_id: string;
  kind: SparkPersonalityMemoryKind;
  content: string;
  source: SparkPersonalityMemorySource;
  reason: string;
  confidence: number;
  evidence_ref_hash?: string | null;
}

export interface SparkPersonalityMemoryReviewResponse {
  principal_id: string;
  active: SparkPersonalityMemoryItem[];
  proposals: SparkPersonalityMemoryProposal[];
  buddy: {
    status: string;
    proposal_count: number;
    feedback_phrase_count: number;
  };
}

export interface SparkPersonalityMemoryApproveRequest {
  approved: true;
  proposal_id: string;
  principal_id: string;
  kind: SparkPersonalityMemoryKind;
  content: string;
  source: SparkPersonalityMemorySource;
  evidence_ref_hash?: string | null;
  importance_score: number;
}

export interface SparkPersonalityMemoryApproveResponse {
  status: string;
  result: {
    saved?: boolean;
    reason?: string;
    personality_id?: string;
    principal_id?: string;
    kind?: SparkPersonalityMemoryKind;
    source?: SparkPersonalityMemorySource;
  };
}

export interface SparkPersonalityMemoryArchiveRequest {
  principal_id: string;
  memory_id: string;
}

export interface SparkPersonalityMemoryArchiveResponse {
  status: string;
  result: {
    archived?: boolean;
    reason?: string;
    personality_id?: string;
    principal_id?: string;
  };
}

export interface SparkPersonalityMemoryRejectRequest {
  principal_id: string;
  proposal_id: string;
}

export interface SparkPersonalityMemoryRejectResponse {
  status: string;
  result: {
    rejected?: boolean;
    reason?: string;
    proposal_id?: string;
    principal_id?: string;
    already_rejected?: boolean;
  };
}
