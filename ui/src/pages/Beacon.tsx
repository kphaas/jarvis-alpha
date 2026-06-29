import { useCallback, useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'
import { MousePointerClick, PlayCircle, RefreshCw, Search, ShieldCheck } from 'lucide-react'
import { BeaconAnswerSummary } from '../components/beacon/BeaconAnswerSummary'
import { BeaconEvidenceTransparencyPanel } from '../components/beacon/BeaconEvidenceTransparencyPanel'
import { BeaconHealthRail } from '../components/beacon/BeaconHealthRail'
import { BeaconModeSelector } from '../components/beacon/BeaconModeSelector'
import { BeaconResearchPlanStrip } from '../components/beacon/BeaconResearchPlanStrip'
import { BeaconSourceCards } from '../components/beacon/BeaconSourceCards'
import { BEACON_MODES, BEACON_PLACEHOLDERS, maxPagesForMode } from '../components/beacon/modeConfig'
import { apiJson } from '../lib/apiFetch'
import { useAppStore } from '../store'
import type {
  BeaconAnswerResponse,
  BeaconBrowserApprovalResponse,
  BeaconFocusMode,
  BeaconHealthPayload,
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
  const activeMode = useMemo(() => BEACON_MODES.find((item) => item.key === mode), [mode])

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

  const runBeacon = async () => {
    const trimmed = query.trim()
    if (!trimmed || runLoading) return
    setRunLoading(true)
    setRunError('')
    try {
      const payload = await apiJson<BeaconAnswerResponse>('/v1/internet-scout/local-llm/tool', {
        method: 'POST',
        body: JSON.stringify({
          query: trimmed,
          tool_hint: 'search',
          focus_mode: mode,
          max_pages: maxPagesForMode(mode),
          max_depth: 0,
          needs_interaction: false,
          sensitivity: 'normal',
          requester: `alpha_ui.beacon_answer_engine.${mode}`,
        }),
      })
      setResult(payload)
      fetchHealth()
    } catch (error) {
      setRunError(error instanceof Error ? error.message : 'Beacon request failed')
      setResult(null)
    } finally {
      setRunLoading(false)
    }
  }

  const queueBrowserApproval = async () => {
    const url = browserUrl.trim()
    const selector = clickSelector.trim()
    if (!url || !selector || approvalLoading) return
    let host = expectedHost.trim()
    try {
      host ||= new URL(url).host
    } catch {
      setApprovalError('Enter a valid public URL.')
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
            {runLoading ? 'Running' : 'Run'}
          </button>
        </div>
        <p className="text-xs opacity-55">{activeMode?.description}</p>
        {runError && <p className="text-sm text-rose-500">{runError}</p>}
      </section>

      <details className={`rounded-lg border p-4 ${border} ${panel}`}>
        <summary className="cursor-pointer text-sm font-semibold">
          Browser action approval
        </summary>
        <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(180px,240px)]">
          <input
            value={browserUrl}
            onChange={(event) => setBrowserUrl(event.target.value)}
            placeholder="https://example.com/page"
            className={`min-h-11 rounded-lg border bg-transparent px-3 text-sm outline-none ${border}`}
          />
          <input
            value={expectedHost}
            onChange={(event) => setExpectedHost(event.target.value)}
            placeholder="expected host"
            className={`min-h-11 rounded-lg border bg-transparent px-3 text-sm outline-none ${border}`}
          />
          <input
            value={clickSelector}
            onChange={(event) => setClickSelector(event.target.value)}
            placeholder="CSS selector to click"
            className={`min-h-11 rounded-lg border bg-transparent px-3 text-sm outline-none ${border}`}
          />
          <input
            value={clickLabel}
            onChange={(event) => setClickLabel(event.target.value)}
            placeholder="label"
            className={`min-h-11 rounded-lg border bg-transparent px-3 text-sm outline-none ${border}`}
          />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={queueBrowserApproval}
            disabled={!browserUrl.trim() || !clickSelector.trim() || approvalLoading}
            className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-cyan-500 px-4 text-sm font-semibold text-[#0A0A0A] transition hover:bg-cyan-400 disabled:opacity-45"
          >
            <MousePointerClick className="h-4 w-4" />
            {approvalLoading ? 'Queueing' : 'Queue approval'}
          </button>
          {approvalResult && (
            <Link
              to="/approvals"
              className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm ${border}`}
            >
              <ShieldCheck className="h-4 w-4 text-emerald-500" />
              Approval {approvalResult.approval_queue_id.slice(0, 8)}
            </Link>
          )}
        </div>
        {approvalResult && (
          <p className="mt-2 text-xs opacity-55">
            hash {approvalResult.preview.approval_hash_prefix} · {approvalResult.preview.allowed_hosts.join(', ') || 'no host'}
          </p>
        )}
        {approvalError && <p className="mt-2 text-sm text-rose-500">{approvalError}</p>}
      </details>

      {!result && !runLoading && (
        <section className={`rounded-lg border p-6 text-sm opacity-60 ${border} ${panel}`}>
          Choose a focus mode and run Beacon.
        </section>
      )}

      {result && (
        <div className="space-y-5">
          <BeaconAnswerSummary result={result} isDark={isDark} />
          <BeaconResearchPlanStrip plan={result.plan.research} report={result.research_report} quality={result.quality} isDark={isDark} />
          <BeaconEvidenceTransparencyPanel transparency={result.evidence_transparency} isDark={isDark} />
          <BeaconSourceCards citations={result.citations} quality={result.quality} isDark={isDark} />
        </div>
      )}
    </motion.div>
  )
}
