import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  LoaderCircle,
  Plus,
  Save,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { useSparkGuardrails } from '../../hooks/useSparkGuardrails'
import type {
  SparkGuardrailState,
  SparkMode,
  SparkProtectedRelationship,
  SparkSensitivity,
} from '../../types/spark'

const TOPICS: SparkSensitivity[] = [
  'legal',
  'medical',
  'custody',
  'minor',
  'relationship',
  'financial',
  'security',
]

const MODES: SparkMode[] = ['draft_only', 'hybrid_review', 'auto_guarded']

function cloneState(state: SparkGuardrailState): SparkGuardrailState {
  return JSON.parse(JSON.stringify(state)) as SparkGuardrailState
}

function listToText(values: string[]) {
  return values.join(', ')
}

function textToList(value: string) {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function labelize(value: string) {
  return value.replace(/_/g, ' ')
}

interface StyleProps {
  border: string
  panel: string
  input: string
  muted: string
  okClass: string
  warnClass: string
  errorClass: string
}

export function SparkGuardrailsPanel({
  border,
  panel,
  input,
  muted,
  okClass,
  warnClass,
  errorClass,
}: StyleProps) {
  const state = useSparkGuardrails()

  if (state.guardrailsLoading) {
    return (
      <section className={`rounded-xl border ${border} ${panel} p-5`}>
        <div className="flex min-h-32 items-center justify-center gap-2 text-sm opacity-60">
          <LoaderCircle className="h-4 w-4 animate-spin" />
          Loading guardrails
        </div>
      </section>
    )
  }

  if (state.guardrailsError || !state.guardrails) {
    return (
      <section className={`rounded-xl border ${border} ${panel} p-5`}>
        <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${errorClass}`}>
          <AlertTriangle className="h-4 w-4 shrink-0" />
          Guardrails unavailable
        </div>
      </section>
    )
  }

  return (
    <SparkGuardrailsEditor
      key={state.guardrails.updated_at}
      initial={state.guardrails}
      state={state}
      border={border}
      panel={panel}
      input={input}
      muted={muted}
      okClass={okClass}
      warnClass={warnClass}
      errorClass={errorClass}
    />
  )
}

interface EditorProps extends StyleProps {
  initial: SparkGuardrailState
  state: ReturnType<typeof useSparkGuardrails>
}

function SparkGuardrailsEditor({
  initial,
  state,
  border,
  panel,
  input,
  muted,
  okClass,
  warnClass,
  errorClass,
}: EditorProps) {
  const [draft, setDraft] = useState<SparkGuardrailState>(() => cloneState(initial))

  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(initial), [draft, initial])

  function patch(patchValue: Partial<SparkGuardrailState>) {
    setDraft((current) => ({ ...current, ...patchValue }))
  }

  function patchCalibration(key: keyof SparkGuardrailState['calibration'], value: string | string[]) {
    setDraft((current) => ({
      ...current,
      calibration: {
        ...current.calibration,
        [key]: value,
      },
    }))
  }

  function toggleTopic(topic: SparkSensitivity) {
    const next = draft.protected_topics.includes(topic)
      ? draft.protected_topics.filter((item) => item !== topic)
      : [...draft.protected_topics, topic]
    patch({ protected_topics: next.length ? next : draft.protected_topics })
  }

  function patchRelationship(id: string, patchValue: Partial<SparkProtectedRelationship>) {
    setDraft((current) => ({
      ...current,
      protected_relationships: current.protected_relationships.map((item) =>
        item.id === id ? { ...item, ...patchValue } : item,
      ),
    }))
  }

  function addRelationship() {
    const relationship: SparkProtectedRelationship = {
      id: `relationship-${Date.now()}`,
      label: 'New relationship',
      relationship: 'relationship',
      sensitivity: 'relationship',
      default_mode: 'draft_only',
      approval_required: true,
      notes: null,
    }
    setDraft((current) => ({
      ...current,
      protected_relationships: [...current.protected_relationships, relationship],
    }))
  }

  function removeRelationship(id: string) {
    setDraft((current) => {
      if (current.protected_relationships.length === 1) return current
      return {
        ...current,
        protected_relationships: current.protected_relationships.filter((item) => item.id !== id),
      }
    })
  }

  function save() {
    if (!dirty || state.saveGuardrailsLoading) return
    state.saveGuardrails(draft)
  }

  return (
    <section className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-emerald-400" />
          <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>Guardrails</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${warnClass}`}>
            no auto send
          </span>
          <button
            type="button"
            onClick={save}
            disabled={!dirty || state.saveGuardrailsLoading}
            className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-bold transition ${border} ${
              dirty ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300' : 'opacity-45'
            }`}
          >
            {state.saveGuardrailsLoading ? (
              <LoaderCircle className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Save
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <div className="space-y-4">
          <label className="block">
            <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
              Mode
            </span>
            <select
              value={draft.active_mode}
              onChange={(event) => patch({ active_mode: event.target.value as SparkMode })}
              className={`mt-2 h-11 w-full rounded-lg border px-3 text-sm ${input}`}
            >
              {MODES.map((mode) => (
                <option key={mode} value={mode}>
                  {labelize(mode)}
                </option>
              ))}
            </select>
          </label>

          <div>
            <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
              Topics
            </span>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {TOPICS.map((topic) => (
                <label
                  key={topic}
                  className={`flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm ${border}`}
                >
                  <input
                    type="checkbox"
                    checked={draft.protected_topics.includes(topic)}
                    onChange={() => toggleTopic(topic)}
                  />
                  <span>{labelize(topic)}</span>
                </label>
              ))}
            </div>
          </div>

          <div className={`rounded-lg border p-3 text-xs ${okClass}`}>
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4" />
              <span className="font-semibold">auto_send_enabled: false</span>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
              Relationships
            </span>
            <button
              type="button"
              onClick={addRelationship}
              className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-xs font-bold ${border}`}
            >
              <Plus className="h-4 w-4" />
              Add
            </button>
          </div>

          <div className="space-y-3">
            {draft.protected_relationships.map((relationship) => (
              <div key={relationship.id} className={`rounded-lg border p-3 ${border}`}>
                <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_160px_160px]">
                  <label className="block">
                    <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
                      Label
                    </span>
                    <input
                      value={relationship.label}
                      onChange={(event) =>
                        patchRelationship(relationship.id, {
                          label: event.target.value,
                        })
                      }
                      className={`mt-1 h-11 w-full rounded-lg border px-3 text-sm ${input}`}
                    />
                  </label>
                  <label className="block">
                    <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
                      Sensitivity
                    </span>
                    <select
                      value={relationship.sensitivity}
                      onChange={(event) =>
                        patchRelationship(relationship.id, {
                          sensitivity: event.target.value as SparkSensitivity,
                        })
                      }
                      className={`mt-1 h-11 w-full rounded-lg border px-3 text-sm ${input}`}
                    >
                      {TOPICS.concat('family').map((topic) => (
                        <option key={topic} value={topic}>
                          {labelize(topic)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
                      Default
                    </span>
                    <select
                      value={relationship.default_mode}
                      onChange={(event) =>
                        patchRelationship(relationship.id, {
                          default_mode: event.target.value as SparkMode,
                        })
                      }
                      className={`mt-1 h-11 w-full rounded-lg border px-3 text-sm ${input}`}
                    >
                      {MODES.map((mode) => (
                        <option key={mode} value={mode}>
                          {labelize(mode)}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="mt-3 grid gap-3 lg:grid-cols-[160px_minmax(0,1fr)_auto]">
                  <label className="block">
                    <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
                      Relation
                    </span>
                    <input
                      value={relationship.relationship}
                      onChange={(event) =>
                        patchRelationship(relationship.id, { relationship: event.target.value })
                      }
                      className={`mt-1 h-11 w-full rounded-lg border px-3 text-sm ${input}`}
                    />
                  </label>
                  <label className="block">
                    <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
                      Notes
                    </span>
                    <input
                      value={relationship.notes ?? ''}
                      onChange={(event) =>
                        patchRelationship(relationship.id, { notes: event.target.value || null })
                      }
                      className={`mt-1 h-11 w-full rounded-lg border px-3 text-sm ${input}`}
                    />
                  </label>
                  <div className="flex items-end gap-2">
                    <label className={`flex min-h-11 items-center gap-2 rounded-lg border px-3 text-xs ${border}`}>
                      <input
                        type="checkbox"
                        checked={relationship.approval_required}
                        onChange={(event) =>
                          patchRelationship(relationship.id, {
                            approval_required: event.target.checked,
                          })
                        }
                      />
                      Approval
                    </label>
                    <button
                      type="button"
                      onClick={() => removeRelationship(relationship.id)}
                      disabled={draft.protected_relationships.length === 1}
                      className={`inline-flex min-h-11 items-center rounded-lg border px-3 transition ${border} disabled:opacity-40`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className={`mt-4 grid gap-3 rounded-lg border p-3 ${border}`}>
        <label className="block">
          <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
            Target voice
          </span>
          <input
            value={listToText(draft.calibration.target_voice)}
            onChange={(event) => patchCalibration('target_voice', textToList(event.target.value))}
            className={`mt-1 h-11 w-full rounded-lg border px-3 text-sm ${input}`}
          />
        </label>
        <label className="block">
          <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
            Avoid voice
          </span>
          <input
            value={listToText(draft.calibration.avoid_voice)}
            onChange={(event) => patchCalibration('avoid_voice', textToList(event.target.value))}
            className={`mt-1 h-11 w-full rounded-lg border px-3 text-sm ${input}`}
          />
        </label>
        <label className="block">
          <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
            Signature phrases
          </span>
          <input
            value={listToText(draft.calibration.signature_phrases)}
            onChange={(event) => patchCalibration('signature_phrases', textToList(event.target.value))}
            className={`mt-1 h-11 w-full rounded-lg border px-3 text-sm ${input}`}
          />
        </label>
        {state.saveGuardrailsError && (
          <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${errorClass}`}>
            <AlertTriangle className="h-4 w-4 shrink-0" />
            Save failed
          </div>
        )}
        {state.saveGuardrailsResult && !dirty && (
          <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${okClass}`}>
            <CheckCircle2 className="h-4 w-4 shrink-0" />
            Guardrails saved
          </div>
        )}
      </div>
    </section>
  )
}
