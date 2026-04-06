import { useEffect, useState } from 'react'
import { Bot, Check, Cloud, Pencil, Sparkles, X } from 'lucide-react'
import { apiJson } from '../../lib/apiFetch'
import { useCostsBudget, useCostsPerplexity, useCostsSummary } from '../../hooks/useCosts'
import { SectionSkeleton } from '../shared/SectionSkeleton'
import { SectionError } from '../shared/SectionError'
import type { PerplexityPayload } from '../../types/costs'
import { fmtMoney } from '../../types/costs'

export function ApiSpendSection({
  isDark,
  border,
  subtle,
}: {
  isDark: boolean
  border: string
  subtle: string
}) {
  const summaryQuery = useCostsSummary()
  const budgetQuery = useCostsBudget()
  const perplexityQuery = useCostsPerplexity()
  const summary = summaryQuery.data ?? null
  const budget = budgetQuery.data ?? null
  const loading = summaryQuery.isLoading || budgetQuery.isLoading
  const [err, setErr] = useState<string | null>(null)
  const [editProv, setEditProv] = useState<string | null>(null)
  const [limitInput, setLimitInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [pxEdit, setPxEdit] = useState(false)
  const [pxForm, setPxForm] = useState({ balance_usd: '', spent_usd: '' })
  const [pxSaving, setPxSaving] = useState(false)

  useEffect(() => {
    if (perplexityQuery.data) {
      setPxForm({
        balance_usd: String(perplexityQuery.data.balance_usd),
        spent_usd: String(perplexityQuery.data.spent_usd),
      })
    }
  }, [perplexityQuery.data])

  const saveLimit = async (provider: string) => {
    setSaving(true)
    try {
      const v = parseFloat(limitInput)
      await apiJson(`/v1/costs/budget/${encodeURIComponent(provider)}`, {
        method: 'POST',
        body: JSON.stringify({ monthly_limit_usd: v }),
      })
      setEditProv(null)
      await budgetQuery.refetch()
      await summaryQuery.refetch()
    } catch {
      setErr('Failed to update limit.')
    } finally {
      setSaving(false)
    }
  }

  const savePx = async () => {
    setPxSaving(true)
    try {
      await apiJson<PerplexityPayload>('/v1/costs/perplexity', {
        method: 'POST',
        body: JSON.stringify({
          balance_usd: parseFloat(pxForm.balance_usd) || 0,
          spent_usd: parseFloat(pxForm.spent_usd) || 0,
        }),
      })
      setPxEdit(false)
      await perplexityQuery.refetch()
      await summaryQuery.refetch()
      await budgetQuery.refetch()
    } catch {
      setErr('Perplexity save failed.')
    } finally {
      setPxSaving(false)
    }
  }

  const wrap = `rounded-3xl border overflow-hidden ${border} ${subtle} ${isDark ? 'bg-white/[0.03]' : 'bg-white/60'}`

  return (
    <section>
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] opacity-40 mb-4">Cloud API spend</p>
      {loading && <SectionSkeleton />}
      {!loading && (err || summaryQuery.error || budgetQuery.error) && !summary && (
        <div className={`p-8 ${wrap}`}>
          <SectionError message={err ?? 'Could not load budget or summary.'} />
        </div>
      )}
      {!loading && summary && budget && (
        <div className={wrap}>
          <div className="divide-y divide-white/5">
            {/* Anthropic */}
            <div className="p-6 space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <Sparkles className="w-5 h-5 text-orange-400 shrink-0" />
                <span className="font-semibold">Anthropic</span>
                <span className="font-mono text-sm tabular-nums ml-auto">
                  MTD {fmtMoney(summary.api?.anthropic?.total_usd ?? 0)}
                </span>
              </div>
              <div className="pl-8 text-xs opacity-60 space-y-1">
                <p>
                  jarvis_core ·{' '}
                  <span className="font-mono tabular-nums">
                    {fmtMoney(summary.api?.anthropic?.jarvis_core_usd ?? 0)}
                  </span>
                </p>
                <p>
                  jarvis_forge ·{' '}
                  <span className="font-mono tabular-nums">
                    {fmtMoney(summary.api?.anthropic?.jarvis_forge_usd ?? 0)}
                  </span>
                </p>
              </div>
              {(() => {
                const b = budget.find((x) => x.provider === 'anthropic')
                if (!b) return null
                const pct = Math.min(100, b.pct_used)
                return (
                  <div className="pl-8 pt-2 space-y-2">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="opacity-50">Limit</span>
                      {editProv === 'anthropic' ? (
                        <>
                          <input
                            type="number"
                            value={limitInput}
                            onChange={(e) => setLimitInput(e.target.value)}
                            className={`w-24 px-2 py-1 rounded-lg border text-xs font-mono bg-transparent ${border}`}
                          />
                          <button
                            type="button"
                            disabled={saving}
                            onClick={() => saveLimit('anthropic')}
                            className="p-1 rounded-lg bg-emerald-500 text-[#0a0a0a]"
                          >
                            <Check className="w-4 h-4" />
                          </button>
                          <button type="button" onClick={() => setEditProv(null)} className="p-1 rounded-lg border border-white/10">
                            <X className="w-4 h-4" />
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            setEditProv('anthropic')
                            setLimitInput(String(b.monthly_limit_usd))
                          }}
                          className="inline-flex items-center gap-1 font-mono tabular-nums"
                        >
                          {fmtMoney(b.monthly_limit_usd)}
                          <Pencil className="w-3 h-3 opacity-40" />
                        </button>
                      )}
                      <span className="opacity-50 ml-2">Remaining {fmtMoney(b.remaining_usd)}</span>
                    </div>
                    <div className={`h-1.5 rounded-full overflow-hidden ${isDark ? 'bg-white/10' : 'bg-[#141414]/10'}`}>
                      <div className="h-full rounded-full bg-orange-400/90" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                )
              })()}
            </div>
            {/* Gemini */}
            <div className="p-6 space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <Bot className="w-5 h-5 text-blue-500 shrink-0" />
                <span className="font-semibold">Gemini</span>
                <span
                  className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border ${
                    summary.api?.gemini?.source === 'gcp_api'
                      ? 'border-blue-500/40 text-blue-400'
                      : 'border-white/15 opacity-60'
                  }`}
                >
                  {summary.api?.gemini?.source === 'gcp_api' ? 'GCP API' : 'GCP FREE TIER'}
                </span>
                <span className="font-mono text-sm tabular-nums ml-auto">
                  MTD {fmtMoney(summary.api?.gemini?.total_usd ?? 0)}
                </span>
              </div>
              {(() => {
                const b = budget.find((x) => x.provider === 'gemini')
                if (!b) return null
                const pct = Math.min(100, b.pct_used)
                return (
                  <div className="pl-8 space-y-2">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="opacity-50">Limit</span>
                      {editProv === 'gemini' ? (
                        <>
                          <input
                            type="number"
                            value={limitInput}
                            onChange={(e) => setLimitInput(e.target.value)}
                            className={`w-24 px-2 py-1 rounded-lg border text-xs font-mono bg-transparent ${border}`}
                          />
                          <button
                            type="button"
                            disabled={saving}
                            onClick={() => saveLimit('gemini')}
                            className="p-1 rounded-lg bg-emerald-500 text-[#0a0a0a]"
                          >
                            <Check className="w-4 h-4" />
                          </button>
                          <button type="button" onClick={() => setEditProv(null)} className="p-1 rounded-lg border border-white/10">
                            <X className="w-4 h-4" />
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            setEditProv('gemini')
                            setLimitInput(String(b.monthly_limit_usd))
                          }}
                          className="inline-flex items-center gap-1 font-mono tabular-nums"
                        >
                          {fmtMoney(b.monthly_limit_usd)}
                          <Pencil className="w-3 h-3 opacity-40" />
                        </button>
                      )}
                      <span className="opacity-50 ml-2">Remaining {fmtMoney(b.remaining_usd)}</span>
                    </div>
                    <div className={`h-1.5 rounded-full overflow-hidden ${isDark ? 'bg-white/10' : 'bg-[#141414]/10'}`}>
                      <div className="h-full rounded-full bg-blue-500/80" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                )
              })()}
            </div>
            {/* Perplexity */}
            <div className="p-6 space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <Cloud className="w-5 h-5 text-cyan-400 shrink-0" />
                <span className="font-semibold">Perplexity</span>
                <span className="font-mono text-sm tabular-nums ml-auto">
                  MTD {fmtMoney(summary.api?.perplexity_mtd_usd ?? 0)}
                </span>
              </div>
              <div className="pl-8 flex flex-wrap items-center gap-4 text-sm">
                <span className="opacity-60">
                  Credit {fmtMoney(parseFloat(pxForm.balance_usd) || 0)} · Spent {fmtMoney(parseFloat(pxForm.spent_usd) || 0)}
                </span>
                {!pxEdit ? (
                  <button type="button" onClick={() => setPxEdit(true)} className="p-1.5 rounded-lg border border-white/10">
                    <Pencil className="w-4 h-4" />
                  </button>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      type="number"
                      placeholder="balance"
                      value={pxForm.balance_usd}
                      onChange={(e) => setPxForm((f) => ({ ...f, balance_usd: e.target.value }))}
                      className={`w-24 px-2 py-1 rounded-lg border text-xs font-mono bg-transparent ${border}`}
                    />
                    <input
                      type="number"
                      placeholder="spent"
                      value={pxForm.spent_usd}
                      onChange={(e) => setPxForm((f) => ({ ...f, spent_usd: e.target.value }))}
                      className={`w-24 px-2 py-1 rounded-lg border text-xs font-mono bg-transparent ${border}`}
                    />
                    <button
                      type="button"
                      disabled={pxSaving}
                      onClick={savePx}
                      className="p-1.5 rounded-lg bg-emerald-500 text-[#0a0a0a]"
                    >
                      <Check className="w-4 h-4" />
                    </button>
                    <button type="button" onClick={() => setPxEdit(false)} className="p-1.5 rounded-lg border border-white/10">
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                )}
              </div>
              {(() => {
                const b = budget.find((x) => x.provider === 'perplexity')
                if (!b) return null
                const pct = Math.min(100, b.pct_used)
                return (
                  <div className="pl-8 space-y-2">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="opacity-50">Limit</span>
                      {editProv === 'perplexity' ? (
                        <>
                          <input
                            type="number"
                            value={limitInput}
                            onChange={(e) => setLimitInput(e.target.value)}
                            className={`w-24 px-2 py-1 rounded-lg border text-xs font-mono bg-transparent ${border}`}
                          />
                          <button
                            type="button"
                            disabled={saving}
                            onClick={() => saveLimit('perplexity')}
                            className="p-1 rounded-lg bg-emerald-500 text-[#0a0a0a]"
                          >
                            <Check className="w-4 h-4" />
                          </button>
                          <button type="button" onClick={() => setEditProv(null)} className="p-1 rounded-lg border border-white/10">
                            <X className="w-4 h-4" />
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            setEditProv('perplexity')
                            setLimitInput(String(b.monthly_limit_usd))
                          }}
                          className="inline-flex items-center gap-1 font-mono tabular-nums"
                        >
                          {fmtMoney(b.monthly_limit_usd)}
                          <Pencil className="w-3 h-3 opacity-40" />
                        </button>
                      )}
                      <span className="opacity-50 ml-2">Remaining {fmtMoney(b.remaining_usd)}</span>
                    </div>
                    <div className={`h-1.5 rounded-full overflow-hidden ${isDark ? 'bg-white/10' : 'bg-[#141414]/10'}`}>
                      <div className="h-full rounded-full bg-cyan-500/80" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                )
              })()}
            </div>
          </div>
          {(err || summaryQuery.error || budgetQuery.error || perplexityQuery.error) && summary && (
            <p className="text-xs text-rose-500 p-4">{err ?? 'Could not load budget or summary.'}</p>
          )}
        </div>
      )}
    </section>
  )
}
