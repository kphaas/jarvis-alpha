import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  XCircle,
  Eye,
  Globe2,
  MousePointerClick,
  ShieldX,
  Camera,
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
  target_count?: number
  [key: string]: unknown
}

interface BeaconClickTarget {
  selector: string
  label?: string | null
  expected_host?: string | null
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
  click_targets?: BeaconClickTarget[]
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

function guardRailClass(safe: boolean, isDark: boolean): string {
  if (safe) {
    return isDark
      ? 'border-emerald-400/25 bg-emerald-500/10 text-emerald-100'
      : 'border-emerald-300 bg-emerald-50 text-emerald-950'
  }
  return isDark
    ? 'border-amber-400/25 bg-amber-500/10 text-amber-100'
    : 'border-amber-300 bg-amber-50 text-amber-950'
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
  const clickTargets = beacon.click_targets ?? []
  const actionTimeline = beacon.action_timeline ?? []
  const screenshotPolicy = beacon.screenshot_policy ?? {}
  const card = isDark ? 'bg-black/25 border-white/10' : 'bg-white/70 border-[#141414]/10'
  const chip = isDark
    ? 'bg-cyan-500/10 border-cyan-400/25 text-cyan-100'
    : 'bg-cyan-50 border-cyan-300 text-cyan-900'
  const muted = isDark ? 'text-white/55' : 'text-[#141414]/55'
  const safeCallout = guardRailClass(true, isDark)
  const cautionCallout = guardRailClass(false, isDark)
  const primaryTarget = clickTargets[0]
  const guardRailRows = [
    {
      label: 'Click-only',
      value: beacon.needs_interaction ? 'one reviewed click' : 'observe only',
      safe: true,
    },
    {
      label: 'Same-host',
      value: beacon.same_host_required ? 'locked' : 'not locked',
      safe: beacon.same_host_required,
    },
    {
      label: 'Credentials',
      value: beacon.credential_entry_allowed ? 'not enforced' : 'blocked',
      safe: !beacon.credential_entry_allowed,
    },
    {
      label: 'Screenshots',
      value: beacon.screenshots_required ? 'required' : 'optional',
      safe: beacon.screenshots_required,
    },
  ]

  const capabilityRows = [
    ['Downloads', beacon.downloads_allowed ? 'allowed' : 'blocked'],
    ['Forms', beacon.forms_allowed ? 'allowed' : 'blocked'],
    ['Credential entry', beacon.credential_entry_allowed ? 'allowed' : 'blocked'],
    ['Cross-host navigation', beacon.same_host_required ? 'blocked' : 'allowed'],
  ]

  const screenshotRows = [
    {
      label: 'Required',
      value: beacon.screenshots_required ? 'required' : 'optional',
      safe: beacon.screenshots_required,
    },
    {
      label: 'Before navigation',
      value: policyBoolLabel(
        screenshotPolicy.before_navigation_required,
        'required',
        'not required'
      ),
      safe: screenshotPolicy.before_navigation_required === true,
    },
    {
      label: 'After observation',
      value: policyBoolLabel(
        screenshotPolicy.after_observation_required,
        'required',
        'not required'
      ),
      safe: screenshotPolicy.after_observation_required === true,
    },
    {
      label: 'Available after run',
      value: policyBoolLabel(
        screenshotPolicy.screenshots_available_after_run,
        'yes',
        'no'
      ),
      safe: screenshotPolicy.screenshots_available_after_run === true,
    },
    {
      label: 'Refs',
      value: policyBoolLabel(
        screenshotPolicy.screenshot_refs_redacted_until_execution,
        'redacted until execution',
        'not redacted'
      ),
      safe: screenshotPolicy.screenshot_refs_redacted_until_execution !== false,
    },
  ]

  const reviewSummaryRows = [
    {
      label: 'Same-host lock',
      value: beacon.same_host_required ? 'on' : 'off',
      safe: beacon.same_host_required,
    },
    {
      label: 'Host scope',
      value: allowedHosts.length > 0 ? `${allowedHosts.length} hosts` : 'not reported',
      safe: allowedHosts.length > 0,
    },
    {
      label: 'Screenshots staged',
      value: beacon.screenshots_required ? 'required' : 'optional',
      safe: beacon.screenshots_required,
    },
    {
      label: 'Click targets',
      value: clickTargets.length > 0 ? `${clickTargets.length} reviewed` : 'none',
      safe: clickTargets.length > 0 || !beacon.needs_interaction,
    },
    {
      label: 'No credential entry',
      value: beacon.credential_entry_allowed ? 'not enforced' : 'enforced',
      safe: !beacon.credential_entry_allowed,
    },
  ]

  return (
    <div className={`rounded-lg border p-3 space-y-3 ${card}`}>
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

      <div className="grid gap-2 sm:grid-cols-4">
        {guardRailRows.map((row) => (
          <div key={row.label} className={`rounded-md border px-2.5 py-2 text-[11px] ${guardRailClass(row.safe, isDark)}`}>
            <div className="font-mono text-[10px] uppercase opacity-70">{row.label}</div>
            <div className="mt-0.5 font-bold">{row.value}</div>
          </div>
        ))}
      </div>

      <div className={`rounded-lg border p-3 ${card}`}>
        <div className="mb-2 flex items-center gap-1.5 text-[11px] font-bold">
          <Eye className="h-3.5 w-3.5 text-cyan-400" />
          Review summary
        </div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {reviewSummaryRows.map((row) => (
            <div
              key={row.label}
              className={`rounded-md border px-2.5 py-2 text-[11px] ${guardRailClass(row.safe, isDark)}`}
            >
              <div className="font-mono text-[10px] uppercase opacity-70">
                {row.label}
              </div>
              <div className="mt-0.5 font-bold">{row.value}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-[1.1fr_0.9fr]">
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
            <Camera className="w-3.5 h-3.5 text-emerald-400" />
            Screenshot review
          </div>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {screenshotRows.map((row) => (
              <div
                key={row.label}
                className={`rounded-md border px-2 py-1.5 text-[11px] ${guardRailClass(row.safe, isDark)}`}
              >
                <div className="font-mono text-[10px] uppercase opacity-70">
                  {row.label}
                </div>
                <div className="font-bold">{row.value}</div>
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

      {(clickTargets.length > 0 || beacon.needs_interaction) && (
        <div className={`rounded-lg border p-3 ${card}`}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-[11px] font-bold">
                <MousePointerClick className="h-3.5 w-3.5 text-cyan-400" />
                Click target review
              </div>
              <div className={`mt-1 text-[11px] ${muted}`}>
                {clickTargets.length > 0
                  ? 'Only listed selectors can run after approval.'
                  : 'Interaction requested, but no click targets were reported.'}
              </div>
            </div>
            <span className={`shrink-0 rounded-md border px-2 py-1 text-[10px] font-mono ${clickTargets.length > 0 ? chip : cautionCallout}`}>
              {clickTargets.length} target{clickTargets.length === 1 ? '' : 's'}
            </span>
          </div>

          {primaryTarget ? (
            <div className={`mt-3 rounded-md border p-2 text-[11px] ${isDark ? 'bg-white/5' : 'bg-[#141414]/5'} ${isDark ? 'border-white/10' : 'border-[#141414]/10'}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-bold">{primaryTarget.label || 'Target 1'}</div>
                  <div className={`mt-1 truncate font-mono ${muted}`} title={primaryTarget.selector}>
                    {primaryTarget.selector}
                  </div>
                </div>
                {primaryTarget.expected_host && (
                  <span className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[10px] ${chip}`}>
                    expected host {primaryTarget.expected_host}
                  </span>
                )}
              </div>
              {primaryTarget.expected_host && (
                <div className={`mt-1 font-mono ${muted}`}>same host only</div>
              )}
              {clickTargets.length > 1 && (
                <details className="mt-2">
                  <summary className={`cursor-pointer select-none font-bold ${muted}`}>
                    Show {clickTargets.length - 1} more target{clickTargets.length === 2 ? '' : 's'}
                  </summary>
                  <div className="mt-2 grid gap-2">
                    {clickTargets.slice(1).map((target, index) => (
                      <div key={`${target.selector}-${index}`} className={`rounded border px-2 py-1.5 ${isDark ? 'border-white/10' : 'border-[#141414]/10'}`}>
                        <div className="flex items-start justify-between gap-2">
                          <span className="font-bold">{target.label || `Target ${index + 2}`}</span>
                          {target.expected_host && <span className={`font-mono text-[10px] ${muted}`}>expected host {target.expected_host}</span>}
                        </div>
                        <div className={`mt-1 truncate font-mono ${muted}`} title={target.selector}>
                          {target.selector}
                        </div>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </div>
          ) : (
            <div className={`mt-3 rounded-md border px-2 py-1.5 text-[11px] ${cautionCallout}`}>
              Interaction requested, but no click targets were reported.
            </div>
          )}
        </div>
      )}

      <div className={`rounded-lg border p-3 space-y-2 ${card}`}>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 text-[11px] font-bold">
            <Clock className="w-3.5 h-3.5 text-cyan-400" />
            Action timeline
          </div>
          <span className={`rounded-md border px-2 py-1 text-[10px] font-mono ${chip}`}>
            {actionTimeline.length} reviewed steps
          </span>
        </div>
        <div className="space-y-2">
          {actionTimeline.length > 0 ? actionTimeline.map((step, index) => (
            <div key={`${step.step ?? 'step'}-${index}`} className="grid grid-cols-[1.5rem_1fr] gap-2 text-[11px]">
              <span className={`h-5 w-5 rounded-full border text-center leading-5 font-mono ${chip}`}>
                {index + 1}
              </span>
              <div className={`rounded-md border px-2 py-1.5 ${card}`}>
                <div className="flex flex-wrap items-center gap-2 font-bold">
                  {humanizeBeaconValue(step.step)}
                  {step.status ? (
                    <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] font-normal ${chip}`}>
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
                {typeof step.target_count === 'number' && (
                  <div className={`font-mono ${muted}`}>click targets: {step.target_count}</div>
                )}
              </div>
            </div>
          )) : (
            <div className={`text-[11px] ${muted}`}>No action timeline reported</div>
          )}
        </div>
      </div>

      <div className={`rounded-lg border p-3 text-[11px] ${safeCallout}`}>
        <div className="mb-2 flex items-center gap-1.5 font-bold">
          <CheckCircle2 className="h-3.5 w-3.5" />
          Decision boundary
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="rounded-md border border-current/20 px-2 py-1.5">
            <div className="flex items-center gap-1.5 font-bold">
              <CheckCircle2 className="h-3.5 w-3.5" />
              Approve plan
            </div>
            <div>Runs only this reviewed browser plan.</div>
          </div>
          <div className={`rounded-md border px-2 py-1.5 ${isDark ? 'border-rose-400/25 bg-rose-500/10 text-rose-100' : 'border-rose-300 bg-rose-50 text-rose-950'}`}>
            <div className="flex items-center gap-1.5 font-bold">
              <XCircle className="h-3.5 w-3.5" />
              Deny plan
            </div>
            <div>Leaves the browser runtime untouched.</div>
          </div>
        </div>
      </div>
    </div>
  )
}
