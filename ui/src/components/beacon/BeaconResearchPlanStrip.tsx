import { Compass, Database, GitBranch, Timer } from 'lucide-react'
import type { ReactNode } from 'react'
import type { BeaconResearchPlan, BeaconResearchReport } from '../../types/beacon'

interface Props {
  plan: BeaconResearchPlan
  report: BeaconResearchReport
  isDark: boolean
}

export function BeaconResearchPlanStrip({ plan, report, isDark }: Props) {
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-white/5' : 'bg-white/50'

  return (
    <section className={`rounded-lg border p-4 ${border} ${panel}`}>
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
          <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Stop criteria</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {plan.stop_criteria.stop_when.map((item) => (
              <span key={item} className={`rounded border px-2 py-1 text-xs ${border}`}>
                {item}
              </span>
            ))}
          </div>
          {(report.coverage_warnings.length > 0 || report.limitations.length > 0) && (
            <div className="mt-4 space-y-2">
              {[...report.coverage_warnings, ...report.limitations].slice(0, 5).map((item) => (
                <p key={item} className="text-sm text-amber-500">{item}</p>
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
