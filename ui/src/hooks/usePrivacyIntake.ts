import { useMemo, useState, type FormEvent } from 'react'
import {
  compactPayload,
  newSubjectForm,
  newTuple,
  privacyJson,
  tuplePayload,
} from '../lib/privacyIntake'
import type {
  IdentityTupleCreateResponse,
  IdentityTupleDraft,
  ProfileFields,
  SubjectCreateResponse,
  SubjectForm,
} from '../types/privacy'

export function usePrivacyIntake() {
  const [form, setForm] = useState<SubjectForm>(() => newSubjectForm())
  const [tuples, setTuples] = useState<IdentityTupleDraft[]>(() => [newTuple()])
  const [createdSubject, setCreatedSubject] = useState<SubjectCreateResponse | null>(null)
  const [appendTuple, setAppendTuple] = useState<IdentityTupleDraft>(() => newTuple('phone'))
  const [appendResult, setAppendResult] = useState<IdentityTupleCreateResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [appendLoading, setAppendLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [appendError, setAppendError] = useState<string | null>(null)

  const validTupleCount = useMemo(
    () => tuples.filter((tuple) => tuple.value.trim().length > 0).length,
    [tuples],
  )
  const canSubmit = form.display_label.trim().length > 0 && validTupleCount > 0 && !loading
  const canAppend = Boolean(createdSubject) && appendTuple.value.trim().length > 0 && !appendLoading

  function updateProfile(key: keyof ProfileFields, value: string) {
    setForm((current) => ({
      ...current,
      profile: { ...current.profile, [key]: value },
    }))
  }

  function updateTuple(id: string, patch: Partial<IdentityTupleDraft>) {
    setTuples((current) => current.map((tuple) => (tuple.id === id ? { ...tuple, ...patch } : tuple)))
  }

  function removeTuple(id: string) {
    setTuples((current) => current.length === 1 ? current : current.filter((tuple) => tuple.id !== id))
  }

  async function createSubject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSubmit) return

    setLoading(true)
    setError(null)
    setAppendResult(null)
    setAppendError(null)
    try {
      const response = await privacyJson<SubjectCreateResponse>('/v1/privacy/subjects', {
        display_label: form.display_label.trim(),
        role: form.role,
        jurisdiction: form.jurisdiction.trim() || 'US_GA',
        payload: compactPayload(form.profile),
        identity_tuples: tuples.filter((tuple) => tuple.value.trim()).map(tuplePayload),
      })
      setCreatedSubject(response)
      setForm(newSubjectForm())
      setTuples([newTuple()])
      setAppendTuple(newTuple('phone'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'privacy_intake_failed')
    } finally {
      setLoading(false)
    }
  }

  async function appendIdentityTuple(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!createdSubject || !canAppend) return

    setAppendLoading(true)
    setAppendError(null)
    setAppendResult(null)
    try {
      const response = await privacyJson<IdentityTupleCreateResponse>(
        `/v1/privacy/subjects/${createdSubject.subject_id}/identity-tuples`,
        tuplePayload(appendTuple),
      )
      setAppendResult(response)
      setAppendTuple(newTuple('phone'))
    } catch (caught) {
      setAppendError(caught instanceof Error ? caught.message : 'privacy_tuple_append_failed')
    } finally {
      setAppendLoading(false)
    }
  }

  function clearLastIntake() {
    setCreatedSubject(null)
    setAppendResult(null)
    setAppendError(null)
    setError(null)
  }

  return {
    form,
    setForm,
    tuples,
    setTuples,
    createdSubject,
    appendTuple,
    setAppendTuple,
    appendResult,
    loading,
    appendLoading,
    error,
    appendError,
    validTupleCount,
    canSubmit,
    canAppend,
    updateProfile,
    updateTuple,
    removeTuple,
    createSubject,
    appendIdentityTuple,
    clearLastIntake,
  }
}
