export interface SparkIMessageDraftRequest {
  principal_id: string;
  approval_id?: string | null;
  reply_goal?: string | null;
  max_context_messages: number;
  include_context_preview?: boolean;
  context_preview_limit?: number;
  include_memory_preview?: boolean;
}

export interface SparkIMessageDraftTarget {
  approval_id: string;
  label: string;
  channel: string;
  thread_kind: string;
  relationship_marked: boolean;
  relationship_approved: boolean;
  legal_marked: boolean;
}

export interface SparkIMessageDraftTargetsResponse {
  principal_id: string;
  targets: SparkIMessageDraftTarget[];
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

export interface SparkIMessageDraftContextMessage {
  index: number;
  speaker: string;
  is_from_me: boolean;
  message_ref_hash: string;
  body_text: string;
}

export interface SparkIMessageDraftMemoryDebugItem {
  kind: string;
  content: string;
  source: string;
  evidence_ref_hash?: string | null;
}

export interface SparkIMessageDraftConversationSummary {
  channel: string;
  voice_principal_label: string;
  reply_target_label: string;
  reply_target_confidence: string;
  context_order: string;
  last_message_speaker?: string | null;
  last_message_preview?: string | null;
  last_message_ref_hash?: string | null;
}

export interface SparkIMessageDraftQualityCheck {
  key: string;
  label: string;
  passed: boolean;
  detail: string;
}

export interface SparkIMessageDraftQuality {
  score: number;
  verdict: "strong" | "review" | "needs_edit" | string;
  checks: SparkIMessageDraftQualityCheck[];
}

export interface SparkIMessageDraftSourceReadiness {
  source: string;
  channel: string;
  status: string;
  detail: string;
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
  conversation_summary: SparkIMessageDraftConversationSummary;
  draft_quality: SparkIMessageDraftQuality;
  source_readiness: SparkIMessageDraftSourceReadiness[];
  context_preview: SparkIMessageDraftContextMessage[];
  personality_memory_preview: SparkIMessageDraftMemoryDebugItem[];
}

export interface SparkIMessageDraftApprovalResponse extends SparkIMessageDraftResponse {
  queue_id: string;
  approval_status: string;
  outbox_id?: string | null;
  outbox_status?: string | null;
  outbox_text_hash?: string | null;
  outbox_recorded: boolean;
  voice_feedback_recorded: boolean;
  voice_feedback_ref_hash?: string | null;
  candidate_key_phrases: string[];
  calibration_lessons: string[];
}

export interface SparkIMessageApprovedSendResponse {
  outbox_id: string;
  outbox_status: string;
  approval_queue_id: string;
  approval_status: string;
  message_ref_hash?: string | null;
  send_attempt_count: number;
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
  scorecard?: SparkPersonalityMemoryScorecard;
  buddy: {
    status: string;
    proposal_count: number;
    feedback_phrase_count: number;
    feedback_lesson_count: number;
  };
}

export interface SparkPersonalityMemoryScorecard {
  active_count: number;
  proposal_count: number;
  feedback_phrase_count: number;
  feedback_lesson_count: number;
  kinds_present: string[];
  missing_core_kinds: string[];
  readiness: "strong" | "needs_review" | "thin";
}

export interface SparkPersonalityMemoryProposeRequest {
  principal_id: string;
  note: string;
}

export interface SparkPersonalityMemoryProposeResponse {
  status: string;
  proposal?: SparkPersonalityMemoryProposal | null;
  reason?: string | null;
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
