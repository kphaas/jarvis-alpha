import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useAppStore } from '../store'
import { askBrain } from '../api'
import type { AskResult } from '../types'

const MODES = ['auto', 'local', 'claude', 'gemini', 'perplexity', 'council']
const COUNCIL_COST = '~$0.006'

export default function Ask() {
  const { theme, mode, setMode, userId, sessionId, workspaceId, persistent, setPersistent } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/5' : 'bg-[#141414]/5'

  const [prompt, setPrompt] = useState('')
  const [result, setResult] = useState<AskResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)

  const submit = async () => {
    if (!prompt.trim()) return
    if (mode === 'council' && !showConfirm) { setShowConfirm(true); return }
    setShowConfirm(false)
    setLoading(true)
    try {
      const res = await askBrain({ prompt, mode, session_id: sessionId, user_id: userId, workspace_id: workspaceId ?? undefined, persistent })
      setResult(res)
    } finally { setLoading(false) }
  }

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="max-w-3xl space-y-6">
      <div>
        <h1 className="font-serif italic text-3xl">Ask</h1>
        <p className="text-[10px] font-mono uppercase opacity-50 mt-1">Adaptive AI router · 6 modes · hierarchical memory</p>
      </div>

      {/* Mode picker */}
      <div className="flex flex-wrap gap-2">
        {MODES.map(m => (
          <button key={m} onClick={() => setMode(m)}
            className={`px-3 py-1.5 rounded-full text-xs font-mono font-bold border transition-colors ${
              mode === m
                ? isDark ? 'bg-emerald-500 text-[#0A0A0A] border-emerald-500' : 'bg-[#141414] text-[#E4E3E0] border-[#141414]'
                : `${border} opacity-50 hover:opacity-80`
            }`}>{m}</button>
        ))}
      </div>

      {/* Persistent toggle */}
      <div className="flex items-center gap-3">
        <span className="text-xs font-mono opacity-50">Persistent memory</span>
        <button onClick={() => setPersistent(!persistent)}
          className={`w-10 h-5 rounded-full transition-colors ${persistent ? 'bg-emerald-500' : isDark ? 'bg-white/10' : 'bg-[#141414]/10'}`}
        />
      </div>

      {/* Council confirm */}
      <AnimatePresence>
        {showConfirm && (
          <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
            className="p-4 rounded-2xl bg-amber-500/10 border border-amber-500/30">
            <p className="text-sm font-bold text-amber-400 mb-1">Council mode — estimated cost {COUNCIL_COST}</p>
            <p className="text-xs opacity-60 mb-3">Fires Claude + Gemini + Perplexity in sequence. 4 model calls.</p>
            <div className="flex gap-3">
              <button onClick={submit} className="px-4 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded-lg text-xs font-mono font-bold">Confirm</button>
              <button onClick={() => setShowConfirm(false)} className={`px-4 py-1.5 rounded-lg text-xs font-mono ${border} opacity-60`}>Cancel</button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Input */}
      <textarea value={prompt} onChange={e => setPrompt(e.target.value)}
        placeholder="Ask anything…" rows={4}
        className={`w-full rounded-2xl border p-4 text-sm placeholder-opacity-30 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 resize-none bg-transparent ${border}`}
      />
      <button onClick={submit} disabled={loading || !prompt.trim()}
        className={`px-6 py-2.5 rounded-xl text-sm font-bold transition-all disabled:opacity-40 ${isDark ? 'bg-emerald-500 text-[#0A0A0A]' : 'bg-[#141414] text-[#E4E3E0]'}`}>
        {loading ? 'Thinking…' : 'Ask'}
      </button>

      {/* Result */}
      <AnimatePresence>
        {result && (
          <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
            className={`p-5 rounded-2xl border ${border} ${subtle} space-y-3`}>
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full ${isDark ? 'bg-emerald-500/20 text-emerald-400' : 'bg-[#141414]/10'}`}>{result.mode}</span>
              {result.steps_completed != null && <span className="text-[10px] font-mono opacity-40">{result.steps_completed}/4 steps</span>}
              {result.error && <span className="text-[10px] font-mono text-rose-400">{result.error}</span>}
            </div>
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{result.result}</p>
            {result.refined_prompt && <p className="text-[10px] font-mono opacity-30 border-t pt-2 mt-2">Refined: {result.refined_prompt}</p>}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
