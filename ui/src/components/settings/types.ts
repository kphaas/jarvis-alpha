export interface ProfilePersonalData {
  profile_id: string
  legal_name?: string | null
  preferred_name?: string | null
  email?: string | null
  phone?: string | null
  birthday?: string | null
  notes?: string | null
  updated_at?: string | null
  updated_by_profile_id?: string | null
  data_classification: 'personal_information'
}

export interface Profile {
  id: string
  display_name: string
  role: 'admin' | 'child'
  child_age?: number | null
  max_rating: 'all_ages' | 'age_8_plus' | 'teen' | 'adult'
  active: boolean
  pin_status: 'set' | 'placeholder'
  personal_data?: ProfilePersonalData | null
}

export interface Relationship {
  id: string
  from_profile_id: string
  to_profile_id: string
  relationship_label: string
  inverse_relationship_label?: string | null
  notes?: string | null
  updated_at?: string | null
  updated_by_profile_id?: string | null
  data_classification: 'personal_information'
}

export interface HomeAddress {
  label: string
  line1?: string | null
  line2?: string | null
  city?: string | null
  region?: string | null
  postal_code?: string | null
  country: string
  updated_at?: string | null
  updated_by_profile_id?: string | null
  data_classification: 'personal_information'
}

export interface IdentitySettings {
  profiles: Profile[]
  relationships: Relationship[]
  personal_data: {
    home_address: HomeAddress | null
    storage_classification: 'alpha_db_personal_settings'
  }
}

export const RATING_LABEL: Record<string, string> = {
  all_ages: 'All Ages',
  age_8_plus: '8+',
  teen: 'Teen',
  adult: 'Adult',
}
