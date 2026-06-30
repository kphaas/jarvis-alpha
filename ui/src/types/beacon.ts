export type BeaconFocusMode =
  | 'all'
  | 'official'
  | 'news_current'
  | 'shopping'
  | 'academic'
  | 'local_weather'
  | 'deep_research'

export interface BeaconMode {
  key: BeaconFocusMode
  label: string
  description: string
}

export interface BeaconHealthCheck {
  ok: boolean
  status: 'ok' | 'warning' | 'degraded' | 'unavailable'
  detail: string
  metadata?: Record<string, unknown>
}

export interface BeaconRetentionReport {
  mode: string
  evidence_retention_days: number
  screenshot_retention_days: number
  old_request_count: number
  screenshot_file_count: number
  screenshot_bytes: number
}

export interface BeaconHealthPayload {
  status: 'ok' | 'degraded'
  checks: Record<string, BeaconHealthCheck>
  retention: BeaconRetentionReport
  checked_at: string
}

export interface BeaconResearchQuery {
  query: string
  purpose: string
  required: boolean
}

export interface BeaconResearchSubquestion {
  question: string
  purpose: string
  required: boolean
  expected_source_types: string[]
}

export interface BeaconResearchStopCriteria {
  min_accepted_citations: number
  min_source_hosts: number
  require_official_source: boolean
  require_cross_check: boolean
  max_searches: number
  max_extracts: number
  stop_when: string[]
}

export interface BeaconResearchPlan {
  plan_id: string
  intent: string
  searches: BeaconResearchQuery[]
  subquestions: BeaconResearchSubquestion[]
  expected_source_types: string[]
  authority_required: boolean
  freshness_required: boolean
  primary_source_required: boolean
  max_searches: number
  provider_strategy: string
  search_providers: string[]
  max_extracts: number
  stop_criteria: BeaconResearchStopCriteria
  notes: string[]
}

export interface BeaconCitation {
  claim?: string | null
  source_url: string
  host: string
  content_hash: string
  citation_text: string
  confidence: 'low' | 'medium' | 'high'
  source_quality: string
  quality_reasons: string[]
  source_rank?: number | null
  source_score: number
}

export interface BeaconQualitySummary {
  status: 'supported' | 'weak' | 'insufficient'
  accepted_citation_count: number
  rejected_citation_count: number
  official_source_count: number
  required_official_target_count: number
  covered_official_target_count: number
  verified_claim_count: number
  unsupported_claim_count: number
  prompt_injection_rejection_count: number
  official_source_required: boolean
  required_source_hosts: string[]
  warnings: string[]
}

export interface BeaconEvidenceTransparencyItem {
  source_url: string
  host: string
  content_hash: string
  citation_text: string
  claim?: string | null
  accepted: boolean
  rejection_reasons: string[]
  confidence: 'low' | 'medium' | 'high'
  source_quality: string
  source_rank?: number | null
  source_score: number
  quality_reasons: string[]
  claim_supported: boolean
  claim_support_reasons: string[]
  official_source_required: boolean
  official_host_match: boolean
  freshness_required: boolean
  fetched_at?: string | null
}

export interface BeaconAnswerQualityScore {
  score: number
  label: 'strong' | 'solid' | 'limited' | 'low'
  source_diversity_score: number
  official_coverage_score: number
  freshness_score: number
  rejected_risk_score: number
  accepted_source_count: number
  source_host_count: number
  rejected_risk_count: number
  summary: string
  warnings: string[]
}

export interface BeaconEvidenceTransparency {
  accepted_sources: BeaconEvidenceTransparencyItem[]
  rejected_sources: BeaconEvidenceTransparencyItem[]
  official_source_required: boolean
  required_source_hosts: string[]
  freshness_required: boolean
  answer_quality_score?: BeaconAnswerQualityScore
}

export interface BeaconSynthesis {
  answerable: boolean
  status: 'supported' | 'weak' | 'insufficient'
  citation_count: number
  minimum_citations_met: boolean
  required_behavior: string
  must_cite_sources: boolean
  limitations: string[]
}

export interface BeaconResearchReport {
  answerability: 'answerable' | 'limited' | 'not_verified'
  title: string
  summary: string
  key_findings: string[]
  limitations: string[]
  cited_source_count: number
  accepted_citation_count: number
  rejected_citation_count: number
  source_hosts: string[]
  verified_claim_count: number
  unsupported_claim_count: number
  source_diversity_score: number
  coverage_warnings: string[]
  verified_claims: string[]
  unsupported_claims: string[]
  report_markdown: string
  source_rankings: Array<{
    rank: number
    source_url: string
    host: string
    source_quality: string
    confidence: 'low' | 'medium' | 'high'
    score: number
    reasons: string[]
  }>
}

export interface BeaconAnswerResponse {
  request_id: string
  plan: {
    selected_tool: string
    execution_enabled: boolean
    notes: string[]
    research: BeaconResearchPlan
  }
  citations: BeaconCitation[]
  quality: BeaconQualitySummary
  synthesis: BeaconSynthesis
  research_report: BeaconResearchReport
  evidence_transparency?: BeaconEvidenceTransparency
  answer_context: string
  raw_web_content_is_untrusted: boolean
}

export interface BeaconBrowserApprovalResponse {
  request_id: string
  approval_queue_id: string
  approval_status: 'pending'
  preview: {
    approval_hash_prefix: string
    allowed_hosts: string[]
    click_targets?: Array<{
      selector: string
      label?: string | null
      expected_host?: string | null
    }>
  }
}
