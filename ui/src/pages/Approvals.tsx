import { useEffect, useState, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'
import { ShieldCheck, ShieldX, Clock, AlertTriangle, Lock, Unlock, Fingerprint, Sparkles, Activity, MousePointerClick, Camera, ListChecks, Eye, FileText } from 'lucide-react'
import { BeaconBrowserApprovalPanel, type BeaconApprovalContext } from '../components/beacon/BeaconBrowserApprovalPanel'
import { apiJson } from '../lib/apiFetch'
import { useAppStore } from '../store'
import type { SparkIMessageApprovedSendResponse } from '../types/spark'

interface PrivacyApprovalContext {
  case_id: string
  action_count: number
  action_statuses: string[]
}

interface SparkApprovalContext {
  kind: string
  can_send: boolean
  requires_human_approval: boolean
  principal_id?: string | null
  target_label?: string | null
  outbox_id?: string | null
  outbox_status?: string | null
  outbox_recorded?: boolean
}

interface QueueItem {
  id: string
  action_class: string[]
  risk_tier: string
  actor_sub: string
  actor_type: string
  description: string
  status: string
  requested_at: string
  expires_at: string
  overnight: boolean
  privacy: PrivacyApprovalContext | null
  spark: SparkApprovalContext | null
  beacon: BeaconApprovalContext | null
}

interface PendingResponse {
  pending: QueueItem[]
  count: number
}

interface BrowserHistoryItem {
  request_id: string
  approval_queue_id: string | null
  event_type: string
  status: string
  created_at: string
  selected_tool: string
  request_status: string
  risk_tier: string | null
  approval_hash_prefix: string | null
  observation_count: number
  screenshot_count: number
  action_audit_count: number
  action: string | null
  host: string | null
  blocked_reason: string | null
  elapsed_ms: number | null
  screenshot_refs?: string[]
  evidence_path?: string | null
  audit_path?: string | null
}

interface BrowserHistoryResponse {
  history: BrowserHistoryItem[]
  count: number
  limit: number
  offset: number
  has_more: boolean
}

interface BrowserHistorySummary {
  approvalRequests: number
  browserRuns: number
  browserActions: number
  screenshots: number
  auditedActions: number
  blockedOrFailed: number
}

interface DecideResponse {
  queue_id: string
  decision: string
  description: string
  expires_at: string | null
}

const REFRESH_MS = 10_000
const SPARK_APPROVE_SEND_TARGETS = new Set(['sweta', 'meagan'])

const TIER_COLORS: Record<string, string> = {
  T4: 'text-amber-400 bg-amber-500/15 border-amber-500/30',
  T5: 'text-rose-400 bg-rose-500/15 border-rose-500/30',
}

const ACTION_LABELS: Record<string, string> = {
  destructive: 'Permanently deletes data',
  admin: 'Changes system config or permissions',
  deploy: 'Deploys to a live node',
  child_facing: 'Affects content for Ryleigh or Sloane',
  privacy_draft_handoff: 'Queues a reviewed privacy packet for approval',
  spark_draft_handoff: 'Queues a reviewed Spark draft for approval',
  beacon_browser_use: 'Queues a browser action for exact human approval before execution',
  external_call: 'Allows a controlled external service call after approval',
  security_write: 'Changes protected security or privacy state',
  unclassified: 'No classification — blocked by default',
}

function tierBadge(tier: string) {
  const cls = TIER_COLORS[tier] ?? 'text-zinc-400 bg-zinc-500/15 border-zinc-500/30'
  return (
    <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${cls}`}>
      {tier}
    </span>
  )
}

function actionBadge(ac: string) {
  const colors: Record<string, string> = {
    destructive: 'text-rose-400 bg-rose-500/15 border-rose-500/30',
    admin: 'text-purple-400 bg-purple-500/15 border-purple-500/30',
    deploy: 'text-blue-400 bg-blue-500/15 border-blue-500/30',
    child_facing: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30',
    privacy_draft_handoff: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30',
    spark_draft_handoff: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30',
    beacon_browser_use: 'text-cyan-400 bg-cyan-500/15 border-cyan-500/30',
    external_call: 'text-sky-400 bg-sky-500/15 border-sky-500/30',
    security_write: 'text-amber-400 bg-amber-500/15 border-amber-500/30',
    unclassified: 'text-zinc-400 bg-zinc-500/15 border-zinc-500/30',
  }
  const cls = colors[ac] ?? colors.unclassified
  return (
    <span key={ac} className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${cls}`}>
      {ac}
    </span>
  )
}

function timeLeft(expiresAt: string): string {
  const ms = new Date(expiresAt).getTime() - Date.now()
  if (ms <= 0) return 'Expired'
  const mins = Math.floor(ms / 60000)
  const secs = Math.floor((ms % 60000) / 1000)
  return `${mins}m ${secs}s left`
}

function buildSparkReviewUrl(item: QueueItem): string {
  const params = new URLSearchParams({ approval: item.id })
  if (item.spark?.principal_id) {
    params.set('principal', item.spark.principal_id)
  }
  if (item.spark?.target_label) {
    params.set('target', item.spark.target_label)
  }
  return `/spark?${params.toString()}`
}

function canApproveAndSendSpark(item: QueueItem): boolean {
  const target = item.spark?.target_label?.trim().toLowerCase()
  return Boolean(
    item.spark?.outbox_recorded &&
    item.spark?.outbox_id &&
    target &&
    SPARK_APPROVE_SEND_TARGETS.has(target)
  )
}

function shortId(value?: string | null): string {
  return value ? value.slice(0, 8) : 'none'
}

function shortEvidenceRef(value: string): string {
  return value.startsWith('sha256:') ? `sha256:${value.slice(7, 15)}` : shortId(value)
}

function eventLabel(value: string): string {
  return value.replace(/_/g, ' ')
}

function historyStatusClass(status: string): string {
  if (status === 'executed' || status === 'succeeded' || status === 'queued' || status === 'requested') {
    return 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30'
  }
  if (status === 'failed' || status === 'blocked' || status === 'denied') {
    return 'text-rose-400 bg-rose-500/15 border-rose-500/30'
  }
  return 'text-amber-400 bg-amber-500/15 border-amber-500/30'
}

function historyDisplayStatus(item: BrowserHistoryItem): string {
  const requestStatus = item.request_status.toLowerCase()
  const eventStatus = item.status.toLowerCase()
  if (requestStatus === 'denied' || eventStatus === 'denied') return 'denied'
  if (requestStatus === 'expired' || eventStatus === 'expired') return 'expired'
  if (requestStatus === 'blocked' || eventStatus === 'blocked') return 'blocked'
  if (requestStatus === 'failed' || eventStatus === 'failed') return 'failed'
  if (eventStatus === 'succeeded' || requestStatus === 'succeeded') {
    return item.event_type === 'approval_request' ? 'requested' : 'executed'
  }
  if (eventStatus === 'queued' || requestStatus === 'queued') return 'requested'
  return eventStatus || requestStatus || 'unknown'
}

function summarizeBrowserHistory(history: BrowserHistoryItem[]): BrowserHistorySummary {
  return history.reduce(
    (summary, item) => ({
      approvalRequests: summary.approvalRequests + (item.event_type === 'approval_request' ? 1 : 0),
      browserRuns: summary.browserRuns + (item.event_type === 'browser_run' ? 1 : 0),
      browserActions: summary.browserActions + (item.event_type === 'browser_action' ? 1 : 0),
      screenshots: summary.screenshots + item.screenshot_count,
      auditedActions: summary.auditedActions + item.action_audit_count,
      blockedOrFailed: summary.blockedOrFailed + (item.status === 'blocked' || item.status === 'failed' ? 1 : 0),
    }),
    {
      approvalRequests: 0,
      browserRuns: 0,
      browserActions: 0,
      screenshots: 0,
      auditedActions: 0,
      blockedOrFailed: 0,
    }
  )
}

function historyEventIcon(eventType: string) {
  if (eventType === 'approval_request') return <ShieldCheck className="h-4 w-4" />
  if (eventType === 'browser_run') return <Activity className="h-4 w-4" />
  if (eventType === 'browser_action') return <MousePointerClick className="h-4 w-4" />
  return <Fingerprint className="h-4 w-4" />
}

export default function Approvals() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/5' : 'bg-[#141414]/5'

  const [data, setData] = useState<PendingResponse | null>(null)
  const [browserHistory, setBrowserHistory] = useState<BrowserHistoryItem[]>([])
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [historyQuery, setHistoryQuery] = useState('')
  const [historyEventType, setHistoryEventType] = useState('all')
  const [historyOffset, setHistoryOffset] = useState(0)
  const [historyHasMore, setHistoryHasMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [acting, setActing] = useState<string | null>(null)
  const [approvalToken, setApprovalToken] = useState<string | null>(null)
  const [tokenExpiry, setTokenExpiry] = useState<number>(0)
  const [pinInput, setPinInput] = useState('')
  const [showPinModal, setShowPinModal] = useState(false)
  const [pinError, setPinError] = useState<string | null>(null)
  const [actionResult, setActionResult] = useState<{
    id: string
    decision: string
    sparkReturnUrl?: string | null
    sendStatus?: string | null
  } | null>(null)

  const isUnlocked = approvalToken && Date.now() < tokenExpiry

  const load = useCallback(async () => {
    try {
      const res = await apiJson<PendingResponse>('/v1/approvals/pending')
      setData(res)
      setError(null)
      try {
        const historyParams = new URLSearchParams({
          limit: '12',
          offset: String(historyOffset),
        })
        const trimmedQuery = historyQuery.trim()
        if (trimmedQuery) historyParams.set('q', trimmedQuery)
        if (historyEventType !== 'all') historyParams.set('event_type', historyEventType)
        const history = await apiJson<BrowserHistoryResponse>(
          `/v1/internet-scout/browser-task/history?${historyParams.toString()}`
        )
        setBrowserHistory(history.history ?? [])
        setHistoryHasMore(history.has_more)
        setHistoryError(null)
      } catch (historyLoadError) {
        setBrowserHistory([])
        setHistoryHasMore(false)
        setHistoryError(
          historyLoadError instanceof Error
            ? historyLoadError.message
            : 'Failed to load browser history'
        )
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [historyEventType, historyOffset, historyQuery])

  useEffect(() => {
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => clearInterval(id)
  }, [load])

  const handleUnlock = async () => {
    setPinError(null)
    try {
      const res = await apiJson<{ approval_token: string; expires_in: number }>(
        '/v1/approvals/unlock',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pin: pinInput }),
        }
      )
      setApprovalToken(res.approval_token)
      setTokenExpiry(Date.now() + res.expires_in * 1000)
      setShowPinModal(false)
      setPinInput('')
    } catch {
      setPinError('Invalid PIN')
    }
  }

  const handleDecide = async (item: QueueItem, decision: 'approved' | 'denied') => {
    if (!isUnlocked) {
      setShowPinModal(true)
      return
    }
    setActing(item.id)
    setActionResult(null)
    try {
      const res = await apiJson<DecideResponse>(
        `/v1/approvals/${item.id}/decide`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Approval-Token': approvalToken!,
          },
          body: JSON.stringify({ decision }),
        }
      )
      setActionResult({
        id: item.id,
        decision: res.decision,
        sparkReturnUrl:
          res.decision === 'approved' && item.spark ? buildSparkReviewUrl(item) : null,
      })
      await load()
    } catch (e) {
      if (e instanceof Error && e.message.includes('403')) {
        setApprovalToken(null)
        setShowPinModal(true)
      }
    } finally {
      setActing(null)
    }
  }

  const handleApproveAndSendSpark = async (item: QueueItem) => {
    if (!isUnlocked) {
      setShowPinModal(true)
      return
    }
    const outboxId = item.spark?.outbox_id
    if (!outboxId || !canApproveAndSendSpark(item)) {
      return
    }
    setActing(item.id)
    setActionResult(null)
    let decision: DecideResponse | null = null
    try {
      decision = await apiJson<DecideResponse>(
        `/v1/approvals/${item.id}/decide`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Approval-Token': approvalToken!,
          },
          body: JSON.stringify({ decision: 'approved' }),
        }
      )
      const send = await apiJson<SparkIMessageApprovedSendResponse>(
        `/v1/spark/drafts/imessage/outbox/${outboxId}/send`,
        { method: 'POST' }
      )
      setActionResult({
        id: item.id,
        decision: decision.decision,
        sparkReturnUrl: buildSparkReviewUrl(item),
        sendStatus: send.outbox_status,
      })
      await load()
    } catch (e) {
      if (e instanceof Error && e.message.includes('403')) {
        setApprovalToken(null)
        setShowPinModal(true)
        return
      }
      setError(e instanceof Error ? e.message : 'Approve + Send failed')
      if (decision) {
        setActionResult({
          id: item.id,
          decision: decision.decision,
          sparkReturnUrl: buildSparkReviewUrl(item),
        })
      }
      await load()
    } finally {
      setActing(null)
    }
  }

  const pending = data?.pending ?? []
  const count = data?.count ?? 0
  const historyStart = browserHistory.length > 0 ? historyOffset + 1 : 0
  const historyEnd = historyOffset + browserHistory.length
  const historySummary = summarizeBrowserHistory(browserHistory)

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="space-y-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <h1 className="font-serif italic text-3xl">Approvals</h1>
          {count > 0 && (
            <span className="text-xs font-mono font-bold px-2.5 py-1 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">
              {count}
            </span>
          )}
        </div>
        <button
          onClick={() => isUnlocked ? setApprovalToken(null) : setShowPinModal(true)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-colors border ${
            isUnlocked
              ? 'bg-emerald-600/20 border-emerald-500/30 text-emerald-400 hover:bg-emerald-600/30'
              : 'bg-zinc-600/20 border-zinc-500/30 text-zinc-400 hover:bg-zinc-600/30'
          }`}
        >
          {isUnlocked ? <Unlock className="w-3.5 h-3.5" /> : <Lock className="w-3.5 h-3.5" />}
          {isUnlocked ? 'Unlocked' : 'Locked'}
        </button>
      </div>

      {/* PIN Modal */}
      {showPinModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className={`p-6 rounded-2xl border ${border} ${isDark ? 'bg-zinc-900' : 'bg-white'} w-80 space-y-4`}>
            <div className="flex items-center gap-2">
              <Lock className="w-5 h-5 text-amber-400" />
              <h2 className="font-bold text-lg">Enter PIN to Approve</h2>
            </div>
            <p className="text-xs opacity-60">Unlocks approve/deny for 5 minutes.</p>
            <input
              type="password"
              autoFocus
              value={pinInput}
              onChange={(e) => setPinInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleUnlock()}
              placeholder="PIN"
              className={`w-full px-3 py-2 rounded-lg border text-center text-lg tracking-widest font-mono ${border} ${isDark ? 'bg-black/30' : 'bg-black/5'}`}
            />
            {pinError && <p className="text-xs text-rose-400">{pinError}</p>}
            <div className="flex gap-2">
              <button
                onClick={() => { setShowPinModal(false); setPinInput(''); setPinError(null) }}
                className={`flex-1 px-3 py-2 rounded-lg text-xs font-bold border ${border} hover:opacity-80`}
              >
                Cancel
              </button>
              <button
                onClick={handleUnlock}
                className="flex-1 px-3 py-2 rounded-lg text-xs font-bold bg-amber-600 hover:bg-amber-500 text-white"
              >
                Unlock
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Action result toast */}
      {actionResult && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className={`flex items-center gap-2 p-3 rounded-xl text-sm ${
            actionResult.decision === 'approved'
              ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400'
              : 'bg-rose-500/10 border border-rose-500/20 text-rose-400'
          }`}
        >
          {actionResult.decision === 'approved' ? <ShieldCheck className="w-4 h-4" /> : <ShieldX className="w-4 h-4" />}
          Request {actionResult.decision}
          {actionResult.sendStatus && <span className="font-mono">· send {actionResult.sendStatus}</span>}
          {actionResult.sparkReturnUrl && (
            <Link
              to={actionResult.sparkReturnUrl}
              className="ml-2 inline-flex items-center gap-1 rounded-md border border-current/30 px-2 py-1 text-xs font-bold hover:opacity-80"
            >
              Return to Spark send
            </Link>
          )}
        </motion.div>
      )}

      {loading && <p className="text-sm opacity-40">Loading...</p>}

      {error && (
        <div className="flex items-center gap-2 p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {!loading && !error && pending.length === 0 && (
        <div className={`flex flex-col items-center justify-center py-16 rounded-2xl border ${border} ${subtle}`}>
          <ShieldCheck className="w-10 h-10 text-emerald-500 mb-3" />
          <p className="text-sm font-medium opacity-60">No pending approvals</p>
        </div>
      )}

      {!loading && !error && (
        <section className={`p-5 rounded-2xl border ${border} ${subtle} space-y-3`}>
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-cyan-400" />
              <h2 className="text-sm font-bold">Browser execution history</h2>
            </div>
            <span className="text-[10px] font-mono uppercase opacity-50">
              {historyStart}-{historyEnd}{historyHasMore ? '+' : ''} recent
            </span>
          </div>

          <div className="grid gap-2 sm:grid-cols-[1fr_180px]">
              <input
                value={historyQuery}
                onChange={(event) => {
                  setHistoryOffset(0)
                  setHistoryQuery(event.target.value)
                }}
                placeholder="Search request, approval, host"
                className={`min-h-11 rounded-lg border px-3 text-xs outline-none ${border} ${isDark ? 'bg-black/20' : 'bg-white/60'}`}
              />
              <select
                value={historyEventType}
                onChange={(event) => {
                  setHistoryOffset(0)
                  setHistoryEventType(event.target.value)
                }}
                className={`min-h-11 rounded-lg border px-3 text-xs outline-none ${border} ${isDark ? 'bg-black/20' : 'bg-white/60'}`}
              >
                <option value="all">All events</option>
                <option value="approval_request">Approval requests</option>
                <option value="browser_run">Browser runs</option>
                <option value="browser_action">Browser actions</option>
              </select>
          </div>

          {historyError && (
            <div className="flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-400">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
              Browser history unavailable: {historyError}
            </div>
          )}

          {!historyError && browserHistory.length === 0 && !historyQuery.trim() && historyEventType === 'all' && (
            <p className="rounded-xl border border-dashed border-current/15 p-3 text-xs opacity-50">
              No browser approval or execution events recorded yet.
            </p>
          )}

          {!historyError && browserHistory.length === 0 && (historyQuery.trim() || historyEventType !== 'all') && (
            <p className="rounded-xl border border-dashed border-current/15 p-3 text-xs opacity-50">
              No browser history matches the current filter.
            </p>
          )}

          {!historyError && browserHistory.length > 0 && (
            <div className="space-y-2">
              <div className={`grid gap-2 rounded-xl border p-3 ${border} ${isDark ? 'bg-black/20' : 'bg-white/60'}`}>
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <ListChecks className="h-3.5 w-3.5 text-cyan-400" />
                    <span className="text-[11px] font-bold">History summary</span>
                  </div>
                  <span className="text-[10px] font-mono opacity-45">latest page only</span>
                </div>
                <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
                  {[
                    ['Approval requests', historySummary.approvalRequests],
                    ['Browser runs', historySummary.browserRuns],
                    ['Action events', historySummary.browserActions],
                    ['Audited actions', historySummary.auditedActions],
                    ['Screenshots', historySummary.screenshots],
                    ['Blocked or failed', historySummary.blockedOrFailed],
                  ].map(([label, value]) => (
                    <div key={label} className={`rounded-lg border px-3 py-2 ${border} ${isDark ? 'bg-white/5' : 'bg-[#141414]/5'}`}>
                      <div className="text-[10px] font-mono uppercase opacity-45">{label}</div>
                      <div className="mt-1 text-sm font-bold">{value}</div>
                    </div>
                  ))}
                </div>
              </div>
              {browserHistory.map((item) => (
                <div
                  key={`${item.request_id}-${item.event_type}-${item.status}-${item.created_at}`}
                  className={`rounded-xl border ${border} px-3 py-2.5 ${isDark ? 'bg-black/20' : 'bg-white/60'}`}
                >
                  <div className="flex items-start gap-2.5">
                    <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border ${border} ${isDark ? 'bg-white/5 text-cyan-300' : 'bg-cyan-50 text-cyan-700'}`}>
                      {historyEventIcon(item.event_type)}
                    </div>
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="flex items-start justify-between gap-3 flex-wrap">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-xs font-bold capitalize">
                              {eventLabel(item.event_type)}
                            </span>
                            <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${historyStatusClass(historyDisplayStatus(item))}`}>
                              {historyDisplayStatus(item)}
                            </span>
                            {item.risk_tier && tierBadge(item.risk_tier)}
                          </div>
                          <div className="flex items-center gap-x-3 gap-y-1 flex-wrap text-[11px] opacity-55">
                            <span>{new Date(item.created_at).toLocaleString()}</span>
                            <span className="font-mono">{item.selected_tool}</span>
                            {item.host && <span className="font-mono">host {item.host}</span>}
                          </div>
                        </div>
                        <span className="text-[10px] font-mono uppercase opacity-45">
                          {item.request_status}
                        </span>
                      </div>

                      <div className="flex items-center gap-1.5 flex-wrap text-[11px]">
                        <span className="inline-flex items-center gap-1 rounded-md border border-current/15 px-2 py-1">
                          <Eye className="h-3 w-3" />
                          {item.observation_count} obs
                        </span>
                        <span className="inline-flex items-center gap-1 rounded-md border border-current/15 px-2 py-1">
                          <Camera className="h-3 w-3" />
                          {item.screenshot_count} shots
                        </span>
                        <span className="inline-flex items-center gap-1 rounded-md border border-current/15 px-2 py-1">
                          <ListChecks className="h-3 w-3" />
                          {item.action_audit_count} audit
                        </span>
                        {item.event_type === 'browser_action' && (
                          <span className="inline-flex items-center gap-1 rounded-md border border-current/15 px-2 py-1 font-mono">
                            <MousePointerClick className="w-3 h-3 text-cyan-400 shrink-0" />
                            {item.action ?? 'action'}
                          </span>
                        )}
                        {item.elapsed_ms !== null && (
                          <span className="rounded-md border border-current/15 px-2 py-1 font-mono opacity-70">{item.elapsed_ms}ms</span>
                        )}
                      </div>

                      {item.blocked_reason && (
                        <div className="rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-400">
                          blocked: {item.blocked_reason}
                        </div>
                      )}

                      {((item.screenshot_refs?.length ?? 0) > 0 || item.evidence_path || item.audit_path) && (
                        <div className={`rounded-lg border px-2.5 py-2 ${border} ${isDark ? 'bg-white/[0.03]' : 'bg-zinc-50'}`}>
                          <div className="mb-1.5 flex items-center justify-between gap-2 text-[10px] font-mono uppercase opacity-55">
                            <span>Evidence preview</span>
                            <span>refs only</span>
                          </div>
                          <div className="flex flex-wrap gap-1.5 text-[11px]">
                            {(item.screenshot_refs ?? []).map((ref) => (
                              <span
                                key={ref}
                                title={ref}
                                className={`inline-flex items-center gap-2 rounded-lg border px-2 py-1 ${border}`}
                              >
                                <span className={`flex h-7 w-8 items-center justify-center rounded border ${border} ${isDark ? 'bg-cyan-400/10 text-cyan-300' : 'bg-cyan-50 text-cyan-700'}`}>
                                  <Camera className="h-3.5 w-3.5" />
                                </span>
                                <span className="min-w-0">
                                  <span className="block font-bold">Screenshot evidence</span>
                                  <span className="block font-mono opacity-60">{shortEvidenceRef(ref)}</span>
                                </span>
                              </span>
                            ))}
                            {item.evidence_path && (
                              <span
                                title={item.evidence_path}
                                className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono ${border}`}
                              >
                                <FileText className="h-3 w-3" />
                                Evidence bundle
                              </span>
                            )}
                            {item.audit_path && (
                              <span
                                title={item.audit_path}
                                className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono ${border}`}
                              >
                                <ListChecks className="h-3 w-3" />
                                Audit trail
                              </span>
                            )}
                          </div>
                        </div>
                      )}

                      <details className={`rounded-lg border px-2.5 py-1.5 text-[11px] ${border}`}>
                        <summary className="cursor-pointer select-none font-bold">Technical audit</summary>
                        <div className="mt-2 flex items-center gap-x-3 gap-y-1 flex-wrap opacity-60">
                          <span className="font-mono">request {shortId(item.request_id)}</span>
                          {item.approval_queue_id && (
                            <span className="font-mono">approval {shortId(item.approval_queue_id)}</span>
                          )}
                          {item.approval_hash_prefix && (
                            <span className="font-mono">hash {item.approval_hash_prefix}</span>
                          )}
                          <span className="font-mono">tool {item.selected_tool}</span>
                          {item.evidence_path && <span className="font-mono">evidence {item.evidence_path}</span>}
                          {item.audit_path && <span className="font-mono">audit {item.audit_path}</span>}
                        </div>
                      </details>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {!historyError && (historyOffset > 0 || historyHasMore) && (
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                disabled={historyOffset === 0}
                onClick={() => setHistoryOffset(Math.max(0, historyOffset - 12))}
                className={`min-h-10 rounded-lg border px-3 text-xs font-bold disabled:cursor-not-allowed disabled:opacity-40 ${border}`}
              >
                Previous
              </button>
              <button
                type="button"
                disabled={!historyHasMore}
                onClick={() => setHistoryOffset(historyOffset + 12)}
                className={`min-h-10 rounded-lg border px-3 text-xs font-bold disabled:cursor-not-allowed disabled:opacity-40 ${border}`}
              >
                Next
              </button>
            </div>
          )}
        </section>
      )}

      {/* Pending items */}
      {pending.map((item) => (
        <div key={item.id} className={`p-5 rounded-2xl border ${border} ${subtle} space-y-3`}>
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="space-y-1.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-bold font-mono">{item.description}</span>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                {tierBadge(item.risk_tier)}
                {item.action_class.map(ac => actionBadge(ac))}
                {item.overnight && (
                  <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border text-indigo-400 bg-indigo-500/15 border-indigo-500/30">
                    overnight
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Risk context */}
          <div className={`p-3 rounded-lg text-xs space-y-1 ${isDark ? 'bg-black/30' : 'bg-black/5'}`}>
            {item.action_class.map(ac => {
              const label = ACTION_LABELS[ac]
              return label ? (
                <div key={ac} className="flex items-start gap-2 opacity-70">
                  <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0 text-amber-400" />
                  <span><strong>{ac}:</strong> {label}</span>
                </div>
              ) : null
            })}
            {item.privacy && (
              <div className="flex items-start gap-2 opacity-80">
                <Fingerprint className="w-3 h-3 mt-0.5 shrink-0 text-emerald-400" />
                <span>
                  <strong>privacy packet:</strong> {item.privacy.action_count} local actions · {item.privacy.action_statuses.join(', ')}
                </span>
              </div>
            )}
            {item.spark && (
              <div className="flex items-start gap-2 opacity-80">
                <Sparkles className="w-3 h-3 mt-0.5 shrink-0 text-emerald-400" />
                <span>
                  <strong>spark draft:</strong> {item.spark.kind.replace('_', ' ')}
                  {item.spark.target_label ? ` · ${item.spark.target_label}` : ''}
                  {item.spark.outbox_recorded ? ` · outbox ${item.spark.outbox_status ?? 'recorded'}` : ' · no outbox'}
                </span>
              </div>
            )}
            {item.beacon && (
              <BeaconBrowserApprovalPanel beacon={item.beacon} isDark={isDark} />
            )}
          </div>

          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-3 text-xs opacity-40">
              <div className="flex items-center gap-1.5">
                <Clock className="w-3 h-3" />
                {new Date(item.requested_at).toLocaleString()}
              </div>
              <span className="font-mono">{timeLeft(item.expires_at)}</span>
              <span className="font-mono opacity-60">by {item.actor_sub}</span>
            </div>
            <div
              className={`flex items-center gap-2 flex-wrap ${
                item.beacon
                  ? `rounded-xl border p-2 ${isDark ? 'border-emerald-400/20 bg-emerald-500/5' : 'border-emerald-300 bg-emerald-50'}`
                  : ''
              }`}
            >
              {item.beacon && (
                <div className={`mr-1 text-[11px] font-mono ${isDark ? 'text-emerald-100/75' : 'text-emerald-950/70'}`}>
                  Decision applies to the reviewed Beacon browser plan
                </div>
              )}
              {item.privacy && (
                <Link
                  to={`/privacy?case=${item.privacy.case_id}&approval=${item.id}`}
                  className={`flex items-center gap-1.5 px-4 py-1.5 rounded-lg border text-xs font-bold transition-colors ${border} hover:opacity-80`}
                >
                  <Fingerprint className="w-3.5 h-3.5" />
                  Review packet
                </Link>
              )}
              {item.spark && (
                <Link
                  to={buildSparkReviewUrl(item)}
                  className={`flex items-center gap-1.5 px-4 py-1.5 rounded-lg border text-xs font-bold transition-colors ${border} hover:opacity-80`}
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  Review Spark
                </Link>
              )}
              {canApproveAndSendSpark(item) && (
                <button
                  disabled={acting === item.id}
                  onClick={() => handleApproveAndSendSpark(item)}
                  className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-bold bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-40"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  Approve + Send
                </button>
              )}
              <button
                disabled={acting === item.id}
                onClick={() => handleDecide(item, 'approved')}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-bold bg-emerald-600 hover:bg-emerald-500 text-white transition-colors disabled:opacity-40"
              >
                <ShieldCheck className="w-3.5 h-3.5" />
                {item.beacon ? 'Approve plan' : 'Approve'}
              </button>
              <button
                disabled={acting === item.id}
                onClick={() => handleDecide(item, 'denied')}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-bold bg-rose-600 hover:bg-rose-500 text-white transition-colors disabled:opacity-40"
              >
                <ShieldX className="w-3.5 h-3.5" />
                {item.beacon ? 'Deny plan' : 'Deny'}
              </button>
            </div>
          </div>
        </div>
      ))}
    </motion.div>
  )
}
