import { LoaderCircle, Plus, RotateCcw } from 'lucide-react'
import type { usePrivacyIntake } from '../../hooks/usePrivacyIntake'
import { IdentityTupleRow } from './IdentityTupleRow'
import { KeyValue, StatusLine } from './PrivacyFields'

type IntakeState = ReturnType<typeof usePrivacyIntake>

export function PrivacyResultPanel({
  intake,
  border,
  panel,
  input,
  muted,
  isDark,
  okClass,
  warnClass,
  errorClass,
}: {
  intake: IntakeState
  border: string
  panel: string
  input: string
  muted: string
  isDark: boolean
  okClass: string
  warnClass: string
  errorClass: string
}) {
  return (
    <div className="space-y-6">
      <section id="privacy-subject-status" className={`rounded-xl border ${border} ${panel} p-5`}>
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold">Subject status</h2>
            <p className={`mt-1 text-sm leading-6 ${muted}`}>
              Current encrypted subject record for this workflow.
            </p>
          </div>
          <button
            type="button"
            onClick={intake.clearLastIntake}
            className={`inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border transition hover:border-emerald-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:hover:border-emerald-300/50 dark:focus-visible:outline-emerald-300 ${border} ${isDark ? 'hover:bg-white/5' : 'hover:bg-[#141414]/5'}`}
            aria-label="Clear last intake"
          >
            <RotateCcw className="h-4 w-4" />
          </button>
        </div>
        {intake.createdSubject ? (
          <div className="mt-5 space-y-3">
            <StatusLine icon="ok" className={okClass} text="Subject stored" />
            <div className={`grid gap-3 rounded-lg border p-3 sm:grid-cols-2 ${border}`}>
              <KeyValue label="Status" value={intake.createdSubject.status} mutedClass={muted} />
              <KeyValue label="Identity values" value={String(intake.createdSubject.identity_tuple_count)} mutedClass={muted} />
            </div>
            <details className={`rounded-lg border ${border}`}>
              <summary className={`cursor-pointer px-3 py-2 text-sm font-medium ${muted}`}>
                Audit details
              </summary>
              <div className={`grid gap-3 border-t p-3 ${border}`}>
                <KeyValue label="Subject ID" value={intake.createdSubject.subject_id} mutedClass={muted} />
                <KeyValue label="Payload key" value={intake.createdSubject.payload_key_version} mutedClass={muted} />
              </div>
            </details>
          </div>
        ) : (
          <div className={`mt-5 rounded-lg border px-4 py-5 text-sm ${warnClass}`}>
            Create a subject to unlock target drafting.
          </div>
        )}
      </section>

      <form onSubmit={intake.appendIdentityTuple} className={`rounded-xl border ${border} ${panel} p-5`}>
        <h2 className="text-base font-semibold">Add identity value</h2>
        <p className={`mt-1 text-sm leading-6 ${muted}`}>
          Add one more matching value without recreating the subject.
        </p>
        <div className="mt-4 space-y-3">
          <IdentityTupleRow
            tuple={intake.appendTuple}
            inputClass={input}
            borderClass={border}
            canRemove={false}
            onChange={(patch) => intake.setAppendTuple((current) => ({ ...current, ...patch }))}
          />
          {intake.appendError && <StatusLine icon="error" className={errorClass} text={intake.appendError} />}
          {intake.appendResult && (
            <div className="space-y-3">
              <StatusLine
                icon="ok"
                className={intake.appendResult.inserted ? okClass : warnClass}
                text={intake.appendResult.inserted ? 'Tuple inserted' : 'Tuple already present'}
              />
              <details className={`rounded-lg border ${border}`}>
                <summary className={`cursor-pointer px-3 py-2 text-sm font-medium ${muted}`}>
                  Audit details
                </summary>
                <div className={`grid gap-3 border-t p-3 ${border}`}>
                  <KeyValue label="Tuple ID" value={intake.appendResult.identity_tuple_id ?? 'duplicate'} mutedClass={muted} />
                  <KeyValue label="Digest key" value={intake.appendResult.key_version} mutedClass={muted} />
                </div>
              </details>
            </div>
          )}
          <button
            type="submit"
            disabled={!intake.canAppend}
            className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg border border-emerald-700/30 bg-emerald-500/15 px-4 text-sm font-bold text-emerald-800 transition hover:bg-emerald-500/25 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 disabled:cursor-not-allowed disabled:opacity-40 dark:border-emerald-400/30 dark:text-emerald-200 dark:focus-visible:outline-emerald-300"
          >
            {intake.appendLoading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Add identity value
          </button>
        </div>
      </form>
    </div>
  )
}
