import { useState } from "react"
import { useAppStore } from "../store"
import { ask } from "../api"

const MODES = ["auto", "local", "claude", "gemini", "perplexity", "council"]
const COUNCIL_COST = "$0.006"

export default function Ask() {
  const { mode, setMode, userId, sessionId, workspaceId, persistent, setPersistent } = useAppStore()
  const [prompt, setPrompt] = useState("")
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(false)
  const [showCouncilConfirm, setShowCouncilConfirm] = useState(false)

  async function submit() {
    if (!prompt.trim()) return
    if (mode === "council" && !showCouncilConfirm) {
      setShowCouncilConfirm(true)
      return
    }
    setShowCouncilConfirm(false)
    setLoading(true)
    try {
      const res = await ask({ prompt, mode, session_id: sessionId, user_id: userId, workspace_id: workspaceId ?? undefined, persistent })
      setResult(res)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="text-xl font-semibold">Ask</h1>

      <div className="flex flex-wrap gap-2">
        {MODES.map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${mode === m ? "bg-indigo-600 border-indigo-500 text-white" : "border-gray-700 text-gray-400 hover:border-gray-500"}`}
          >
            {m}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-3">
        <label className="text-xs text-gray-400">Persistent memory</label>
        <button
          onClick={() => setPersistent(!persistent)}
          className={`w-10 h-5 rounded-full transition-colors ${persistent ? "bg-indigo-600" : "bg-gray-700"}`}
        />
      </div>

      {showCouncilConfirm && (
        <div className="bg-yellow-900/30 border border-yellow-700 rounded-lg p-4 text-sm">
          <p className="font-medium text-yellow-300 mb-2">Council mode — estimated cost {COUNCIL_COST}</p>
          <p className="text-gray-400 mb-3">This fires Claude + Gemini + Perplexity in sequence.</p>
          <div className="flex gap-3">
            <button onClick={submit} className="px-4 py-1.5 bg-yellow-600 hover:bg-yellow-500 text-white rounded text-xs font-medium">Confirm</button>
            <button onClick={() => setShowCouncilConfirm(false)} className="px-4 py-1.5 bg-gray-700 text-gray-300 rounded text-xs font-medium">Cancel</button>
          </div>
        </div>
      )}

      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder="Ask anything…"
        rows={4}
        className="w-full bg-gray-900 border border-gray-700 rounded-lg p-3 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500 resize-none"
      />
      <button
        onClick={submit}
        disabled={loading || !prompt.trim()}
        className="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white rounded-lg text-sm font-medium"
      >
        {loading ? "Thinking…" : "Ask"}
      </button>

      {result && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <span className="px-2 py-0.5 bg-indigo-900 text-indigo-300 rounded-full">{String(result.mode)}</span>
            {!!result.steps_completed && <span>{String(result.steps_completed)}/4 steps</span>}
            {!!result.error && <span className="text-red-400">{String(result.error)}</span>}
          </div>
          <p className="text-sm text-gray-200 whitespace-pre-wrap">{String(result.result)}</p>
          {!!result.refined_prompt && <p className="text-xs text-gray-500">Refined: {String(result.refined_prompt)}</p>}
        </div>
      )}
    </div>
  )
}
