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
      <section className={`rounded-xl border ${border} ${panel} p-5`}>
        <div className="flex items-center justify-between gap-3">
          <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>Last intake</h2>
          <button
            type="button"
            onClick={intake.clearLastIntake}
            className={`inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border ${border} ${isDark ? 'hover:bg-white/5' : 'hover:bg-[#141414]/5'}`}
            aria-label="Clear last intake"
          >
            <RotateCcw className="h-4 w-4" />
          </button>
        </div>
        {intake.createdSubject ? (
          <div className="mt-5 space-y-3">
            <StatusLine icon="ok" className={okClass} text="Subject stored" />
            <KeyValue label="Subject ID" value={intake.createdSubject.subject_id} mutedClass={muted} />
            <KeyValue label="Status" value={intake.createdSubject.status} mutedClass={muted} />
            <KeyValue label="Tuples" value={String(intake.createdSubject.identity_tuple_count)} mutedClass={muted} />
            <KeyValue label="Payload key" value={intake.createdSubject.payload_key_version} mutedClass={muted} />
          </div>
        ) : (
          <div className={`mt-5 rounded-lg border px-4 py-5 text-sm ${warnClass}`}>
            No subject selected
          </div>
        )}
      </section>

      <form onSubmit={intake.appendIdentityTuple} className={`rounded-xl border ${border} ${panel} p-5`}>
        <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>Append tuple</h2>
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
              <KeyValue label="Tuple ID" value={intake.appendResult.identity_tuple_id ?? 'duplicate'} mutedClass={muted} />
              <KeyValue label="Digest key" value={intake.appendResult.key_version} mutedClass={muted} />
            </div>
          )}
          <button
            type="submit"
            disabled={!intake.canAppend}
            className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg border border-sky-400/30 bg-sky-500/15 px-4 text-sm font-bold text-sky-300 transition hover:bg-sky-500/25 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {intake.appendLoading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Append identity tuple
          </button>
        </div>
      </form>
    </div>
  )
}
