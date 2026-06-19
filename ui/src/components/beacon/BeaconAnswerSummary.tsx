import { AlertTriangle, CheckCircle2, Lock } from 'lucide-react'
import type { BeaconAnswerResponse } from '../../types/beacon'

interface Props {
  result: BeaconAnswerResponse
  isDark: boolean
}

export function BeaconAnswerSummary({ result, isDark }: Props) {
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-white/5' : 'bg-white/50'
  const supported = result.synthesis.answerable
  const Icon = supported ? CheckCircle2 : AlertTriangle
  const tone = supported ? 'text-emerald-500' : 'text-amber-500'

  return (
    <section className={`rounded-lg border p-4 ${border} ${panel}`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Answer contract</p>
          <div className="mt-2 flex items-center gap-2">
            <Icon className={`h-5 w-5 ${tone}`} />
            <h2 className="text-lg font-semibold">{result.synthesis.required_behavior.replaceAll('_', ' ')}</h2>
          </div>
          <p className="mt-1 text-xs opacity-55">request {result.request_id.slice(0, 8)}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge label={result.quality.status} tone={result.quality.status} />
          <Badge label={`${result.citations.length} citations`} />
          <Badge label={result.raw_web_content_is_untrusted ? 'web untrusted' : 'web trusted'} />
        </div>
      </div>

      {result.answer_context && (
        <div className={`mt-4 max-h-72 overflow-auto rounded-lg border p-3 font-mono text-xs leading-6 ${border}`}>
          {result.answer_context}
        </div>
      )}

      {result.synthesis.limitations.length > 0 && (
        <div className="mt-4 space-y-2">
          {result.synthesis.limitations.slice(0, 5).map((item) => (
            <p key={item} className="flex gap-2 text-sm text-amber-500">
              <Lock className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{item}</span>
            </p>
          ))}
        </div>
      )}
    </section>
  )
}

function Badge({ label, tone }: { label: string; tone?: string }) {
  const toneClass = tone === 'supported'
    ? 'border-emerald-500/30 text-emerald-500'
    : tone === 'weak'
      ? 'border-amber-500/30 text-amber-500'
      : tone === 'insufficient'
        ? 'border-rose-500/30 text-rose-500'
        : 'border-white/10 opacity-65'
  return (
    <span className={`rounded border px-2 py-1 text-[10px] font-mono uppercase tracking-widest ${toneClass}`}>
      {label}
    </span>
  )
}
