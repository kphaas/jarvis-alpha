import { Trash2 } from 'lucide-react'
import { TUPLE_TYPES, type IdentityTupleDraft, type TupleType } from '../../types/privacy'

export function IdentityTupleRow({
  tuple,
  inputClass,
  borderClass,
  canRemove,
  onChange,
  onRemove,
}: {
  tuple: IdentityTupleDraft
  inputClass: string
  borderClass: string
  canRemove: boolean
  onChange: (patch: Partial<IdentityTupleDraft>) => void
  onRemove?: () => void
}) {
  return (
    <div className="grid gap-3 md:grid-cols-[150px_minmax(0,1fr)_minmax(120px,160px)_44px]">
      <select
        value={tuple.tuple_type}
        onChange={(event) => onChange({ tuple_type: event.target.value as TupleType })}
        className={`min-h-11 rounded-lg border px-3 text-sm outline-none transition focus:border-emerald-600 focus-visible:ring-2 focus-visible:ring-emerald-700/25 dark:focus:border-emerald-400 dark:focus-visible:ring-emerald-300/25 ${inputClass}`}
        aria-label="Tuple type"
      >
        {TUPLE_TYPES.map((item) => (
          <option key={item.value} value={item.value}>{item.label}</option>
        ))}
      </select>
      <input
        value={tuple.value}
        onChange={(event) => onChange({ value: event.target.value })}
        className={`min-h-11 rounded-lg border px-3 text-sm outline-none transition focus:border-emerald-600 focus-visible:ring-2 focus-visible:ring-emerald-700/25 dark:focus:border-emerald-400 dark:focus-visible:ring-emerald-300/25 ${inputClass}`}
        placeholder="Value"
        aria-label="Tuple value"
      />
      <input
        value={tuple.label}
        onChange={(event) => onChange({ label: event.target.value })}
        className={`min-h-11 rounded-lg border px-3 text-sm outline-none transition focus:border-emerald-600 focus-visible:ring-2 focus-visible:ring-emerald-700/25 dark:focus:border-emerald-400 dark:focus-visible:ring-emerald-300/25 ${inputClass}`}
        placeholder="Label"
        aria-label="Tuple label"
      />
      <button
        type="button"
        disabled={!canRemove}
        onClick={onRemove}
        className={`inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border ${borderClass} transition disabled:cursor-not-allowed disabled:opacity-25`}
        aria-label="Remove tuple"
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  )
}
