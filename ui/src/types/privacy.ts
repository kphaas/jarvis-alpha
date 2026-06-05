export type SubjectRole = "adult" | "minor";

export type TupleType =
  | "email"
  | "phone"
  | "address"
  | "name"
  | "full_name"
  | "dob";

export type IdentityTupleDraft = {
  id: string;
  tuple_type: TupleType;
  value: string;
  label: string;
};

export type SubjectCreateResponse = {
  subject_id: string;
  status: string;
  identity_tuple_count: number;
  payload_key_version: string;
};

export type IdentityTupleCreateResponse = {
  subject_id: string;
  identity_tuple_id: string | null;
  tuple_type: TupleType;
  key_version: string;
  inserted: boolean;
};

export type PrivacyTargetCategory =
  | "data_broker"
  | "social"
  | "public_record"
  | "breach_db";

export type PrivacyTargetMethod =
  | "email"
  | "web_form"
  | "api"
  | "manual_only"
  | "court_motion";

export type PrivacyTarget = {
  id: string;
  name: string;
  category: PrivacyTargetCategory;
  jurisdiction: string;
  opt_out_method: PrivacyTargetMethod;
  opt_out_url: string | null;
  contact_email: string | null;
  supports_minors: boolean;
  requires_sensitive_payload: boolean;
  requires_identity_document: boolean;
  avg_response_days: number | null;
  last_verified: string | null;
  notes: string | null;
  yaml_source: string;
  loaded_at: string | null;
};

export type PrivacyTargetsResponse = {
  count: number;
  targets: PrivacyTarget[];
};

export type PrivacyTargetsRefreshResponse = {
  count: number;
  source_label: string;
};

export type TargetReviewPacket = {
  target_id: string;
  target_name: string;
  category: PrivacyTargetCategory;
  jurisdiction: string;
  opt_out_method: PrivacyTargetMethod;
  approval_tier: string;
  approval_reason: string;
  legal_basis: string;
  required_identifiers: string[];
  available_identity_tuple_types: string[];
  evidence_checklist: string[];
  risk_flags: string[];
};

export type DraftAction = {
  action_id: string;
  target_id: string;
  approval_tier: string;
  status: string;
};

export type CaseDraftCreateResponse = {
  case_id: string;
  subject_id: string;
  status: string;
  target_count: number;
  action_count: number;
  payload_key_version: string;
  review_packets: TargetReviewPacket[];
  actions: DraftAction[];
};

export type CaseDraftSummary = {
  case_id: string;
  subject_id: string;
  status: string;
  target_count: number;
  action_count: number;
  highest_approval_tier: string | null;
  payload_key_version: string;
  created_at: string | null;
  updated_at: string | null;
};

export type CaseDraftListResponse = {
  count: number;
  drafts: CaseDraftSummary[];
};

export type CaseDraftDetailResponse = CaseDraftSummary & {
  review_packets: TargetReviewPacket[];
  actions: DraftAction[];
};

export type ProfileFields = {
  legal_name: string;
  date_of_birth: string;
  address: string;
  phone: string;
  email: string;
  notes: string;
  legal_context: string;
};

export type SubjectForm = {
  display_label: string;
  role: SubjectRole;
  jurisdiction: string;
  profile: ProfileFields;
};

export const TUPLE_TYPES: Array<{ value: TupleType; label: string }> = [
  { value: "email", label: "Email" },
  { value: "phone", label: "Phone" },
  { value: "address", label: "Address" },
  { value: "full_name", label: "Full name" },
  { value: "name", label: "Name fragment" },
  { value: "dob", label: "Date of birth" },
];

export const TARGET_CATEGORIES: Array<{
  value: PrivacyTargetCategory;
  label: string;
}> = [
  { value: "data_broker", label: "Brokers" },
  { value: "public_record", label: "Records" },
  { value: "social", label: "Social" },
  { value: "breach_db", label: "Breach" },
];

export const TARGET_METHOD_LABEL: Record<PrivacyTargetMethod, string> = {
  email: "Email",
  web_form: "Web form",
  api: "API",
  manual_only: "Manual",
  court_motion: "Court",
};

export const EMPTY_PROFILE: ProfileFields = {
  legal_name: "",
  date_of_birth: "",
  address: "",
  phone: "",
  email: "",
  notes: "",
  legal_context: "",
};
