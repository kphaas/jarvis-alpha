export interface HomeLocation {
  label: string
  postal_code?: string | null
  city?: string | null
  region?: string | null
  country: string
  latitude: number
  longitude: number
  updated_at?: string | null
  updated_by_profile_id?: string | null
  data_classification: 'personal_information'
}

export interface WebAgentSettings {
  home_location: HomeLocation | null
  storage_classification: 'alpha_db_personal_settings'
}

export interface WebAgentLocationFormState {
  label: string
  postal_code: string
  city: string
  region: string
  country: string
  latitude: string
  longitude: string
}

export const EMPTY_WEB_AGENT_LOCATION_FORM: WebAgentLocationFormState = {
  label: 'Home',
  postal_code: '',
  city: '',
  region: '',
  country: 'US',
  latitude: '',
  longitude: '',
}

export function toWebAgentLocationForm(location: HomeLocation | null): WebAgentLocationFormState {
  if (!location) return EMPTY_WEB_AGENT_LOCATION_FORM
  return {
    label: location.label,
    postal_code: location.postal_code ?? '',
    city: location.city ?? '',
    region: location.region ?? '',
    country: location.country,
    latitude: String(location.latitude),
    longitude: String(location.longitude),
  }
}
