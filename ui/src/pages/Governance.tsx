import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import {
  AlertTriangle,
  Database,
  GitCompareArrows,
  KeyRound,
  Lock,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  SquareActivity,
  Workflow,
} from 'lucide-react'
import { apiJson } from '../lib/apiFetch'
import { uniqueSorted, type Agent, type AgentList, type Skill, type SkillList } from '../lib/registryTypes'
import { useAppStore } from '../store'

function tierColor(tier: string) {
  if (tier === 'T5') return 'border-rose-500/30 bg-rose-500/10 text-rose-400'
  if (tier === 'T4') return 'border-amber-500/30 bg-amber-500/10 text-amber-400'
  if (tier === 'T3') return 'border-sky-500/30 bg-sky-500/10 text-sky-400'
  return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
}

function statusColor(status: string, enabled?: boolean) {
  if (enabled === false) return 'border-zinc-400/30 bg-zinc-500/10 text-zinc-400'
  if (status === 'active') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
  if (status === 'planned') return 'border-sky-500/30 bg-sky-500/10 text-sky-400'
  return 'border-zinc-500/30 bg-zinc-500/10 text-zinc-400'
}

export default function Governance() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-white/[0.04]' : 'bg-[#141414]/[0.03]'
  const strongPanel = isDark ? 'bg-zinc-950/50' : 'bg-white'
  const muted = isDark ? 'text-zinc-400' : 'text-zinc-500'

  const [skills, setSkills] = useState<Skill[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [skillRes, agentRes] = await Promise.all([
        apiJson<SkillList>('/v1/skills'),
        apiJson<AgentList>('/v1/agents'),
      ])
      setSkills(skillRes.skills)
      setAgents(agentRes.agents)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load governance')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const highRiskSkills = useMemo(
    () => skills.filter((skill) => ['T4', 'T5'].includes(skill.approval_tier)),
    [skills]
  )
  const bodySkills = useMemo(() => skills.filter((skill) => skill.body_access), [skills])
  const missingConsumers = useMemo(
    () => skills.filter((skill) => !agents.some((agent) => agent.allowed_skills.includes(skill.name))),
    [skills, agents]
  )
  const activeAgents = useMemo(() => agents.filter((agent) => agent.status === 'active'), [agents])
  const enabledAgents = useMemo(() => agents.filter((agent) => agent.enabled), [agents])
  const domains = useMemo(() => uniqueSorted(skills.map((skill) => skill.domain)), [skills])
  const manifestSkills = useMemo(
    () => skills.filter((skill) => skill.manifest?.manifest_version === 1),
    [skills]
  )
  const missingManifest = useMemo(
    () => skills.filter((skill) => skill.manifest?.manifest_version !== 1),
    [skills]
  )
  const sideEffectRows = useMemo(() => {
    return uniqueSorted(manifestSkills.map((skill) => skill.manifest?.side_effect_class ?? 'unknown')).map((effect) => ({
      label: effect,
      count: manifestSkills.filter((skill) => skill.manifest?.side_effect_class === effect).length,
    }))
  }, [manifestSkills])
  const dataClassRows = useMemo(() => {
    return uniqueSorted(manifestSkills.map((skill) => skill.manifest?.data_classification ?? 'unknown')).map((classification) => ({
      label: classification,
      count: manifestSkills.filter((skill) => skill.manifest?.data_classification === classification).length,
    }))
  }, [manifestSkills])

  const scopeRows = useMemo(() => {
    return uniqueSorted(skills.map((skill) => skill.scope)).map((scope) => {
      const scopeSkills = skills.filter((skill) => skill.scope === scope)
      const allowedAgents = agents.filter((agent) => agent.allowed_scopes.includes(scope))
      return {
        scope,
        skills: scopeSkills.length,
        agents: allowedAgents.length,
        highestTier: highestTier(scopeSkills),
      }
    })
  }, [skills, agents])

  const matrixRows = useMemo(() => {
    return agents.map((agent) => ({
      agent,
      activeSkills: agent.allowed_skills.filter((skillName) =>
        skills.some((skill) => skill.name === skillName && skill.status === 'active')
      ).length,
      plannedSkills: agent.allowed_skills.filter((skillName) =>
        skills.some((skill) => skill.name === skillName && skill.status === 'planned')
      ).length,
      unknownSkills: agent.allowed_skills.filter((skillName) =>
        !skills.some((skill) => skill.name === skillName)
      ).length,
      highRiskSkills: agent.allowed_skills.filter((skillName) =>
        skills.some((skill) => skill.name === skillName && ['T4', 'T5'].includes(skill.approval_tier))
      ).length,
    }))
  }, [agents, skills])

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="space-y-5 max-w-7xl">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <ShieldCheck className="w-6 h-6 text-emerald-400" />
          <h1 className="text-2xl font-bold">Governance</h1>
        </div>
        <button
          onClick={load}
          title="Refresh"
          className={`min-h-11 px-3 rounded-lg border ${border} ${panel} hover:opacity-80 flex items-center gap-2 text-sm font-semibold`}
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="min-h-11 flex items-center gap-2 rounded-lg border border-rose-500/25 bg-rose-500/10 px-3 text-sm text-rose-400">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <Stat label="Registered Skills" value={skills.length} icon={<Database className="w-5 h-5 text-sky-400" />} border={border} panel={panel} muted={muted} />
        <Stat label="Registered Agents" value={agents.length} icon={<Workflow className="w-5 h-5 text-emerald-400" />} border={border} panel={panel} muted={muted} />
        <Stat label="Body Access" value={bodySkills.length} icon={<Lock className="w-5 h-5 text-amber-400" />} border={border} panel={panel} muted={muted} />
        <Stat label="T4/T5 Skills" value={highRiskSkills.length} icon={<ShieldAlert className="w-5 h-5 text-rose-400" />} border={border} panel={panel} muted={muted} />
        <Stat label="Manifest v1" value={manifestSkills.length} icon={<SquareActivity className="w-5 h-5 text-emerald-400" />} border={border} panel={panel} muted={muted} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_420px] gap-4">
        <section className={`rounded-lg border ${border} ${strongPanel} overflow-hidden`}>
          <div className={`px-4 py-3 border-b ${border} flex items-center justify-between`}>
            <div className="font-semibold flex items-center gap-2">
              <GitCompareArrows className="w-4 h-4" />
              Agent Skill Matrix
            </div>
            <div className={`text-xs ${muted}`}>{enabledAgents.length} enabled / {activeAgents.length} active</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className={`text-xs ${muted}`}>
                <tr className={`border-b ${border}`}>
                  <th className="text-left font-semibold p-3">Agent</th>
                  <th className="text-left font-semibold p-3">State</th>
                  <th className="text-left font-semibold p-3">Risk</th>
                  <th className="text-right font-semibold p-3">Active Skills</th>
                  <th className="text-right font-semibold p-3">Planned</th>
                  <th className="text-right font-semibold p-3">High Risk</th>
                  <th className="text-right font-semibold p-3">Unknown</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-500/10">
                {matrixRows.length === 0 && (
                  <tr>
                    <td colSpan={7} className={`p-4 text-sm ${muted}`}>
                      No agents loaded.
                    </td>
                  </tr>
                )}
                {matrixRows.map((row) => (
                  <tr key={row.agent.agent_id} className="hover:bg-emerald-500/5">
                    <td className="p-3">
                      <div className="font-semibold">{row.agent.display_name}</div>
                      <div className={`text-xs ${muted}`}>{row.agent.agent_id}</div>
                    </td>
                    <td className="p-3">
                      <span className={`rounded border px-2 py-1 text-xs font-semibold ${statusColor(row.agent.status, row.agent.enabled)}`}>
                        {row.agent.enabled ? row.agent.status : 'disabled'}
                      </span>
                    </td>
                    <td className="p-3">
                      <span className={`rounded border px-2 py-1 text-xs font-semibold ${tierColor(row.agent.risk_tier)}`}>{row.agent.risk_tier}</span>
                    </td>
                    <td className="p-3 text-right font-mono">{row.activeSkills}</td>
                    <td className="p-3 text-right font-mono">{row.plannedSkills}</td>
                    <td className="p-3 text-right font-mono">{row.highRiskSkills}</td>
                    <td className={`p-3 text-right font-mono ${row.unknownSkills ? 'text-rose-400' : ''}`}>{row.unknownSkills}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className={`rounded-lg border ${border} ${strongPanel} overflow-hidden`}>
          <div className={`px-4 py-3 border-b ${border} font-semibold`}>Governance Coverage</div>
          <div className="p-4 space-y-3">
            <Coverage label="Skill registry" ok={skills.length > 0} border={border} panel={panel} muted={muted} />
            <Coverage label="Agent registry" ok={agents.length > 0} border={border} panel={panel} muted={muted} />
            <Coverage label="Policy gate" ok={true} border={border} panel={panel} muted={muted} />
            <Coverage label="Approval routing" ok={highRiskSkills.length > 0} border={border} panel={panel} muted={muted} />
            <Coverage label="Body-access rail" ok={bodySkills.length > 0} border={border} panel={panel} muted={muted} />
            <Coverage label="Skill Manifest v1" ok={skills.length > 0 && missingManifest.length === 0} border={border} panel={panel} muted={muted} />
            <Coverage label="Governance audit ledger" ok={false} border={border} panel={panel} muted={muted} />
            <Coverage label="T5 policy editor" ok={false} border={border} panel={panel} muted={muted} />
          </div>
        </section>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <Panel title="High-Risk Skills" count={highRiskSkills.length} border={border} panel={strongPanel} muted={muted}>
          {highRiskSkills.map((skill) => (
            <SkillLine key={skill.name} skill={skill} muted={muted} />
          ))}
        </Panel>
        <Panel title="Body-Access Skills" count={bodySkills.length} border={border} panel={strongPanel} muted={muted}>
          {bodySkills.map((skill) => (
            <SkillLine key={skill.name} skill={skill} muted={muted} />
          ))}
        </Panel>
        <Panel title="No Agent Consumer" count={missingConsumers.length} border={border} panel={strongPanel} muted={muted}>
          {missingConsumers.slice(0, 12).map((skill) => (
            <SkillLine key={skill.name} skill={skill} muted={muted} />
          ))}
        </Panel>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <ManifestBreakdown title="Data Classifications" rows={dataClassRows} border={border} panel={strongPanel} muted={muted} />
        <ManifestBreakdown title="Side Effects" rows={sideEffectRows} border={border} panel={strongPanel} muted={muted} />
      </div>

      <section className={`rounded-lg border ${border} ${strongPanel} overflow-hidden`}>
        <div className={`px-4 py-3 border-b ${border} flex items-center justify-between`}>
          <div className="font-semibold flex items-center gap-2">
            <KeyRound className="w-4 h-4" />
            Scope Coverage
          </div>
          <div className={`text-xs ${muted}`}>{domains.length} domains</div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 p-4">
          {scopeRows.length === 0 && (
            <div className={`text-sm ${muted}`}>No scopes loaded.</div>
          )}
          {scopeRows.map((row) => (
            <div key={row.scope} className={`rounded-lg border ${border} ${panel} p-3 min-h-28`}>
              <div className="flex items-start justify-between gap-2">
                <div className="font-mono text-sm break-all">{row.scope}</div>
                <span className={`rounded border px-2 py-1 text-xs font-semibold ${tierColor(row.highestTier)}`}>{row.highestTier}</span>
              </div>
              <div className={`mt-3 grid grid-cols-2 gap-2 text-xs ${muted}`}>
                <span>Skills {row.skills}</span>
                <span>Agents {row.agents}</span>
              </div>
            </div>
          ))}
        </div>
      </section>
    </motion.div>
  )
}

function highestTier(skills: Skill[]): string {
  const order = ['T1', 'T2', 'T3', 'T4', 'T5']
  return skills.reduce((highest, skill) => {
    return order.indexOf(skill.approval_tier) > order.indexOf(highest) ? skill.approval_tier : highest
  }, 'T1')
}

function Stat({ label, value, icon, border, panel, muted }: { label: string; value: number; icon: ReactNode; border: string; panel: string; muted: string }) {
  return (
    <div className={`rounded-lg border ${border} ${panel} p-4 min-h-24`}>
      <div className={`text-xs font-semibold ${muted}`}>{label}</div>
      <div className="mt-2 flex items-center gap-2 text-2xl font-bold">
        {icon}
        {value}
      </div>
    </div>
  )
}

function Coverage({ label, ok, border, panel, muted }: { label: string; ok: boolean; border: string; panel: string; muted: string }) {
  return (
    <div className={`rounded-lg border ${border} ${panel} min-h-12 px-3 flex items-center justify-between gap-3`}>
      <span className={`text-sm font-semibold ${muted}`}>{label}</span>
      <span className={`text-xs font-semibold ${ok ? 'text-emerald-400' : 'text-amber-400'}`}>
        {ok ? 'Live' : 'Gap'}
      </span>
    </div>
  )
}

function Panel({ title, count, border, panel, muted, children }: { title: string; count: number; border: string; panel: string; muted: string; children: ReactNode }) {
  return (
    <section className={`rounded-lg border ${border} ${panel} overflow-hidden min-h-80`}>
      <div className={`px-4 py-3 border-b ${border} flex items-center justify-between`}>
        <div className="font-semibold">{title}</div>
        <div className={`text-xs ${muted}`}>{count}</div>
      </div>
      <div className="divide-y divide-zinc-500/10">
        {count === 0 ? (
          <div className={`p-4 text-sm ${muted}`}>None</div>
        ) : children}
      </div>
    </section>
  )
}

function ManifestBreakdown({
  title,
  rows,
  border,
  panel,
  muted,
}: {
  title: string
  rows: { label: string; count: number }[]
  border: string
  panel: string
  muted: string
}) {
  return (
    <section className={`rounded-lg border ${border} ${panel} overflow-hidden`}>
      <div className={`px-4 py-3 border-b ${border} flex items-center justify-between`}>
        <div className="font-semibold">{title}</div>
        <div className={`text-xs ${muted}`}>{rows.reduce((total, row) => total + row.count, 0)}</div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 p-4">
        {rows.length === 0 ? (
          <div className={`text-sm ${muted}`}>No manifest rows loaded.</div>
        ) : rows.map((row) => (
          <div key={row.label} className={`rounded-lg border ${border} p-3 min-h-20`}>
            <div className={`text-xs font-semibold ${muted}`}>{row.label}</div>
            <div className="mt-2 text-2xl font-bold">{row.count}</div>
          </div>
        ))}
      </div>
    </section>
  )
}

function SkillLine({ skill, muted }: { skill: Skill; muted: string }) {
  return (
    <div className="p-4 min-h-20">
      <div className="flex items-start justify-between gap-2">
        <div className="font-semibold text-sm break-all">{skill.name}</div>
        <span className={`shrink-0 rounded border px-2 py-1 text-xs font-semibold ${tierColor(skill.approval_tier)}`}>{skill.approval_tier}</span>
      </div>
      <div className={`mt-1 text-xs ${muted}`}>{skill.scope} · {skill.status}</div>
    </div>
  )
}
