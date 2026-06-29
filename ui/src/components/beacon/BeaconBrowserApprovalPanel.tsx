import {
  AlertTriangle,
  Clock,
  Globe2,
  MousePointerClick,
  ShieldCheck,
  ShieldX,
} from 'lucide-react'

interface BeaconScreenshotPolicy {
  before_navigation_required?: boolean
  after_observation_required?: boolean
  screenshots_available_after_run?: boolean
  screenshot_refs_redacted_until_execution?: boolean
  [key: string]: unknown
}

interface BeaconActionTimelineItem {
  step?: string
  status?: string
  description?: string
  allowed_host_count?: number
  [key: string]: unknown
}

export interface BeaconApprovalContext {
  kind: string
  approval_contract_version?: number
  request_id?: string | null
  selected_tool: string
  risk_tier: string
  sensitivity: string
  requires_human_approval: boolean
  has_query: boolean
  url_count: number
  max_pages: number
  max_depth: number
  needs_interaction: boolean
  allowed_hosts?: string[]
  url_hashes?: string[]
  same_host_required: boolean
  screenshots_required: boolean
  screenshot_policy?: BeaconScreenshotPolicy
  downloads_allowed: boolean
  forms_allowed: boolean
  credential_entry_allowed?: boolean
  risk_labels?: string[]
  action_timeline?: BeaconActionTimelineItem[]
  raw_task_text_included: boolean
  raw_web_content_is_untrusted: boolean
  approval_hash_prefix: string
}

function humanizeBeaconValue(value: string | null | undefined): string {
  if (!value?.trim()) return 'not set'
  return value.replace(/_/g, ' ')
}

function shortEvidenceHash(hash: string): string {
  const [prefix, value] = hash.split(':', 2)
  if (prefix && value) {
    return `${prefix}:${value.slice(0, 12)}`
  }
  return hash.slice(0, 18)
}

function policyBoolLabel(value: unknown, yes: string, no: string): string {
  if (value === true) return yes
  if (value === false) return no
  return 'not reported'
}

export function BeaconBrowserApprovalPanel({
  beacon,
  isDark,
}: {
  beacon: BeaconApprovalContext
  isDark: boolean
}) {
  const allowedHosts = beacon.allowed_hosts ?? []
  const urlHashes = beacon.url_hashes ?? []
  const riskLabels = beacon.risk_labels ?? []
  const actionTimeline = beacon.action_timeline ?? []
  const screenshotPolicy = beacon.screenshot_policy ?? {}
  const card = isDark ? 'bg-black/25 border-white/10' : 'bg-white/70 border-[#141414]/10'
  const chip = isDark
    ? 'bg-cyan-500/10 border-cyan-400/25 text-cyan-100'
    : 'bg-cyan-50 border-cyan-300 text-cyan-900'
  const muted = isDark ? 'text-white/55' : 'text-[#141414]/55'

  const capabilityRows = [
    ['Downloads', beacon.downloads_allowed ? 'allowed' : 'blocked'],
    ['Forms', beacon.forms_allowed ? 'allowed' : 'blocked'],
    ['Credential entry', beacon.credential_entry_allowed ? 'allowed' : 'blocked'],
    ['Cross-host navigation', beacon.same_host_required ? 'blocked' : 'allowed'],
  ]

  const screenshotRows = [
    ['Required', beacon.screenshots_required ? 'yes' : 'no'],
    [
      'Before navigation',
      policyBoolLabel(
        screenshotPolicy.before_navigation_required,
        'required',
        'not required'
      ),
    ],
    [
      'After observation',
      policyBoolLabel(
        screenshotPolicy.after_observation_required,
        'required',
        'not required'
      ),
    ],
    [
      'Available after run',
      policyBoolLabel(
        screenshotPolicy.screenshots_available_after_run,
        'yes',
        'no'
      ),
    ],
    [
      'Refs',
      policyBoolLabel(
        screenshotPolicy.screenshot_refs_redacted_until_execution,
        'redacted until execution',
        'not redacted'
      ),
    ],
  ]

  return (
    <div className={`rounded-xl border p-3 space-y-3 ${card}`}>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-start gap-2">
          <MousePointerClick className="w-4 h-4 mt-0.5 shrink-0 text-cyan-400" />
          <div>
            <div className="text-xs font-bold">Beacon browser approval</div>
            <div className={`text-[11px] ${muted}`}>
              {humanizeBeaconValue(beacon.selected_tool)}
              {' · '}contract v{beacon.approval_contract_version ?? 1}
              {' · '}risk {beacon.risk_tier}
              {' · '}sensitivity {humanizeBeaconValue(beacon.sensitivity)}
            </div>
          </div>
        </div>
        <div className={`text-[10px] font-mono ${muted}`}>
          hash {beacon.approval_hash_prefix}
          {beacon.request_id ? ` · request ${beacon.request_id.slice(0, 8)}` : ''}
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className={`rounded-lg border p-3 space-y-2 ${card}`}>
          <div className="flex items-center gap-1.5 text-[11px] font-bold">
            <Globe2 className="w-3.5 h-3.5 text-cyan-400" />
            Host allowlist
          </div>
          <div className="flex flex-wrap gap-1.5">
            {allowedHosts.length > 0 ? allowedHosts.map((host) => (
              <span key={host} className={`rounded-md border px-2 py-1 text-[10px] font-mono ${chip}`}>
                {host}
              </span>
            )) : (
              <span className={`text-[11px] ${muted}`}>No host allowlist shown</span>
            )}
          </div>
          <div className={`text-[11px] ${muted}`}>
            URLs {beacon.url_count} · query {beacon.has_query ? 'yes' : 'no'} · max pages {beacon.max_pages} · depth {beacon.max_depth}
          </div>
          {urlHashes.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              <span className={`text-[11px] ${muted}`}>URL hashes</span>
              {urlHashes.map((hash) => (
                <span key={hash} className={`rounded-md border px-2 py-1 text-[10px] font-mono ${chip}`}>
                  {shortEvidenceHash(hash)}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className={`rounded-lg border p-3 space-y-2 ${card}`}>
          <div className="flex items-center gap-1.5 text-[11px] font-bold">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            Screenshot review
          </div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
            {screenshotRows.map(([label, value]) => (
              <div key={label} className="contents">
                <span className={muted}>{label}</span>
                <span className="font-mono">{value}</span>
              </div>
            ))}
          </div>
          <div className={`text-[11px] ${muted}`}>
            Screenshot files stay private; audit stores content-addressed refs after execution.
          </div>
        </div>

        <div className={`rounded-lg border p-3 space-y-2 ${card}`}>
          <div className="flex items-center gap-1.5 text-[11px] font-bold">
            <ShieldX className="w-3.5 h-3.5 text-rose-400" />
            Blocked capabilities
          </div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
            {capabilityRows.map(([label, value]) => (
              <div key={label} className="contents">
                <span className={muted}>{label}</span>
                <span className={`font-mono ${value === 'allowed' ? 'text-amber-400' : ''}`}>
                  {value}
                </span>
              </div>
            ))}
          </div>
          <div className={`text-[11px] ${muted}`}>
            Raw task text {beacon.raw_task_text_included ? 'included' : 'hidden'} · web content {beacon.raw_web_content_is_untrusted ? 'untrusted evidence' : 'trusted'}
          </div>
        </div>

        <div className={`rounded-lg border p-3 space-y-2 ${card}`}>
          <div className="flex items-center gap-1.5 text-[11px] font-bold">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
            Risk labels
          </div>
          <div className="flex flex-wrap gap-1.5">
            {riskLabels.length > 0 ? riskLabels.map((label) => (
              <span key={label} className={`rounded-md border px-2 py-1 text-[10px] font-mono ${chip}`}>
                {humanizeBeaconValue(label)}
              </span>
            )) : (
              <span className={`text-[11px] ${muted}`}>No risk labels reported</span>
            )}
          </div>
        </div>
      </div>

      <div className={`rounded-lg border p-3 space-y-2 ${card}`}>
        <div className="flex items-center gap-1.5 text-[11px] font-bold">
          <Clock className="w-3.5 h-3.5 text-cyan-400" />
          Action timeline
        </div>
        <div className="space-y-2">
          {actionTimeline.length > 0 ? actionTimeline.map((step, index) => (
            <div key={`${step.step ?? 'step'}-${index}`} className="grid grid-cols-[1.5rem_1fr] gap-2 text-[11px]">
              <span className={`h-5 w-5 rounded-full border text-center leading-5 font-mono ${chip}`}>
                {index + 1}
              </span>
              <div>
                <div className="font-bold">
                  {humanizeBeaconValue(step.step)}
                  {step.status ? (
                    <span className={`ml-2 font-mono font-normal ${muted}`}>
                      {humanizeBeaconValue(step.status)}
                    </span>
                  ) : null}
                </div>
                {step.description ? (
                  <div className={muted}>{step.description}</div>
                ) : null}
                {typeof step.allowed_host_count === 'number' && (
                  <div className={`font-mono ${muted}`}>allowed hosts: {step.allowed_host_count}</div>
                )}
              </div>
            </div>
          )) : (
            <div className={`text-[11px] ${muted}`}>No action timeline reported</div>
          )}
        </div>
      </div>

      <div className={`text-[11px] ${muted}`}>
        Approve runs only this reviewed browser plan. Deny leaves the browser runtime untouched.
      </div>
    </div>
  )
}
