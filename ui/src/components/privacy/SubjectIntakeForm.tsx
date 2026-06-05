import { LoaderCircle, Plus, UserRound } from 'lucide-react'
import { newTuple } from '../../lib/privacyIntake'
import type { usePrivacyIntake } from '../../hooks/usePrivacyIntake'
import { IdentityTupleRow } from './IdentityTupleRow'
import { StatusLine, TextArea, TextInput } from './PrivacyFields'

type IntakeState = ReturnType<typeof usePrivacyIntake>

export function SubjectIntakeForm({
  intake,
  isDark,
  border,
  panel,
  input,
  muted,
  errorClass,
}: {
  intake: IntakeState
  isDark: boolean
  border: string
  panel: string
  input: string
  muted: string
  errorClass: string
}) {
  return (
    <form onSubmit={intake.createSubject} className={`rounded-xl border ${border} ${panel}`}>
      <div className={`grid gap-5 border-b p-5 ${border} md:grid-cols-[1fr_220px_160px]`}>
        <TextInput
          label="Display label"
          value={intake.form.display_label}
          onChange={(value) => intake.setForm((current) => ({ ...current, display_label: value }))}
          inputClass={input}
          mutedClass={muted}
          placeholder="Operator label"
        />
        <div className="space-y-2">
          <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>Role</span>
          <div className={`grid min-h-11 grid-cols-2 overflow-hidden rounded-lg border ${border}`}>
            {(['adult', 'minor'] as const).map((role) => (
              <button
                key={role}
                type="button"
                onClick={() => intake.setForm((current) => ({ ...current, role }))}
                className={`text-sm font-medium capitalize transition-colors ${
                  intake.form.role === role
                    ? 'bg-emerald-500 text-[#0A0A0A]'
                    : isDark ? 'hover:bg-white/5' : 'hover:bg-[#141414]/5'
                }`}
              >
                {role}
              </button>
            ))}
          </div>
        </div>
        <TextInput
          label="Jurisdiction"
          value={intake.form.jurisdiction}
          onChange={(value) => intake.setForm((current) => ({ ...current, jurisdiction: value }))}
          inputClass={input}
          mutedClass={muted}
        />
      </div>

      <div className={`grid gap-4 border-b p-5 ${border} md:grid-cols-2`}>
        <TextInput label="Legal name" value={intake.form.profile.legal_name} onChange={(value) => intake.updateProfile('legal_name', value)} inputClass={input} mutedClass={muted} />
        <TextInput label="Date of birth" value={intake.form.profile.date_of_birth} onChange={(value) => intake.updateProfile('date_of_birth', value)} inputClass={input} mutedClass={muted} placeholder="YYYY-MM-DD" />
        <TextInput label="Email" value={intake.form.profile.email} onChange={(value) => intake.updateProfile('email', value)} inputClass={input} mutedClass={muted} />
        <TextInput label="Phone" value={intake.form.profile.phone} onChange={(value) => intake.updateProfile('phone', value)} inputClass={input} mutedClass={muted} />
        <div className="md:col-span-2">
          <TextInput label="Address" value={intake.form.profile.address} onChange={(value) => intake.updateProfile('address', value)} inputClass={input} mutedClass={muted} />
        </div>
        <TextArea label="Legal context" value={intake.form.profile.legal_context} onChange={(value) => intake.updateProfile('legal_context', value)} inputClass={input} mutedClass={muted} />
        <TextArea label="Notes" value={intake.form.profile.notes} onChange={(value) => intake.updateProfile('notes', value)} inputClass={input} mutedClass={muted} />
      </div>

      <div className="space-y-4 p-5">
        <div className="flex items-center justify-between gap-3">
          <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>Identity tuples</h2>
          <button
            type="button"
            onClick={() => intake.setTuples((current) => [...current, newTuple()])}
            className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm transition ${border} ${isDark ? 'hover:bg-white/5' : 'hover:bg-[#141414]/5'}`}
          >
            <Plus className="h-4 w-4" />
            Add
          </button>
        </div>
        <div className="space-y-3">
          {intake.tuples.map((tuple) => (
            <IdentityTupleRow
              key={tuple.id}
              tuple={tuple}
              inputClass={input}
              borderClass={border}
              canRemove={intake.tuples.length > 1}
              onChange={(patch) => intake.updateTuple(tuple.id, patch)}
              onRemove={() => intake.removeTuple(tuple.id)}
            />
          ))}
        </div>
        {intake.error && <StatusLine icon="error" className={errorClass} text={intake.error} />}
        <div className={`flex flex-col gap-3 border-t pt-5 sm:flex-row sm:items-center sm:justify-between ${border}`}>
          <div className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
            {intake.validTupleCount} tuple{intake.validTupleCount === 1 ? '' : 's'} ready
          </div>
          <button
            type="submit"
            disabled={!intake.canSubmit}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-emerald-500 px-4 text-sm font-bold text-[#0A0A0A] transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {intake.loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <UserRound className="h-4 w-4" />}
            Create subject
          </button>
        </div>
      </div>
    </form>
  )
}
