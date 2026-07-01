import { useCallback, useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, History, Loader2, MousePointerClick, PlayCircle, RefreshCw, Search, ShieldCheck } from 'lucide-react'
import { BeaconAnswerSummary } from '../components/beacon/BeaconAnswerSummary'
import { BeaconCrawlerConsole } from '../components/beacon/BeaconCrawlerConsole'
import { BeaconEvidenceTransparencyPanel } from '../components/beacon/BeaconEvidenceTransparencyPanel'
import { BeaconHealthRail } from '../components/beacon/BeaconHealthRail'
import { BeaconModeSelector } from '../components/beacon/BeaconModeSelector'
import { BeaconResearchPlanStrip } from '../components/beacon/BeaconResearchPlanStrip'
import { BeaconSourceCards } from '../components/beacon/BeaconSourceCards'
import { BEACON_MODES, BEACON_PLACEHOLDERS } from '../components/beacon/modeConfig'
import { apiFetch, apiJson } from '../lib/apiFetch'
import { useAppStore } from '../store'
import type {
  BeaconAnswerResponse,
  BeaconBrowserApprovalResponse,
  BeaconFocusMode,
  BeaconHealthPayload,
  BeaconMode,
  BeaconRequestHistoryItem,
  BeaconRequestHistoryResponse,
  BeaconResearchProgressEvent,
} from '../types/beacon'

export default function Beacon() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-white/5' : 'bg-white/50'
  const [mode, setMode] = useState<BeaconFocusMode>('all')
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<BeaconAnswerResponse | null>(null)
  const [runLoading, setRunLoading] = useState(false)
  const [runError, setRunError] = useState('')
  const [researchSteps, setResearchSteps] = useState<BeaconResearchProgressEvent[]>([])
  const [browserUrl, setBrowserUrl] = useState('')
  const [clickSelector, setClickSelector] = useState('')
  const [clickLabel, setClickLabel] = useState('')
  const [expectedHost, setExpectedHost] = useState('')
  const [approvalLoading, setApprovalLoading] = useState(false)
  const [approvalError, setApprovalError] = useState('')
  const [approvalResult, setApprovalResult] = useState<BeaconBrowserApprovalResponse | null>(null)
  const [health, setHealth] = useState<BeaconHealthPayload | null>(null)
  const [healthLoading, setHealthLoading] = useState(true)
  const [healthError, setHealthError] = useState(false)
  const [historyDraftQuery, setHistoryDraftQuery] = useState('')
  const [historyQuery, setHistoryQuery] = useState('')
  const [historyStatus, setHistoryStatus] = useState('all')
  const [historyOffset, setHistoryOffset] = useState(0)
  const [historyRows, setHistoryRows] = useState<BeaconRequestHistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [historyHasMore, setHistoryHasMore] = useState(false)
  const activeMode = useMemo(() => BEACON_MODES.find((item) => item.key === mode) ?? BEACON_MODES[0], [mode])
  const browserHost = useMemo(() => parseUrlHost(browserUrl), [browserUrl])
  const reviewedHost = expectedHost.trim().toLowerCase() || browserHost.host
  const hostMismatch = Boolean(
    browserHost.host && expectedHost.trim() && browserHost.host !== expectedHost.trim().toLowerCase()
  )
  const browserUrlInvalid = Boolean(browserUrl.trim() && !browserHost.valid)

  const fetchHealth = useCallback(() => {
    setHealthLoading(true)
    setHealthError(false)
    apiJson<BeaconHealthPayload>('/v1/internet-scout/health')
      .then((payload) => setHealth(payload))
      .catch(() => {
        setHealth(null)
        setHealthError(true)
      })
      .finally(() => setHealthLoading(false))
  }, [])

  useEffect(() => {
    fetchHealth()
  }, [fetchHealth])

  const fetchHistory = useCallback(() => {
    setHistoryLoading(true)
    setHistoryError('')
    const params = new URLSearchParams({
      limit: '12',
      offset: String(historyOffset),
    })
    if (historyStatus !== 'all') params.set('status', historyStatus)
    if (historyQuery.trim()) params.set('q', historyQuery.trim())
    apiJson<BeaconRequestHistoryResponse>(`/v1/internet-scout/requests?${params.toString()}`)
      .then((payload) => {
        setHistoryRows(payload.history ?? [])
        setHistoryHasMore(payload.has_more)
      })
      .catch((error) => {
        setHistoryRows([])
        setHistoryHasMore(false)
        setHistoryError(error instanceof Error ? error.message : 'Beacon history unavailable')
      })
      .finally(() => setHistoryLoading(false))
  }, [historyOffset, historyQuery, historyStatus])

  useEffect(() => {
    fetchHistory()
  }, [fetchHistory])

  const runBeacon = async () => {
    const trimmed = query.trim()
    if (!trimmed || runLoading) return
    const requestBody = JSON.stringify({
      query: trimmed,
      tool_hint: 'search',
      focus_mode: mode,
      max_pages: activeMode.maxPages,
      max_depth: 0,
      needs_interaction: false,
      sensitivity: 'normal',
      requester: `alpha_ui.beacon_answer_engine.${mode}`,
    })
    setRunLoading(true)
    setRunError('')
    setResearchSteps(mode === 'deep_research'
      ? [{
        stage: 'queued',
        status: 'queued',
        detail: 'Request queued by Beacon UI.',
      }]
      : [])
    try {
      if (mode === 'deep_research') {
        await runBeaconStream(requestBody)
      } else {
        const payload = await apiJson<BeaconAnswerResponse>('/v1/internet-scout/local-llm/tool', {
          method: 'POST',
          body: requestBody,
        })
        setResult(payload)
      }
      fetchHealth()
    } catch (error) {
      setRunError(error instanceof Error ? error.message : 'Beacon request failed')
      setResult(null)
    } finally {
      setRunLoading(false)
    }
  }

  const runBeaconStream = async (requestBody: string) => {
    const response = await apiFetch('/v1/internet-scout/local-llm/tool/stream', {
      method: 'POST',
      body: requestBody,
    })
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
    if (!response.body) {
      throw new Error('Beacon stream is unavailable in this browser.')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let completed = false

    try {
      while (true) {
        const { value, done } = await reader.read()
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
        const frames = buffer.split('\n\n')
        buffer = frames.pop() || ''

        for (const frame of frames) {
          const parsed = parseBeaconStreamFrame(frame)
          if (!parsed) continue
          if (parsed.event === 'step') {
            setResearchSteps((previous) => [...previous, parsed.data as BeaconResearchProgressEvent].slice(-8))
          }
          if (parsed.event === 'completed') {
            completed = true
            const completedStep: BeaconResearchProgressEvent = {
              stage: 'completed',
              status: 'completed',
              detail: 'Evidence bundle and report ready.',
            }
            setResearchSteps((previous) => [
              ...previous,
              completedStep,
            ].slice(-8))
            setResult(parsed.data as BeaconAnswerResponse)
          }
          if (parsed.event === 'failed') {
            const failure = parsed.data as Partial<BeaconResearchProgressEvent>
            const failedStep: BeaconResearchProgressEvent = {
              stage: 'failed',
              status: 'failed',
              detail: failure.detail || 'Beacon stream failed.',
            }
            setResearchSteps((previous) => [
              ...previous,
              failedStep,
            ].slice(-8))
            throw new Error(failure.detail || 'Beacon stream failed.')
          }
        }

        if (done) break
      }
    } finally {
      reader.releaseLock()
    }

    if (!completed) {
      throw new Error('Beacon stream ended before completion.')
    }
  }

  const queueBrowserApproval = async () => {
    const url = browserUrl.trim()
    const selector = clickSelector.trim()
    if (!url || !selector || approvalLoading) return
    let host = expectedHost.trim()
    let urlHost = ''
    try {
      urlHost = new URL(url).host.toLowerCase()
      host ||= urlHost
    } catch {
      setApprovalError('Enter a valid public URL.')
      return
    }
    if (host.toLowerCase() !== urlHost) {
      setApprovalError('Expected host must match the URL host for click-only requests.')
      return
    }
    setApprovalLoading(true)
    setApprovalError('')
    setApprovalResult(null)
    try {
      const payload = await apiJson<BeaconBrowserApprovalResponse>('/v1/internet-scout/browser-task/approval-request', {
        method: 'POST',
        body: JSON.stringify({
          urls: [url],
          browser_clicks: [{
            selector,
            label: clickLabel.trim() || null,
            expected_host: host || null,
          }],
          max_pages: 1,
          max_depth: 0,
          needs_interaction: true,
          sensitivity: 'normal',
          requester: 'alpha_ui.beacon_browser_action',
        }),
      })
      setApprovalResult(payload)
      fetchHealth()
    } catch (error) {
      setApprovalError(error instanceof Error ? error.message : 'Approval request failed')
    } finally {
      setApprovalLoading(false)
    }
  }

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="max-w-6xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Beacon</h1>
          <p className="mt-1 text-[10px] font-mono uppercase tracking-widest opacity-50">Answer engine · evidence first</p>
        </div>
        <button
          type="button"
          onClick={fetchHealth}
          disabled={healthLoading}
          className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm transition ${border} ${panel} disabled:opacity-45`}
        >
          <RefreshCw className={`h-4 w-4 ${healthLoading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      <BeaconHealthRail health={health} loading={healthLoading} error={healthError} isDark={isDark} />

      <section className={`space-y-4 rounded-lg border p-4 ${border} ${panel}`}>
        <BeaconModeSelector value={mode} onChange={setMode} isDark={isDark} />
        <div className="flex flex-col gap-3 lg:flex-row">
          <label className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 opacity-45" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void runBeacon()
              }}
              placeholder={BEACON_PLACEHOLDERS[mode]}
              className={`min-h-11 w-full rounded-lg border bg-transparent py-2 pl-10 pr-3 text-sm outline-none transition ${border} ${isDark ? 'focus:border-emerald-400' : 'focus:border-[#141414]'}`}
            />
          </label>
          <button
            type="button"
            onClick={runBeacon}
            disabled={!query.trim() || runLoading}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-emerald-500 px-4 text-sm font-semibold text-[#0A0A0A] transition hover:bg-emerald-400 disabled:opacity-45"
          >
            <PlayCircle className="h-4 w-4" />
            {runLoading ? 'Running' : activeMode.runLabel}
          </button>
        </div>
        <BeaconModeRunContract mode={activeMode} isDark={isDark} />
        {researchSteps.length > 0 && (
          <BeaconResearchStreamTrace steps={researchSteps} result={result} isDark={isDark} />
        )}
        {runError && <p className="text-sm text-rose-500">{runError}</p>}
      </section>

      <BeaconCrawlerConsole isDark={isDark} onComplete={fetchHealth} />

      <details className={`rounded-lg border p-4 ${border} ${panel}`}>
        <summary className="cursor-pointer text-sm font-semibold">
          Browser click-only request
        </summary>
        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-3">
            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(180px,240px)]">
              <input
                value={browserUrl}
                onChange={(event) => setBrowserUrl(event.target.value)}
                placeholder="URL to inspect"
                className={`min-h-11 rounded-lg border bg-transparent px-3 text-sm outline-none ${border}`}
              />
              <input
                value={expectedHost}
                onChange={(event) => setExpectedHost(event.target.value)}
                placeholder="Allowed host (auto)"
                className={`min-h-11 rounded-lg border bg-transparent px-3 text-sm outline-none ${border}`}
              />
              <input
                value={clickSelector}
                onChange={(event) => setClickSelector(event.target.value)}
                placeholder="CSS selector for one reviewed click"
                className={`min-h-11 rounded-lg border bg-transparent px-3 text-sm outline-none ${border}`}
              />
              <input
                value={clickLabel}
                onChange={(event) => setClickLabel(event.target.value)}
                placeholder="Click target label"
                className={`min-h-11 rounded-lg border bg-transparent px-3 text-sm outline-none ${border}`}
              />
            </div>
            <div className="flex flex-wrap gap-2">
              {['Click only', 'No typing/forms', 'No credentials', 'Same host', 'Screenshots + audit'].map((item) => (
                <span key={item} className={`rounded border px-2 py-1 text-[10px] font-mono uppercase ${border}`}>
                  {item}
                </span>
              ))}
            </div>
            {browserUrlInvalid && <p className="text-xs text-rose-500">Enter a full URL with https://.</p>}
            {hostMismatch && <p className="text-xs text-amber-500">Allowed host must match the URL host for click-only approval.</p>}
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={queueBrowserApproval}
                disabled={!browserUrl.trim() || !clickSelector.trim() || approvalLoading || browserUrlInvalid || hostMismatch}
                className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-cyan-500 px-4 text-sm font-semibold text-[#0A0A0A] transition hover:bg-cyan-400 disabled:opacity-45"
              >
                <MousePointerClick className="h-4 w-4" />
                {approvalLoading ? 'Queueing' : 'Queue click approval'}
              </button>
              {approvalResult && (
                <Link
                  to="/approvals"
                  className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm ${border}`}
                >
                  <ShieldCheck className="h-4 w-4 text-emerald-500" />
                  Review {approvalResult.approval_queue_id.slice(0, 8)}
                </Link>
              )}
            </div>
            {approvalError && <p className="text-sm text-rose-500">{approvalError}</p>}
          </div>
          <div className={`rounded-lg border p-3 text-xs ${border} ${isDark ? 'bg-black/15' : 'bg-white/35'}`}>
            <p className="font-mono uppercase tracking-widest opacity-45">Approval preview</p>
            <div className="mt-3 grid gap-2">
              <PreviewRow label="Reviewed host" value={reviewedHost || 'enter URL'} />
              <PreviewRow label="Target" value={clickLabel.trim() || clickSelector.trim() || 'enter selector'} />
              <PreviewRow label="Action space" value="single click, no input" />
              <PreviewRow label="Decision" value="operator approve or deny" />
            </div>
            {approvalResult && (
              <p className="mt-3 border-t pt-3 font-mono text-[10px] uppercase opacity-55">
                hash {approvalResult.preview.approval_hash_prefix} · {approvalResult.preview.allowed_hosts.join(', ') || 'no host'}
              </p>
            )}
          </div>
        </div>
      </details>

      <details className={`rounded-lg border p-4 ${border} ${panel}`}>
        <summary className="cursor-pointer text-sm font-semibold">
          Saved Beacon history
        </summary>
        <div className="mt-4 flex flex-col gap-3 lg:flex-row">
          <label className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 opacity-45" />
            <input
              value={historyDraftQuery}
              onChange={(event) => setHistoryDraftQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  setHistoryOffset(0)
                  setHistoryQuery(historyDraftQuery)
                }
              }}
              placeholder="Search request id, requester, host, claim, status"
              className={`min-h-11 w-full rounded-lg border bg-transparent py-2 pl-10 pr-3 text-sm outline-none ${border}`}
            />
          </label>
          <select
            value={historyStatus}
            onChange={(event) => {
              setHistoryOffset(0)
              setHistoryStatus(event.target.value)
            }}
            className={`min-h-11 rounded-lg border bg-transparent px-3 text-sm outline-none ${border}`}
          >
            <option value="all">All status</option>
            <option value="succeeded">Succeeded</option>
            <option value="running">Running</option>
            <option value="failed">Failed</option>
            <option value="blocked">Blocked</option>
          </select>
          <button
            type="button"
            onClick={() => {
              setHistoryOffset(0)
              setHistoryQuery(historyDraftQuery)
            }}
            className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border px-3 text-sm ${border}`}
          >
            <History className="h-4 w-4" />
            Search history
          </button>
        </div>
        <div className="mt-4 space-y-2">
          {historyLoading && <p className="text-sm opacity-55">Loading saved Beacon history.</p>}
          {historyError && <p className="text-sm text-rose-500">{historyError}</p>}
          {!historyLoading && !historyError && historyRows.length === 0 && (
            <p className="text-sm opacity-55">No saved Beacon requests match this view.</p>
          )}
          {!historyLoading && !historyError && historyRows.map((item) => (
            <BeaconHistoryRow key={item.request_id} item={item} border={border} isDark={isDark} />
          ))}
        </div>
        {!historyError && (historyOffset > 0 || historyHasMore) && (
          <div className="mt-3 flex items-center justify-between gap-3">
            <button
              type="button"
              disabled={historyOffset === 0}
              onClick={() => setHistoryOffset(Math.max(0, historyOffset - 12))}
              className={`min-h-10 rounded-lg border px-3 text-sm disabled:opacity-45 ${border}`}
            >
              Previous
            </button>
            <p className="text-xs opacity-55">
              {historyOffset + 1}-{historyOffset + historyRows.length}{historyHasMore ? '+' : ''}
            </p>
            <button
              type="button"
              disabled={!historyHasMore}
              onClick={() => setHistoryOffset(historyOffset + 12)}
              className={`min-h-10 rounded-lg border px-3 text-sm disabled:opacity-45 ${border}`}
            >
              Next
            </button>
          </div>
        )}
      </details>

      {!result && !runLoading && (
        <section className={`rounded-lg border p-6 text-sm opacity-60 ${border} ${panel}`}>
          Choose a focus mode and run Beacon.
        </section>
      )}

      {result && (
        <div className="space-y-5">
          <BeaconAnswerSummary result={result} isDark={isDark} />
          <BeaconResearchPlanStrip
            plan={result.plan.research}
            report={result.research_report}
            quality={result.quality}
            evidenceBundle={result.evidence_bundle}
            isDark={isDark}
          />
          <BeaconEvidenceTransparencyPanel transparency={result.evidence_transparency} isDark={isDark} />
          <BeaconSourceCards citations={result.citations} quality={result.quality} isDark={isDark} />
        </div>
      )}
    </motion.div>
  )
}

function PreviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">{label}</p>
      <p className="mt-0.5 truncate font-semibold">{value}</p>
    </div>
  )
}

function BeaconHistoryRow({
  item,
  border,
  isDark,
}: {
  item: BeaconRequestHistoryItem
  border: string
  isDark: boolean
}) {
  const hostPreview = item.source_hosts.slice(0, 3).join(', ') || 'no sources yet'
  const eventPreview = item.latest_event_type
    ? `${item.latest_event_type.replaceAll('_', ' ')} · ${item.latest_event_status || 'unknown'}`
    : 'no events'

  return (
    <div className={`rounded-lg border px-3 py-2 text-sm ${border} ${isDark ? 'bg-black/15' : 'bg-white/35'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-semibold">{item.requester} · {item.selected_tool}</p>
          <p className="mt-0.5 font-mono text-[10px] uppercase opacity-50">
            {item.request_id.slice(0, 8)} · {formatBeaconDate(item.created_at)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded border px-2 py-0.5 text-[10px] font-mono uppercase ${historyStatusClass(item.status)} ${border}`}>
            {item.status}
          </span>
          <span className={`rounded border px-2 py-0.5 text-[10px] font-mono uppercase ${border}`}>
            {item.risk_tier}
          </span>
        </div>
      </div>
      <div className="mt-2 grid gap-2 text-xs sm:grid-cols-4">
        <PreviewRow label="Evidence" value={`${item.source_count} sources · ${item.claim_count} claims`} />
        <PreviewRow label="Latest event" value={eventPreview} />
        <PreviewRow label="Hosts" value={hostPreview} />
        <PreviewRow label="Shape" value={`${item.has_query ? 'query' : 'url'} · ${item.max_pages}p · ${item.event_count} events`} />
      </div>
    </div>
  )
}

function parseUrlHost(value: string): { host: string; valid: boolean } {
  const trimmed = value.trim()
  if (!trimmed) return { host: '', valid: true }
  try {
    return { host: new URL(trimmed).host.toLowerCase(), valid: true }
  } catch {
    return { host: '', valid: false }
  }
}

function historyStatusClass(status: string): string {
  if (status === 'succeeded') return 'text-emerald-500'
  if (status === 'failed') return 'text-rose-500'
  if (status === 'blocked') return 'text-amber-500'
  return 'opacity-70'
}

function formatBeaconDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function BeaconModeRunContract({ mode, isDark }: { mode: BeaconMode; isDark: boolean }) {
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  return (
    <div className={`grid gap-2 rounded-lg border px-3 py-2 text-xs ${border} ${isDark ? 'bg-black/15' : 'bg-white/35'} sm:grid-cols-4`}>
      <ContractMetric label="Source policy" value={mode.sourcePolicy} />
      <ContractMetric label="Provider route" value={mode.providerStrategy} />
      <ContractMetric label="Extract budget" value={mode.extractBudget} />
      <ContractMetric label="Page cap" value={`${mode.maxPages} page${mode.maxPages === 1 ? '' : 's'}`} />
    </div>
  )
}

function ContractMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">{label}</p>
      <p className="mt-1 truncate font-semibold">{value}</p>
    </div>
  )
}

function BeaconResearchStreamTrace({
  steps,
  result,
  isDark,
}: {
  steps: BeaconResearchProgressEvent[]
  result: BeaconAnswerResponse | null
  isDark: boolean
}) {
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-black/20' : 'bg-white/40'
  const activeStep = steps[steps.length - 1]
  const completed = steps.filter((step) => step.status === 'completed').length
  const progress = `${completed}/${steps.length}`
  const providerRoute = activeStep?.search_providers?.join(' > ') || result?.plan.research.search_providers.join(' > ')
  const exportReady = Boolean(result?.research_report.report_markdown || result?.evidence_bundle)

  return (
    <div className={`rounded-lg border px-3 py-2 ${border} ${panel}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Live research trace</p>
          <p className="mt-1 text-sm font-semibold">{activeStep?.detail || 'Waiting for Beacon'}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded border px-2 py-1 text-[10px] font-mono uppercase ${border}`}>
            {progress} steps
          </span>
          {exportReady && (
            <span className={`rounded border px-2 py-1 text-[10px] font-mono uppercase text-emerald-500 ${border}`}>
              Export ready
            </span>
          )}
          <span className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[10px] font-mono uppercase ${border}`}>
          {activeStep?.status === 'completed' || activeStep?.status === 'failed' ? (
            activeStep.status === 'failed' ? <AlertTriangle className="h-3 w-3" /> : <CheckCircle2 className="h-3 w-3" />
          ) : (
            <Loader2 className="h-3 w-3 animate-spin" />
          )}
          {activeStep?.stage || 'queued'}
          </span>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-[10px] font-mono uppercase opacity-60">
        {activeStep?.plan_id && <span>plan {activeStep.plan_id.slice(0, 8)}</span>}
        {providerRoute && <span>route {providerRoute}</span>}
        {activeStep?.max_searches !== undefined && <span>{activeStep.max_searches} searches</span>}
        {activeStep?.max_extracts !== undefined && <span>{activeStep.max_extracts} extracts</span>}
        {activeStep?.source_count !== undefined && <span>{activeStep.source_count} sources</span>}
        {activeStep?.claim_count !== undefined && <span>{activeStep.claim_count} claims</span>}
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {steps.map((step, index) => (
          <div
            key={`${step.stage}-${index}`}
            className={`rounded border px-2 py-1.5 text-[10px] ${border} ${step.status === 'failed' ? 'text-rose-500' : ''}`}
          >
            <div className="flex items-center justify-between gap-2 font-mono uppercase">
              <span>{step.stage.replaceAll('_', ' ')}</span>
              <span className={step.status === 'completed' ? 'text-emerald-500' : step.status === 'failed' ? 'text-rose-500' : 'opacity-55'}>
                {step.status}
              </span>
            </div>
            <p className="mt-1 line-clamp-2 text-xs normal-case opacity-65">{step.detail}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function parseBeaconStreamFrame(frame: string): { event: string; data: unknown } | null {
  const eventLine = frame.split('\n').find((line) => line.startsWith('event:'))
  const dataLine = frame.split('\n').find((line) => line.startsWith('data:'))
  if (!eventLine || !dataLine) return null
  const event = eventLine.replace('event:', '').trim()
  try {
    return {
      event,
      data: JSON.parse(dataLine.replace('data:', '').trim()) as unknown,
    }
  } catch {
    return null
  }
}
