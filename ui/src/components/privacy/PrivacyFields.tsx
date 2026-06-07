import { AlertTriangle, CheckCircle2 } from 'lucide-react'

export function TextInput({
  label,
  value,
  onChange,
  inputClass,
  mutedClass,
  placeholder,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  inputClass: string
  mutedClass: string
  placeholder?: string
}) {
  return (
    <label className="space-y-2">
      <span className={`text-xs font-medium ${mutedClass}`}>{label}</span>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className={`min-h-11 w-full rounded-lg border px-3 text-sm outline-none transition focus:border-emerald-600 focus-visible:ring-2 focus-visible:ring-emerald-700/25 dark:focus:border-emerald-400 dark:focus-visible:ring-emerald-300/25 ${inputClass}`}
      />
    </label>
  )
}

export function TextArea({
  label,
  value,
  onChange,
  inputClass,
  mutedClass,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  inputClass: string
  mutedClass: string
}) {
  return (
    <label className="space-y-2">
      <span className={`text-xs font-medium ${mutedClass}`}>{label}</span>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={`min-h-24 w-full resize-y rounded-lg border px-3 py-2 text-sm outline-none transition focus:border-emerald-600 focus-visible:ring-2 focus-visible:ring-emerald-700/25 dark:focus:border-emerald-400 dark:focus-visible:ring-emerald-300/25 ${inputClass}`}
      />
    </label>
  )
}

export function KeyValue({ label, value, mutedClass }: { label: string; value: string; mutedClass: string }) {
  return (
    <div className="space-y-1">
      <div className={`text-[10px] font-mono uppercase tracking-widest ${mutedClass}`}>{label}</div>
      <div className="break-all text-sm font-mono">{value}</div>
    </div>
  )
}

export function StatusLine({
  icon,
  className,
  text,
}: {
  icon: 'ok' | 'error'
  className: string
  text: string
}) {
  const Icon = icon === 'ok' ? CheckCircle2 : AlertTriangle
  return (
    <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${className}`}>
      <Icon className="h-4 w-4 shrink-0" />
      <span className="min-w-0 break-words">{text}</span>
    </div>
  )
}
