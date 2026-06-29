import { AlertTriangle, CheckCircle2, FileText, Lock, Quote } from 'lucide-react'
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
  const report = result.research_report
  const findings = report.key_findings.length ? report.key_findings : [report.summary]
  const limitations = [...result.synthesis.limitations, ...report.limitations]

  return (
    <section className={`rounded-lg border p-4 ${border} ${panel}`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-3xl">
          <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Answer workspace</p>
          <div className="mt-2 flex items-center gap-2">
            <Icon className={`h-5 w-5 ${tone}`} />
            <h2 className="text-lg font-semibold leading-6">{report.title || result.synthesis.required_behavior.replaceAll('_', ' ')}</h2>
          </div>
          <p className="mt-2 text-sm leading-6 opacity-80">{report.summary}</p>
          <p className="mt-2 text-xs opacity-55">request {result.request_id.slice(0, 8)}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge label={result.quality.status} tone={result.quality.status} />
          <Badge label={`${result.citations.length} citations`} />
          <Badge label={`${result.quality.official_source_count} official`} />
          <Badge label={result.raw_web_content_is_untrusted ? 'web untrusted' : 'web trusted'} />
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        {findings.slice(0, 3).map((item, index) => (
          <div key={`${index}-${item}`} className={`rounded-lg border p-3 ${border}`}>
            <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest opacity-45">
              <Quote className="h-3.5 w-3.5" />
              finding {index + 1}
            </div>
            <p className="mt-2 text-sm leading-6 opacity-85">{item}</p>
          </div>
        ))}
      </div>

      {result.quality.warnings.length > 0 && (
        <div className="mt-4 space-y-2">
          {result.quality.warnings.slice(0, 4).map((item) => (
            <p key={item} className="flex gap-2 text-sm text-amber-500">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{item}</span>
            </p>
          ))}
        </div>
      )}

      {limitations.length > 0 && (
        <div className="mt-4 space-y-2">
          {limitations.slice(0, 5).map((item) => (
            <p key={item} className="flex gap-2 text-sm text-amber-500">
              <Lock className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{item}</span>
            </p>
          ))}
        </div>
      )}

      {result.answer_context && (
        <details className={`mt-4 rounded-lg border p-3 ${border}`}>
          <summary className="flex cursor-pointer list-none items-center gap-2 text-xs font-semibold">
            <FileText className="h-4 w-4" />
            Evidence prompt context
          </summary>
          <div className={`mt-3 max-h-72 overflow-auto rounded-lg border p-3 font-mono text-xs leading-6 ${border}`}>
            {result.answer_context}
          </div>
        </details>
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
