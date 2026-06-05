export type SubjectRole = 'adult' | 'minor'

export type TupleType = 'email' | 'phone' | 'address' | 'name' | 'full_name' | 'dob'

export type IdentityTupleDraft = {
  id: string
  tuple_type: TupleType
  value: string
  label: string
}

export type SubjectCreateResponse = {
  subject_id: string
  status: string
  identity_tuple_count: number
  payload_key_version: string
}

export type IdentityTupleCreateResponse = {
  subject_id: string
  identity_tuple_id: string | null
  tuple_type: TupleType
  key_version: string
  inserted: boolean
}

export type ProfileFields = {
  legal_name: string
  date_of_birth: string
  address: string
  phone: string
  email: string
  notes: string
  legal_context: string
}

export type SubjectForm = {
  display_label: string
  role: SubjectRole
  jurisdiction: string
  profile: ProfileFields
}

export const TUPLE_TYPES: Array<{ value: TupleType; label: string }> = [
  { value: 'email', label: 'Email' },
  { value: 'phone', label: 'Phone' },
  { value: 'address', label: 'Address' },
  { value: 'full_name', label: 'Full name' },
  { value: 'name', label: 'Name fragment' },
  { value: 'dob', label: 'Date of birth' },
]

export const EMPTY_PROFILE: ProfileFields = {
  legal_name: '',
  date_of_birth: '',
  address: '',
  phone: '',
  email: '',
  notes: '',
  legal_context: '',
}
