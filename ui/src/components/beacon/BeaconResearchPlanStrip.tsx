import { AlertTriangle, Compass, Database, FileJson, GitBranch, ListChecks, Quote, Timer } from 'lucide-react'
import type { ReactNode } from 'react'
import type { BeaconEvidenceBundle, BeaconQualitySummary, BeaconResearchPlan, BeaconResearchReport } from '../../types/beacon'

interface Props {
  plan: BeaconResearchPlan
  report: BeaconResearchReport
  quality: BeaconQualitySummary
  evidenceBundle?: BeaconEvidenceBundle
  isDark: boolean
}

export function BeaconResearchPlanStrip({ plan, report, quality, evidenceBundle, isDark }: Props) {
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-white/5' : 'bg-white/50'
  const mutedPanel = isDark ? 'bg-black/20' : 'bg-white/40'
  const warnings = [...report.coverage_warnings, ...report.limitations]
  const citationTarget = Math.max(plan.stop_criteria.min_accepted_citations, 1)
  const citationProgress = Math.min(report.accepted_citation_count, citationTarget)
  const progressLabel = `${citationProgress}/${citationTarget} citations`
  const exportMarkdown =
    report.report_markdown ||
    `# ${report.title}\n\n${report.summary || 'No report summary generated.'}\n`
  const exportHref = `data:text/markdown;charset=utf-8,${encodeURIComponent(exportMarkdown)}`
  const evidenceHref = evidenceBundle
    ? `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(evidenceBundle, null, 2))}`
    : ''
  const bundleRedacted = Boolean(
    evidenceBundle &&
      !evidenceBundle.raw_web_content_included &&
      !evidenceBundle.raw_user_query_included
  )

  return (
    <section className={`rounded-lg border p-4 ${border} ${panel}`}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Deep research cockpit</p>
          <h3 className="mt-1 text-sm font-semibold">Plan, coverage, and source ranking</h3>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded border px-2 py-1 text-[10px] font-mono uppercase ${border}`}>
            Progress {progressLabel}
          </span>
          <a
            href={exportHref}
            download="beacon-research-report.md"
            className={`rounded border px-2 py-1 text-[10px] font-mono uppercase transition hover:opacity-75 ${border}`}
          >
            Export report
          </a>
          {evidenceBundle && (
            <a
              href={evidenceHref}
              download="beacon-evidence-bundle.json"
              className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[10px] font-mono uppercase transition hover:opacity-75 ${border}`}
            >
              <FileJson className="h-3 w-3" />
              Export evidence
            </a>
          )}
          {evidenceBundle && (
            <span className={`rounded border px-2 py-1 text-[10px] font-mono uppercase ${bundleRedacted ? 'text-emerald-500' : 'text-amber-500'} ${border}`}>
              {bundleRedacted ? 'Bundle redacted' : 'Review raw fields'}
            </span>
          )}
          <span className={`rounded border px-2 py-1 text-[10px] font-mono uppercase ${border}`}>
            {report.answerability.replaceAll('_', ' ')}
          </span>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-4">
        <Metric
          icon={<Compass className="h-4 w-4" />}
          label="Intent"
          value={plan.intent.replaceAll('_', ' ')}
        />
        <Metric
          icon={<GitBranch className="h-4 w-4" />}
          label="Provider"
          value={plan.provider_strategy}
          detail={plan.search_providers.join(' > ')}
        />
        <Metric
          icon={<Timer className="h-4 w-4" />}
          label="Coverage"
          value={`${plan.searches.length}/${plan.max_searches} searches`}
          detail={`${plan.max_extracts} extracts`}
        />
        <Metric
          icon={<Database className="h-4 w-4" />}
          label="Report"
          value={report.answerability.replaceAll('_', ' ')}
          detail={`${report.cited_source_count} cited`}
        />
      </div>

      <div className={`mt-4 rounded-lg border p-3 ${border} ${mutedPanel}`}>
        <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest opacity-45">
          <ListChecks className="h-4 w-4" />
          Eval gates
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-4">
          <Metric
            icon={<Database className="h-4 w-4" />}
            label="Official"
            value={`${quality.covered_official_target_count}/${quality.required_official_target_count}`}
          />
          <Metric
            icon={<Quote className="h-4 w-4" />}
            label="Verified"
            value={String(report.verified_claim_count)}
          />
          <Metric
            icon={<AlertTriangle className="h-4 w-4" />}
            label="Unsupported"
            value={String(report.unsupported_claim_count)}
          />
          <Metric
            icon={<AlertTriangle className="h-4 w-4" />}
            label="Warnings"
            value={String(report.coverage_warnings.length)}
          />
        </div>
      </div>

      {evidenceBundle && (
        <div className={`mt-4 rounded-lg border p-3 ${border} ${mutedPanel}`}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Exportable citation bundle</p>
              <p className="mt-1 text-sm font-semibold">
                request {shortId(evidenceBundle.request_id)} · {evidenceBundle.source_hosts.length} hosts
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <span className={`rounded border px-2 py-1 text-[10px] font-mono uppercase ${border}`}>
                raw web {evidenceBundle.raw_web_content_included ? 'yes' : 'no'}
              </span>
              <span className={`rounded border px-2 py-1 text-[10px] font-mono uppercase ${border}`}>
                raw query {evidenceBundle.raw_user_query_included ? 'yes' : 'no'}
              </span>
              <span className={`rounded border px-2 py-1 text-[10px] font-mono uppercase ${border}`}>
                v{evidenceBundle.bundle_version}
              </span>
            </div>
          </div>
          <p className="mt-2 text-xs opacity-60">{evidenceBundle.instruction_boundary}</p>
        </div>
      )}

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <div>
          <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Planned searches</p>
          <div className="mt-2 space-y-2">
            {plan.searches.map((search) => (
              <div key={`${search.purpose}-${search.query}`} className={`rounded-lg border px-3 py-2 ${border}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[10px] font-mono uppercase opacity-55">{search.purpose}</span>
                  {search.required && <span className="text-[10px] font-mono uppercase text-emerald-500">required</span>}
                </div>
                <p className="mt-1 text-sm opacity-80">{search.query}</p>
              </div>
            ))}
          </div>
        </div>

        <div>
          <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Subquestions</p>
          <div className="mt-2 space-y-2">
            {plan.subquestions.slice(0, 5).map((item) => (
              <div key={`${item.purpose}-${item.question}`} className={`rounded-lg border px-3 py-2 ${border}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[10px] font-mono uppercase opacity-55">{item.purpose}</span>
                  {item.required && <span className="text-[10px] font-mono uppercase text-emerald-500">required</span>}
                </div>
                <p className="mt-1 text-sm opacity-80">{item.question}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
        <details className={`rounded-lg border p-3 ${border} ${mutedPanel}`}>
          <summary className="flex cursor-pointer list-none items-center gap-2 text-xs font-semibold">
            <Database className="h-4 w-4" />
            Ranked sources
          </summary>
          <div className="mt-3 space-y-2">
            {report.source_rankings.slice(0, 6).map((source) => (
              <a
                key={`${source.rank}-${source.source_url}`}
                href={source.source_url}
                target="_blank"
                rel="noreferrer"
                className={`block rounded-lg border px-3 py-2 transition hover:opacity-80 ${border}`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[10px] font-mono uppercase opacity-55">rank {source.rank}</span>
                  <span className="text-[10px] font-mono uppercase opacity-55">{source.source_quality.replaceAll('_', ' ')}</span>
                  <span className="text-[10px] font-mono uppercase opacity-55">{source.confidence}</span>
                  <span className="text-[10px] font-mono uppercase opacity-55">score {source.score}</span>
                </div>
                <p className="mt-1 truncate text-sm font-semibold">{source.host}</p>
                {source.reasons.length > 0 && <p className="mt-1 text-xs opacity-55">{source.reasons.slice(0, 2).join(' / ')}</p>}
              </a>
            ))}
            {report.source_rankings.length === 0 && <p className="text-sm opacity-55">No ranked sources yet.</p>}
          </div>
        </details>

        <div className={`rounded-lg border p-3 ${border} ${mutedPanel}`}>
          <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest opacity-45">
            <ListChecks className="h-4 w-4" />
            Stop criteria
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {plan.stop_criteria.stop_when.map((item) => (
              <span key={item} className={`rounded border px-2 py-1 text-xs ${border}`}>
                {item}
              </span>
            ))}
          </div>
          {warnings.length > 0 && (
            <div className="mt-4 space-y-2">
              {warnings.slice(0, 5).map((item) => (
                <p key={item} className="flex gap-2 text-sm text-amber-500">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{item}</span>
                </p>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

interface MetricProps {
  icon: ReactNode
  label: string
  value: string
  detail?: string
}

function Metric({ icon, label, value, detail }: MetricProps) {
  return (
    <div>
      <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest opacity-45">
        {icon}
        {label}
      </div>
      <p className="mt-2 truncate text-sm font-semibold">{value}</p>
      {detail && <p className="mt-1 truncate text-xs opacity-55">{detail}</p>}
    </div>
  )
}

function shortId(value: string): string {
  return value ? value.slice(0, 8) : 'none'
}
