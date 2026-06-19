import type { HomeAddress, ProfilePersonalData } from './types'

export const EMPTY_ADDRESS = {
  label: 'Home',
  line1: '',
  line2: '',
  city: '',
  region: '',
  postal_code: '',
  country: 'US',
}

export const EMPTY_CONTACT = {
  legal_name: '',
  preferred_name: '',
  email: '',
  phone: '',
  birthday: '',
  notes: '',
}

export type ContactFormDraft = typeof EMPTY_CONTACT

export function toAddressForm(address: HomeAddress | null | undefined) {
  if (!address) return EMPTY_ADDRESS
  return {
    label: address.label,
    line1: address.line1 ?? '',
    line2: address.line2 ?? '',
    city: address.city ?? '',
    region: address.region ?? '',
    postal_code: address.postal_code ?? '',
    country: address.country,
  }
}

export function toContactForm(data: ProfilePersonalData | null | undefined) {
  if (!data) return EMPTY_CONTACT
  return {
    legal_name: data.legal_name ?? '',
    preferred_name: data.preferred_name ?? '',
    email: data.email ?? '',
    phone: data.phone ?? '',
    birthday: data.birthday ?? '',
    notes: data.notes ?? '',
  }
}
