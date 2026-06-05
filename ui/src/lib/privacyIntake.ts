import { apiFetch } from './apiFetch'
import type {
  IdentityTupleDraft,
  ProfileFields,
  SubjectForm,
  TupleType,
} from '../types/privacy'
import { EMPTY_PROFILE } from '../types/privacy'

export function newTuple(tuple_type: TupleType = 'email'): IdentityTupleDraft {
  return {
    id: crypto.randomUUID(),
    tuple_type,
    value: '',
    label: '',
  }
}

export function newSubjectForm(): SubjectForm {
  return {
    display_label: '',
    role: 'adult',
    jurisdiction: 'US_GA',
    profile: { ...EMPTY_PROFILE },
  }
}

export async function privacyJson<T>(path: string, body: object): Promise<T> {
  const response = await apiFetch(path, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  const payload = (await response.json().catch(() => ({}))) as {
    detail?: unknown
  }
  if (!response.ok) {
    const detail = typeof payload.detail === 'string' ? payload.detail : `HTTP ${response.status}`
    throw new Error(detail)
  }
  return payload as T
}

export async function privacyGetJson<T>(path: string): Promise<T> {
  const response = await apiFetch(path)
  const payload = (await response.json().catch(() => ({}))) as {
    detail?: unknown
  }
  if (!response.ok) {
    const detail = typeof payload.detail === 'string' ? payload.detail : `HTTP ${response.status}`
    throw new Error(detail)
  }
  return payload as T
}

export function compactPayload(profile: ProfileFields): Record<string, string | boolean> {
  const payload: Record<string, string | boolean> = {
    intake_source: 'alpha_privacy_ui_p2c',
    synthetic: false,
  }
  for (const [key, value] of Object.entries(profile)) {
    const trimmed = value.trim()
    if (trimmed) payload[key] = trimmed
  }
  return payload
}

export function tuplePayload(tuple: IdentityTupleDraft) {
  return {
    tuple_type: tuple.tuple_type,
    value: tuple.value.trim(),
    label: tuple.label.trim() || undefined,
  }
}
