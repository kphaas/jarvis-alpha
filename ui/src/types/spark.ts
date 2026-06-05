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
