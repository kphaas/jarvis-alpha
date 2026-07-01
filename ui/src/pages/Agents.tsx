import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import {
  Activity,
  AlertTriangle,
  Bell,
  Bot,
  CheckCircle2,
  Clock3,
  Pause,
  Play,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react'
import { apiFetch, apiJson } from '../lib/apiFetch'
import { useAppStore } from '../store'

interface AgentStatus {
  agent_id: string
  display_name: string
  status: string
  enabled: boolean
  risk_tier: string
  cadence: string | null
  launch_label: string | null
  mattermost_channel_key: string | null
  last_run_status: string | null
  last_run_at: string | null
  last_event_type: string | null
  last_event_severity: string | null
  last_event_title: string | null
  last_event_at: string | null
}

interface Agent {
  agent_id: string
  display_name: string
  purpose: string
  risk_tier: string
  status: string
  enabled: boolean
  owner: string
  cadence: string | null
  launch_label: string | null
  allowed_skills: string[]
  allowed_scopes: string[]
  cost_daily_cap_usd: number | null
  model_policy: Record<string, unknown>
  approval_policy: Record<string, unknown>
  metadata: Record<string, unknown>
}

interface AgentEvent {
  id: string
  event_type: string
  severity: string
  title: string
  message: string
  channel_key: string
  notification_status: string
  created_at: string
}

interface AgentRun {
  id: string
  status: string
  trigger_type: string
  started_at: string | null
  completed_at: string | null
  cost_usd: number
  error_text: string | null
  workspace_backend: string
  workspace_root: string | null
  policy_labels: string[]
  approval_scope: string | null
  retention_class: string
  created_at: string
}

interface AgentRunArtifact {
  artifact_id: string
  run_id: string
  relative_path: string
  kind: string
  content_type: string
  size_bytes: number
  created_at: string
  sha256: string
  policy_labels: string[]
}

interface AgentStatusList {
  count: number
  agents: AgentStatus[]
}

interface AgentList {
  count: number
  agents: Agent[]
}

interface AgentEventList {
  count: number
  events: AgentEvent[]
}

interface AgentRunList {
  count: number
  runs: AgentRun[]
}

interface AgentRunArtifactList {
  count: number
  artifacts: AgentRunArtifact[]
}

interface AgentManualRun {
  agent_id: string
  executed: boolean
  run_id: string | null
  status: string | null
  trace_id: string | null
  skipped_reason: string | null
  error_text: string | null
}

interface ApprovalGateResponse {
  detail: 'approval_required'
  queue_id: string
  tier: string
  action_class: string
}

const REFRESH_MS = 30_000

function statusColor(status: string, enabled: boolean) {
  if (!enabled) return 'border-zinc-400/30 bg-zinc-500/10 text-zinc-400'
  if (status === 'active') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
  if (status === 'planned') return 'border-sky-500/30 bg-sky-500/10 text-sky-400'
  return 'border-amber-500/30 bg-amber-500/10 text-amber-400'
}

function severityColor(severity: string) {
  if (severity === 'critical' || severity === 'error') return 'text-rose-400'
  if (severity === 'warning' || severity === 'needs_input') return 'text-amber-400'
  return 'text-emerald-400'
}

function timeText(value: string | null) {
  if (!value) return 'Never'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function compactJson(value: Record<string, unknown>) {
  const entries = Object.entries(value)
  if (!entries.length) return 'None'
  return entries.map(([key, val]) => `${key}: ${String(val)}`).join(' / ')
}

function bytesText(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

export default function Agents() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-white/[0.04]' : 'bg-[#141414]/[0.03]'
  const strongPanel = isDark ? 'bg-zinc-950/50' : 'bg-white'
  const muted = isDark ? 'text-zinc-400' : 'text-zinc-500'

  const [statuses, setStatuses] = useState<AgentStatus[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [runs, setRuns] = useState<AgentRun[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [artifacts, setArtifacts] = useState<AgentRunArtifact[]>([])
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [artifactLoading, setArtifactLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [artifactError, setArtifactError] = useState<string | null>(null)
  const [acting, setActing] = useState<string | null>(null)
  const [runningNow, setRunningNow] = useState<string | null>(null)
  const [runResult, setRunResult] = useState<AgentManualRun | null>(null)
  const [approvalNotice, setApprovalNotice] = useState<ApprovalGateResponse | null>(null)

  const load = useCallback(async () => {
    try {
      const [statusRes, agentRes] = await Promise.all([
        apiJson<AgentStatusList>('/v1/agents/status'),
        apiJson<AgentList>('/v1/agents'),
      ])
      setStatuses(statusRes.agents)
      setAgents(agentRes.agents)
      setSelectedId((current) => current ?? statusRes.agents[0]?.agent_id ?? null)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load agents')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadDetails = useCallback(async (agentId: string) => {
    setDetailLoading(true)
    try {
      const [eventRes, runRes] = await Promise.all([
        apiJson<AgentEventList>(`/v1/agents/${agentId}/events?limit=12`),
        apiJson<AgentRunList>(`/v1/agents/${agentId}/runs?limit=8`),
      ])
      setEvents(eventRes.events)
      setRuns(runRes.runs)
      setSelectedRunId((current) => {
        if (current && runRes.runs.some((run) => run.id === current)) return current
        return runRes.runs[0]?.id ?? null
      })
      setArtifactError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load agent details')
    } finally {
      setDetailLoading(false)
    }
  }, [])

  const loadArtifacts = useCallback(async (runId: string) => {
    setArtifactLoading(true)
    try {
      const artifactRes = await apiJson<AgentRunArtifactList>(`/v1/agent-runs/${runId}/artifacts`)
      setArtifacts(artifactRes.artifacts)
      setArtifactError(null)
    } catch (err) {
      setArtifacts([])
      setArtifactError(err instanceof Error ? err.message : 'Failed to load artifacts')
    } finally {
      setArtifactLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => clearInterval(id)
  }, [load])

  useEffect(() => {
    if (selectedId) loadDetails(selectedId)
  }, [loadDetails, selectedId])

  useEffect(() => {
    if (!selectedRunId) {
      setArtifacts([])
      setArtifactError(null)
      return
    }
    loadArtifacts(selectedRunId)
  }, [loadArtifacts, selectedRunId])

  const selectedStatus = useMemo(
    () => statuses.find((agent) => agent.agent_id === selectedId) ?? null,
    [statuses, selectedId]
  )
  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.agent_id === selectedId) ?? null,
    [agents, selectedId]
  )
  const selectedRun = useMemo(
    () => runs.find((run) => run.id === selectedRunId) ?? null,
    [runs, selectedRunId]
  )

  const stats = useMemo(() => {
    const enabled = statuses.filter((agent) => agent.enabled).length
    const active = statuses.filter((agent) => agent.status === 'active').length
    const alerting = statuses.filter((agent) =>
      ['critical', 'error', 'warning', 'needs_input'].includes(agent.last_event_severity ?? '')
    ).length
    return { enabled, active, alerting }
  }, [statuses])

  const setEnabled = async (agentId: string, enabled: boolean) => {
    setActing(agentId)
    setRunResult(null)
    setApprovalNotice(null)
    try {
      const response = await postAgentControl<Agent>(`/v1/agents/${agentId}/${enabled ? 'enable' : 'disable'}`)
      if (response.approval) {
        setApprovalNotice(response.approval)
        return
      }
      await load()
      await loadDetails(agentId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Agent control failed')
    } finally {
      setActing(null)
    }
  }

  const runNow = async (agentId: string) => {
    setRunningNow(agentId)
    setRunResult(null)
    setApprovalNotice(null)
    try {
      const response = await postAgentControl<AgentManualRun>(`/v1/agents/${agentId}/run`)
      if (response.approval) {
        setApprovalNotice(response.approval)
      } else if (response.data) {
        setRunResult(response.data)
        if (response.data.run_id) setSelectedRunId(response.data.run_id)
      }
      await load()
      await loadDetails(agentId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Manual run failed')
    } finally {
      setRunningNow(null)
    }
  }

  const canRunSelected =
    selectedAgent?.enabled === true &&
    selectedAgent.status === 'active' &&
    selectedAgent.metadata.manual_run_enabled === true

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="space-y-5 max-w-7xl">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <Bot className="w-6 h-6 text-sky-400" />
          <h1 className="text-2xl font-bold">Agents</h1>
        </div>
        <button
          onClick={load}
          title="Refresh"
          className={`min-h-11 px-3 rounded-lg border ${border} ${panel} hover:opacity-80 flex items-center gap-2 text-sm font-semibold`}
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {error && (
        <div className="min-h-11 flex items-center gap-2 rounded-lg border border-rose-500/25 bg-rose-500/10 px-3 text-sm text-rose-400">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {runResult && (
        <div className="min-h-11 flex items-center gap-2 rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-3 text-sm text-emerald-400">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          Manual run {runResult.status ?? 'queued'} for {runResult.agent_id}
        </div>
      )}

      {approvalNotice && (
        <div className="min-h-11 flex items-center gap-2 rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 text-sm text-amber-400">
          <ShieldCheck className="w-4 h-4 shrink-0" />
          Approval queued: {approvalNotice.tier} / {approvalNotice.queue_id}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className={`rounded-lg border ${border} ${panel} p-4 min-h-24`}>
          <div className={`text-xs font-semibold ${muted}`}>Enabled</div>
          <div className="mt-2 flex items-center gap-2 text-2xl font-bold">
            <CheckCircle2 className="w-5 h-5 text-emerald-400" />
            {stats.enabled}
          </div>
        </div>
        <div className={`rounded-lg border ${border} ${panel} p-4 min-h-24`}>
          <div className={`text-xs font-semibold ${muted}`}>Active</div>
          <div className="mt-2 flex items-center gap-2 text-2xl font-bold">
            <Activity className="w-5 h-5 text-sky-400" />
            {stats.active}
          </div>
        </div>
        <div className={`rounded-lg border ${border} ${panel} p-4 min-h-24`}>
          <div className={`text-xs font-semibold ${muted}`}>Attention</div>
          <div className="mt-2 flex items-center gap-2 text-2xl font-bold">
            <Bell className="w-5 h-5 text-amber-400" />
            {stats.alerting}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[420px_1fr] gap-4">
        <section className={`rounded-lg border ${border} ${strongPanel} overflow-hidden`}>
          <div className={`px-4 py-3 border-b ${border} flex items-center justify-between`}>
            <div className="font-semibold">Registry</div>
            <div className={`text-xs ${muted}`}>{statuses.length} total</div>
          </div>
          <div className="divide-y divide-zinc-500/10">
            {loading && Array.from({ length: 6 }).map((_, index) => (
              <div key={index} className="p-4 animate-pulse">
                <div className="h-4 w-40 rounded bg-zinc-500/20" />
                <div className="mt-3 h-3 w-64 rounded bg-zinc-500/10" />
              </div>
            ))}
            {!loading && statuses.map((agent) => (
              <button
                key={agent.agent_id}
                onClick={() => setSelectedId(agent.agent_id)}
                className={`w-full min-h-24 text-left p-4 hover:bg-sky-500/5 transition-colors ${
                  selectedId === agent.agent_id ? 'bg-sky-500/10' : ''
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-semibold truncate">{agent.display_name}</div>
                    <div className={`mt-1 text-xs ${muted}`}>{agent.agent_id}</div>
                  </div>
                  <span className={`shrink-0 rounded border px-2 py-1 text-xs font-semibold ${statusColor(agent.status, agent.enabled)}`}>
                    {agent.enabled ? agent.status : 'disabled'}
                  </span>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                  <span className={muted}>Risk {agent.risk_tier}</span>
                  <span className={muted}>Cadence {agent.cadence ?? 'manual'}</span>
                </div>
              </button>
            ))}
          </div>
        </section>

        <section className={`rounded-lg border ${border} ${strongPanel} overflow-hidden min-h-[620px]`}>
          {!selectedAgent || !selectedStatus ? (
            <div className={`p-6 text-sm ${muted}`}>No agent selected.</div>
          ) : (
            <>
              <div className={`px-4 py-3 border-b ${border} flex items-center justify-between gap-3 flex-wrap`}>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-bold">{selectedAgent.display_name}</h2>
                    <span className={`rounded border px-2 py-1 text-xs font-semibold ${statusColor(selectedAgent.status, selectedAgent.enabled)}`}>
                      {selectedAgent.enabled ? selectedAgent.status : 'disabled'}
                    </span>
                  </div>
                  <div className={`mt-1 text-sm ${muted}`}>{selectedAgent.purpose}</div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    disabled={!canRunSelected || runningNow === selectedAgent.agent_id}
                    onClick={() => runNow(selectedAgent.agent_id)}
                    title="Run now"
                    className="min-h-11 px-3 rounded-lg border border-sky-500/30 bg-sky-500/10 text-sky-400 flex items-center gap-2 text-sm font-semibold disabled:opacity-40"
                  >
                    <Play className="w-4 h-4" />
                    Run Now
                  </button>
                  <button
                    disabled={acting === selectedAgent.agent_id}
                    onClick={() => setEnabled(selectedAgent.agent_id, !selectedAgent.enabled)}
                    title={selectedAgent.enabled ? 'Disable agent' : 'Enable agent'}
                    className={`min-h-11 px-3 rounded-lg border flex items-center gap-2 text-sm font-semibold disabled:opacity-40 ${
                      selectedAgent.enabled
                        ? 'border-amber-500/30 bg-amber-500/10 text-amber-400'
                        : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                    }`}
                  >
                    {selectedAgent.enabled ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                    {selectedAgent.enabled ? 'Disable' : 'Enable'}
                  </button>
                </div>
              </div>

              <div className="p-4 space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                  <InfoCell label="Last Run" value={timeText(selectedStatus.last_run_at)} icon={<Clock3 className="w-4 h-4" />} muted={muted} border={border} panel={panel} />
                  <InfoCell label="Run Status" value={selectedStatus.last_run_status ?? 'None'} icon={<Activity className="w-4 h-4" />} muted={muted} border={border} panel={panel} />
                  <InfoCell label="Channel" value={selectedStatus.mattermost_channel_key ?? 'None'} icon={<Bell className="w-4 h-4" />} muted={muted} border={border} panel={panel} />
                  <InfoCell label="Policy" value={selectedAgent.risk_tier} icon={<ShieldCheck className="w-4 h-4" />} muted={muted} border={border} panel={panel} />
                </div>

                <div className={`rounded-lg border ${border} ${panel} p-4`}>
                  <div className="text-sm font-semibold">Allowed Skills</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {selectedAgent.allowed_skills.length ? selectedAgent.allowed_skills.map((skill) => (
                      <span key={skill} className={`rounded border ${border} px-2 py-1 text-xs font-mono`}>
                        {skill}
                      </span>
                    )) : <span className={`text-sm ${muted}`}>None</span>}
                  </div>
                </div>

                <div className={`rounded-lg border ${border} ${panel} p-4`}>
                  <div className="text-sm font-semibold">Policy</div>
                  <div className={`mt-2 text-sm ${muted}`}>{compactJson(selectedAgent.approval_policy)}</div>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div className={`rounded-lg border ${border} ${panel} overflow-hidden`}>
                    <div className={`px-4 py-3 border-b ${border} font-semibold`}>Events</div>
                    <div className="divide-y divide-zinc-500/10 min-h-72">
                      {detailLoading && <div className={`p-4 text-sm ${muted}`}>Loading...</div>}
                      {!detailLoading && events.length === 0 && <div className={`p-4 text-sm ${muted}`}>No events.</div>}
                      {!detailLoading && events.map((event) => (
                        <div key={event.id} className="p-4 min-h-20">
                          <div className="flex items-start justify-between gap-2">
                            <div className="font-semibold text-sm">{event.title}</div>
                            <span className={`text-xs font-semibold ${severityColor(event.severity)}`}>{event.severity}</span>
                          </div>
                          <div className={`mt-1 text-xs ${muted}`}>{event.event_type} / {event.notification_status}</div>
                          <div className={`mt-2 text-sm ${muted}`}>{timeText(event.created_at)}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className={`rounded-lg border ${border} ${panel} overflow-hidden`}>
                    <div className={`px-4 py-3 border-b ${border} font-semibold`}>Runs</div>
                    <div className="divide-y divide-zinc-500/10 min-h-72">
                      {detailLoading && <div className={`p-4 text-sm ${muted}`}>Loading...</div>}
                      {!detailLoading && runs.length === 0 && <div className={`p-4 text-sm ${muted}`}>No runs.</div>}
                      {!detailLoading && runs.map((run) => (
                        <button
                          key={run.id}
                          type="button"
                          onClick={() => setSelectedRunId(run.id)}
                          className={`w-full text-left p-4 min-h-20 hover:bg-sky-500/5 transition-colors ${
                            selectedRunId === run.id ? 'bg-sky-500/10' : ''
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="font-semibold text-sm">{run.trigger_type}</div>
                            <span className={`text-xs font-semibold ${run.status === 'failed' ? 'text-rose-400' : 'text-emerald-400'}`}>{run.status}</span>
                          </div>
                          <div className={`mt-1 text-xs ${muted}`}>${run.cost_usd.toFixed(4)} / {timeText(run.created_at)}</div>
                          <div className="mt-2 flex flex-wrap gap-2">
                            <span className={`rounded border ${border} px-2 py-1 text-[11px] font-semibold ${muted}`}>
                              {run.workspace_root ? `${run.workspace_backend} workspace` : 'no workspace'}
                            </span>
                            <span className={`rounded border ${border} px-2 py-1 text-[11px] font-semibold ${muted}`}>
                              {run.retention_class}
                            </span>
                            {run.approval_scope && (
                              <span className={`rounded border ${border} px-2 py-1 text-[11px] font-semibold ${muted}`}>
                                {run.approval_scope}
                              </span>
                            )}
                          </div>
                          {run.error_text && <div className="mt-2 text-xs text-rose-400">{run.error_text}</div>}
                        </button>
                      ))}
                    </div>
                    {selectedRun && (
                      <div className={`border-t ${border} p-4 space-y-4`}>
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <div className="text-sm font-semibold">Run Workspace</div>
                            <div className={`mt-1 text-xs ${muted}`}>{selectedRun.id}</div>
                          </div>
                          <span className={`rounded border ${border} px-2 py-1 text-[11px] font-semibold ${muted}`}>
                            {selectedRun.status}
                          </span>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          <InfoCell
                            label="Backend"
                            value={selectedRun.workspace_backend}
                            icon={<Bot className="w-4 h-4" />}
                            muted={muted}
                            border={border}
                            panel={panel}
                          />
                          <InfoCell
                            label="Retention"
                            value={selectedRun.retention_class}
                            icon={<Clock3 className="w-4 h-4" />}
                            muted={muted}
                            border={border}
                            panel={panel}
                          />
                          <InfoCell
                            label="Approval Scope"
                            value={selectedRun.approval_scope ?? 'None'}
                            icon={<ShieldCheck className="w-4 h-4" />}
                            muted={muted}
                            border={border}
                            panel={panel}
                          />
                          <InfoCell
                            label="Policies"
                            value={selectedRun.policy_labels.join(', ') || 'None'}
                            icon={<Bell className="w-4 h-4" />}
                            muted={muted}
                            border={border}
                            panel={panel}
                          />
                        </div>

                        <div className={`rounded-lg border ${border} ${panel} p-4`}>
                          <div className="text-sm font-semibold">Workspace Root</div>
                          <div className={`mt-2 text-xs break-all ${muted}`}>
                            {selectedRun.workspace_root ?? 'Not initialized'}
                          </div>
                        </div>

                        <div className={`rounded-lg border ${border} ${panel} overflow-hidden`}>
                          <div className={`px-4 py-3 border-b ${border} flex items-center justify-between gap-3`}>
                            <div className="text-sm font-semibold">Artifacts</div>
                            <div className={`text-xs ${muted}`}>{artifacts.length} items</div>
                          </div>
                          <div className="divide-y divide-zinc-500/10">
                            {artifactLoading && <div className={`p-4 text-sm ${muted}`}>Loading artifacts...</div>}
                            {!artifactLoading && artifactError && <div className="p-4 text-sm text-rose-400">{artifactError}</div>}
                            {!artifactLoading && !artifactError && artifacts.length === 0 && (
                              <div className={`p-4 text-sm ${muted}`}>No artifacts recorded for this run.</div>
                            )}
                            {!artifactLoading && !artifactError && artifacts.map((artifact) => (
                              <div key={artifact.artifact_id} className="p-4 min-h-20">
                                <div className="flex items-start justify-between gap-3">
                                  <div className="min-w-0">
                                    <div className="text-sm font-semibold break-all">{artifact.relative_path}</div>
                                    <div className={`mt-1 text-xs ${muted}`}>
                                      {artifact.kind} / {artifact.content_type}
                                    </div>
                                  </div>
                                  <div className={`text-xs ${muted}`}>{bytesText(artifact.size_bytes)}</div>
                                </div>
                                <div className={`mt-2 text-xs ${muted}`}>{timeText(artifact.created_at)}</div>
                                {artifact.policy_labels.length > 0 && (
                                  <div className="mt-2 flex flex-wrap gap-2">
                                    {artifact.policy_labels.map((label) => (
                                      <span key={label} className={`rounded border ${border} px-2 py-1 text-[11px] font-semibold ${muted}`}>
                                        {label}
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </motion.div>
  )
}

async function postAgentControl<T>(path: string): Promise<{ data?: T; approval?: ApprovalGateResponse }> {
  const res = await apiFetch(path, { method: 'POST' })
  const body = await parseJsonBody(res)
  if (res.ok) {
    return { data: body as T }
  }
  if (res.status === 403 && isApprovalGateResponse(body)) {
    return { approval: body }
  }
  const detail = body && typeof body === 'object' && 'detail' in body ? String(body.detail) : `HTTP ${res.status}`
  throw new Error(detail)
}

async function parseJsonBody(res: Response): Promise<unknown> {
  try {
    return await res.json()
  } catch {
    return null
  }
}

function isApprovalGateResponse(value: unknown): value is ApprovalGateResponse {
  return (
    typeof value === 'object' &&
    value !== null &&
    (value as { detail?: unknown }).detail === 'approval_required' &&
    typeof (value as { queue_id?: unknown }).queue_id === 'string' &&
    typeof (value as { tier?: unknown }).tier === 'string' &&
    typeof (value as { action_class?: unknown }).action_class === 'string'
  )
}

function InfoCell({
  label,
  value,
  icon,
  muted,
  border,
  panel,
}: {
  label: string
  value: string
  icon: ReactNode
  muted: string
  border: string
  panel: string
}) {
  return (
    <div className={`rounded-lg border ${border} ${panel} p-3 min-h-24`}>
      <div className={`flex items-center gap-2 text-xs font-semibold ${muted}`}>
        {icon}
        {label}
      </div>
      <div className="mt-2 text-sm font-semibold break-words">{value}</div>
    </div>
  )
}
