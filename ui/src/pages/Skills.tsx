import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  Filter,
  KeyRound,
  Lock,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  Wrench,
} from 'lucide-react'
import { apiJson } from '../lib/apiFetch'
import { compactJson, uniqueSorted, type Agent, type AgentList, type Skill, type SkillList } from '../lib/registryTypes'
import { useAppStore } from '../store'

const ALL = 'all'

function tierColor(tier: string) {
  if (tier === 'T5') return 'border-rose-500/30 bg-rose-500/10 text-rose-400'
  if (tier === 'T4') return 'border-amber-500/30 bg-amber-500/10 text-amber-400'
  if (tier === 'T3') return 'border-sky-500/30 bg-sky-500/10 text-sky-400'
  return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
}

function statusColor(status: string) {
  if (status === 'active') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
  if (status === 'planned') return 'border-sky-500/30 bg-sky-500/10 text-sky-400'
  return 'border-zinc-500/30 bg-zinc-500/10 text-zinc-400'
}

export default function Skills() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-white/[0.04]' : 'bg-[#141414]/[0.03]'
  const strongPanel = isDark ? 'bg-zinc-950/50' : 'bg-white'
  const muted = isDark ? 'text-zinc-400' : 'text-zinc-500'

  const [skills, setSkills] = useState<Skill[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [selectedName, setSelectedName] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [domain, setDomain] = useState(ALL)
  const [status, setStatus] = useState(ALL)
  const [tier, setTier] = useState(ALL)
  const [flag, setFlag] = useState(ALL)
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
      setSelectedName((current) => current ?? skillRes.skills[0]?.name ?? null)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load skills')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const domains = useMemo(() => uniqueSorted(skills.map((skill) => skill.domain)), [skills])
  const tiers = useMemo(() => uniqueSorted(skills.map((skill) => skill.approval_tier)), [skills])

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    return skills.filter((skill) => {
      if (domain !== ALL && skill.domain !== domain) return false
      if (status !== ALL && skill.status !== status) return false
      if (tier !== ALL && skill.approval_tier !== tier) return false
      if (flag === 'mutating' && !skill.mutates_state) return false
      if (flag === 'body' && !skill.body_access) return false
      if (flag === 'idempotent' && !skill.idempotency_required) return false
      if (!normalized) return true
      return [
        skill.name,
        skill.domain,
        skill.action,
        skill.scope,
        skill.description,
      ].some((value) => value.toLowerCase().includes(normalized))
    })
  }, [skills, domain, status, tier, flag, query])

  const selected = useMemo(
    () => filtered.find((skill) => skill.name === selectedName) ?? filtered[0] ?? null,
    [selectedName, filtered]
  )

  const consumers = useMemo(() => {
    if (!selected) return []
    return agents.filter((agent) => agent.allowed_skills.includes(selected.name))
  }, [agents, selected])

  const stats = useMemo(() => ({
    active: skills.filter((skill) => skill.status === 'active').length,
    mutating: skills.filter((skill) => skill.mutates_state).length,
    body: skills.filter((skill) => skill.body_access).length,
    highRisk: skills.filter((skill) => ['T4', 'T5'].includes(skill.approval_tier)).length,
  }), [skills])

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="space-y-5 max-w-7xl">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <Wrench className="w-6 h-6 text-emerald-400" />
          <h1 className="text-2xl font-bold">Skills</h1>
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

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Active" value={stats.active} icon={<CheckCircle2 className="w-5 h-5 text-emerald-400" />} border={border} panel={panel} muted={muted} />
        <Stat label="Mutating" value={stats.mutating} icon={<Database className="w-5 h-5 text-sky-400" />} border={border} panel={panel} muted={muted} />
        <Stat label="Body Access" value={stats.body} icon={<Lock className="w-5 h-5 text-amber-400" />} border={border} panel={panel} muted={muted} />
        <Stat label="T4/T5" value={stats.highRisk} icon={<ShieldAlert className="w-5 h-5 text-rose-400" />} border={border} panel={panel} muted={muted} />
      </div>

      <section className={`rounded-lg border ${border} ${strongPanel} p-3`}>
        <div className="grid grid-cols-1 md:grid-cols-[1fr_150px_150px_120px_150px] gap-2">
          <label className={`min-h-11 rounded-lg border ${border} ${panel} px-3 flex items-center gap-2`}>
            <Search className={`w-4 h-4 ${muted}`} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="w-full bg-transparent outline-none text-sm"
              placeholder="Search skills"
            />
          </label>
          <Select value={domain} onChange={setDomain} options={[ALL, ...domains]} label="Domain" border={border} panel={panel} />
          <Select value={status} onChange={setStatus} options={[ALL, 'active', 'planned', 'disabled']} label="Status" border={border} panel={panel} />
          <Select value={tier} onChange={setTier} options={[ALL, ...tiers]} label="Tier" border={border} panel={panel} />
          <Select value={flag} onChange={setFlag} options={[ALL, 'mutating', 'body', 'idempotent']} label="Flag" border={border} panel={panel} />
        </div>
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-[460px_1fr] gap-4">
        <section className={`rounded-lg border ${border} ${strongPanel} overflow-hidden`}>
          <div className={`px-4 py-3 border-b ${border} flex items-center justify-between`}>
            <div className="font-semibold flex items-center gap-2">
              <Filter className="w-4 h-4" />
              Registry
            </div>
            <div className={`text-xs ${muted}`}>{filtered.length} of {skills.length}</div>
          </div>
          <div className="divide-y divide-zinc-500/10 max-h-[760px] overflow-y-auto">
            {loading && Array.from({ length: 8 }).map((_, index) => (
              <div key={index} className="p-4 animate-pulse">
                <div className="h-4 w-48 rounded bg-zinc-500/20" />
                <div className="mt-3 h-3 w-72 rounded bg-zinc-500/10" />
              </div>
            ))}
            {!loading && filtered.map((skill) => (
              <button
                key={skill.name}
                onClick={() => setSelectedName(skill.name)}
                className={`w-full min-h-24 text-left p-4 hover:bg-emerald-500/5 transition-colors ${
                  selected?.name === skill.name ? 'bg-emerald-500/10' : ''
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-semibold truncate">{skill.name}</div>
                    <div className={`mt-1 text-xs ${muted}`}>{skill.description}</div>
                  </div>
                  <span className={`shrink-0 rounded border px-2 py-1 text-xs font-semibold ${tierColor(skill.approval_tier)}`}>
                    {skill.approval_tier}
                  </span>
                </div>
                <div className="mt-3 flex items-center gap-2 flex-wrap text-xs">
                  <span className={`rounded border px-2 py-1 ${statusColor(skill.status)}`}>{skill.status}</span>
                  <span className={muted}>{skill.scope}</span>
                  {skill.body_access && <span className="text-amber-400">body</span>}
                  {skill.mutates_state && <span className="text-sky-400">mutates</span>}
                </div>
              </button>
            ))}
            {!loading && filtered.length === 0 && (
              <div className={`p-6 text-sm ${muted}`}>
                No skills match the current filters.
              </div>
            )}
          </div>
        </section>

        <section className={`rounded-lg border ${border} ${strongPanel} overflow-hidden min-h-[620px]`}>
          {!selected ? (
            <div className={`p-6 text-sm ${muted}`}>No skill selected.</div>
          ) : (
            <>
              <div className={`px-4 py-3 border-b ${border} flex items-start justify-between gap-3 flex-wrap`}>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h2 className="text-lg font-bold break-all">{selected.name}</h2>
                    <span className={`rounded border px-2 py-1 text-xs font-semibold ${tierColor(selected.approval_tier)}`}>{selected.approval_tier}</span>
                    <span className={`rounded border px-2 py-1 text-xs font-semibold ${statusColor(selected.status)}`}>{selected.status}</span>
                  </div>
                  <div className={`mt-1 text-sm ${muted}`}>{selected.description}</div>
                </div>
              </div>

              <div className="p-4 space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                  <Info label="Domain" value={selected.domain} icon={<Database className="w-4 h-4" />} border={border} panel={panel} muted={muted} />
                  <Info label="Scope" value={selected.scope} icon={<KeyRound className="w-4 h-4" />} border={border} panel={panel} muted={muted} />
                  <Info label="Owner" value={selected.owner} icon={<ShieldCheck className="w-4 h-4" />} border={border} panel={panel} muted={muted} />
                  <Info label="Action" value={selected.action} icon={<Wrench className="w-4 h-4" />} border={border} panel={panel} muted={muted} />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <FlagCard label="Mutates State" active={selected.mutates_state} border={border} panel={panel} muted={muted} />
                  <FlagCard label="Body Access" active={selected.body_access} border={border} panel={panel} muted={muted} />
                  <FlagCard label="Idempotency Required" active={selected.idempotency_required} border={border} panel={panel} muted={muted} />
                </div>

                <div className={`rounded-lg border ${border} ${panel} p-4`}>
                  <div className="text-sm font-semibold">Allowed Agents</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {consumers.length ? consumers.map((agent) => (
                      <span key={agent.agent_id} className={`rounded border ${border} px-2 py-1 text-xs`}>
                        {agent.display_name} · {agent.enabled ? 'on' : 'off'}
                      </span>
                    )) : <span className={`text-sm ${muted}`}>None</span>}
                  </div>
                </div>

                <div className={`rounded-lg border ${border} ${panel} p-4`}>
                  <div className="text-sm font-semibold">Metadata</div>
                  <div className={`mt-2 text-sm ${muted} break-words`}>{compactJson(selected.metadata)}</div>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </motion.div>
  )
}

function Select({
  value,
  onChange,
  options,
  label,
  border,
  panel,
}: {
  value: string
  onChange: (value: string) => void
  options: string[]
  label: string
  border: string
  panel: string
}) {
  return (
    <label className={`min-h-11 rounded-lg border ${border} ${panel} px-3 flex items-center gap-2`}>
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full bg-transparent outline-none text-sm capitalize"
      >
        {options.map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
    </label>
  )
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

function Info({ label, value, icon, border, panel, muted }: { label: string; value: string; icon: ReactNode; border: string; panel: string; muted: string }) {
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

function FlagCard({ label, active, border, panel, muted }: { label: string; active: boolean; border: string; panel: string; muted: string }) {
  return (
    <div className={`rounded-lg border ${border} ${panel} p-3 min-h-20`}>
      <div className={`text-xs font-semibold ${muted}`}>{label}</div>
      <div className={`mt-2 text-sm font-bold ${active ? 'text-amber-400' : 'text-emerald-400'}`}>
        {active ? 'Yes' : 'No'}
      </div>
    </div>
  )
}
