import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Bot,
  CheckCircle2,
  ExternalLink,
  FileSearch,
  Globe2,
  Loader2,
  MessageSquare,
  RotateCcw,
  Search,
  Send,
  ShieldCheck,
  Square,
  User,
} from 'lucide-react'
import { apiFetch, apiJson } from '../lib/apiFetch'
import { useAppStore } from '../store'

type InternetMode = 'none' | 'web_search' | 'deep_research'
type MessageRole = 'user' | 'assistant'

interface Citation {
  source_url?: string
  host?: string
  claim?: string
  confidence?: string
  source_quality?: string
  source_rank?: number
  source_score?: number
  quality_reasons?: string[]
}

interface ChatMetadata {
  thread_id?: string
  internet_mode?: InternetMode
  internet_request_id?: string
  internet_selected_tool?: string
  internet_citation_count?: number
  internet_accepted_citation_count?: number
  internet_source_quality_status?: string
  internet_research_report_planned_query_count?: number
  internet_research_report_independent_source_count?: number
  internet_research_report_coverage_warnings?: string[]
  internet_synthesis_answerable?: boolean
  internet_synthesis_status?: string
  internet_synthesis_required_behavior?: string
  raw_web_content_is_untrusted?: boolean
  citations?: Citation[]
}

interface StreamPayload extends ChatMetadata {
  delta?: string
  done?: boolean
  model?: string
}

interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  metadata?: ChatMetadata
  pending?: boolean
}

interface PendingApprovalItem {
  id: string
  action_class: string[]
  risk_tier: string
  description: string
  status: string
  requested_at: string
  expires_at: string
}

interface PendingApprovalsPayload {
  pending: PendingApprovalItem[]
  count: number
}

const MODE_OPTIONS: Array<{
  mode: InternetMode
  label: string
  detail: string
  icon: typeof MessageSquare
}> = [
  { mode: 'none', label: 'Local', detail: 'Memory and local model', icon: MessageSquare },
  { mode: 'web_search', label: 'Web', detail: 'Beacon search', icon: Search },
  { mode: 'deep_research', label: 'Research', detail: 'Multi-source Beacon', icon: FileSearch },
]

const QUICK_PROMPTS = [
  {
    label: 'Weather',
    mode: 'web_search' as const,
    text: 'What is the weather outside right now? Use my home location if configured.',
  },
  {
    label: 'Docs',
    mode: 'web_search' as const,
    text: 'Find the official OpenAI API reference URL and cite it.',
  },
  {
    label: 'Compare',
    mode: 'deep_research' as const,
    text: 'Compare Brave Search API and Perplexity Search API pricing using current official docs.',
  },
]

function hasInternetMetadata(payload: StreamPayload): boolean {
  return (
    typeof payload.internet_request_id === 'string' ||
    payload.internet_mode === 'web_search' ||
    payload.internet_mode === 'deep_research'
  )
}

function safeText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

function safeNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function sourceQualityTone(status: string | undefined): {
  text: string
  classes: string
} {
  switch (status) {
    case 'supported':
      return { text: 'Supported', classes: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-500' }
    case 'weak':
      return { text: 'Weak', classes: 'border-amber-500/30 bg-amber-500/10 text-amber-500' }
    case 'insufficient':
      return { text: 'Insufficient', classes: 'border-rose-500/30 bg-rose-500/10 text-rose-500' }
    default:
      return { text: status || 'No evidence', classes: 'border-zinc-500/30 bg-zinc-500/10 text-zinc-500' }
  }
}

function modeLabel(mode: InternetMode | undefined): string {
  if (mode === 'web_search') return 'Web search'
  if (mode === 'deep_research') return 'Deep research'
  return 'Local'
}

function getCitationUrl(citation: Citation): string | null {
  return safeText(citation.source_url)
}

function normalizeMetadata(payload: StreamPayload): ChatMetadata {
  return {
    thread_id: safeText(payload.thread_id) ?? undefined,
    internet_mode: payload.internet_mode,
    internet_request_id: safeText(payload.internet_request_id) ?? undefined,
    internet_selected_tool: safeText(payload.internet_selected_tool) ?? undefined,
    internet_citation_count: safeNumber(payload.internet_citation_count) ?? undefined,
    internet_accepted_citation_count:
      safeNumber(payload.internet_accepted_citation_count) ?? undefined,
    internet_source_quality_status:
      safeText(payload.internet_source_quality_status) ?? undefined,
    internet_research_report_planned_query_count:
      safeNumber(payload.internet_research_report_planned_query_count) ?? undefined,
    internet_research_report_independent_source_count:
      safeNumber(payload.internet_research_report_independent_source_count) ?? undefined,
    internet_research_report_coverage_warnings: Array.isArray(
      payload.internet_research_report_coverage_warnings
    )
      ? payload.internet_research_report_coverage_warnings.filter(
          (item): item is string => typeof item === 'string'
        )
      : undefined,
    internet_synthesis_answerable:
      typeof payload.internet_synthesis_answerable === 'boolean'
        ? payload.internet_synthesis_answerable
        : undefined,
    internet_synthesis_status: safeText(payload.internet_synthesis_status) ?? undefined,
    internet_synthesis_required_behavior:
      safeText(payload.internet_synthesis_required_behavior) ?? undefined,
    raw_web_content_is_untrusted:
      typeof payload.raw_web_content_is_untrusted === 'boolean'
        ? payload.raw_web_content_is_untrusted
        : undefined,
    citations: Array.isArray(payload.citations)
      ? payload.citations.filter((item): item is Citation => typeof item === 'object' && item !== null)
      : undefined,
  }
}

function parseSseFrame(frame: string): StreamPayload[] {
  return frame
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.replace(/^data:\s*/, ''))
    .filter((line) => line && line !== '[DONE]')
    .map((line) => JSON.parse(line) as unknown)
    .filter((payload): payload is StreamPayload => typeof payload === 'object' && payload !== null)
}

async function readChatStream(
  body: ReadableStream<Uint8Array>,
  onPayload: (payload: StreamPayload) => void
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split(/\n\n/)
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        for (const payload of parseSseFrame(frame)) {
          onPayload(payload)
        }
      }
    }
    buffer += decoder.decode()
    if (buffer.trim()) {
      for (const payload of parseSseFrame(buffer)) {
        onPayload(payload)
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function isBeaconBrowserApproval(item: PendingApprovalItem): boolean {
  return (
    item.action_class.includes('beacon_browser_use') ||
    item.description.toLowerCase().includes('beacon browser')
  )
}

function newId(): string {
  return crypto.randomUUID()
}

export default function Ask() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-[#0F0F0F]' : 'bg-white'
  const subtle = isDark ? 'bg-white/[0.04]' : 'bg-[#141414]/5'
  const hover = isDark ? 'hover:bg-white/[0.07]' : 'hover:bg-[#141414]/8'
  const muted = isDark ? 'text-zinc-500' : 'text-zinc-600'
  const strongMuted = isDark ? 'text-zinc-300' : 'text-zinc-800'

  const [mode, setMode] = useState<InternetMode>('none')
  const [prompt, setPrompt] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [threadId, setThreadId] = useState<string | null>(null)
  const [activeMetadata, setActiveMetadata] = useState<ChatMetadata | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [browserApprovals, setBrowserApprovals] = useState<PendingApprovalItem[]>([])
  const [approvalsLoading, setApprovalsLoading] = useState(false)
  const [approvalsError, setApprovalsError] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const lastAssistantMetadata = useMemo(() => {
    for (const message of [...messages].reverse()) {
      if (message.role === 'assistant' && message.metadata) return message.metadata
    }
    return null
  }, [messages])

  const evidence = activeMetadata ?? lastAssistantMetadata

  const loadBrowserApprovals = async () => {
    setApprovalsLoading(true)
    setApprovalsError(false)
    try {
      const payload = await apiJson<PendingApprovalsPayload>('/v1/approvals/pending')
      setBrowserApprovals((payload.pending ?? []).filter(isBeaconBrowserApproval))
    } catch {
      setBrowserApprovals([])
      setApprovalsError(true)
    } finally {
      setApprovalsLoading(false)
    }
  }

  useEffect(() => {
    void loadBrowserApprovals()
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  const stopStreaming = () => {
    abortRef.current?.abort()
  }

  const resetThread = () => {
    if (isStreaming) stopStreaming()
    setThreadId(null)
    setMessages([])
    setActiveMetadata(null)
    setError(null)
  }

  const submitPrompt = async (event?: FormEvent) => {
    event?.preventDefault()
    const text = prompt.trim()
    if (!text || isStreaming) return

    const userMessage: ChatMessage = { id: newId(), role: 'user', content: text }
    const assistantId = newId()
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      pending: true,
    }
    setMessages((current) => [...current, userMessage, assistantMessage])
    setPrompt('')
    setError(null)
    setActiveMetadata(null)
    setIsStreaming(true)

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const response = await apiFetch('/v1/chat/completions', {
        method: 'POST',
        signal: controller.signal,
        headers: {
          Accept: 'text/event-stream',
        },
        body: JSON.stringify({
          model: 'auto',
          stream: true,
          internet_mode: mode,
          thread_id: threadId ?? undefined,
          messages: [{ role: 'user', content: text }],
        }),
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      if (!response.body) {
        throw new Error('Missing response stream')
      }

      await readChatStream(response.body, (payload) => {
        if (payload.thread_id) setThreadId(payload.thread_id)

        if (hasInternetMetadata(payload)) {
          const metadata = normalizeMetadata(payload)
          setActiveMetadata(metadata)
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantId
                ? { ...message, metadata }
                : message
            )
          )
        }

        if (typeof payload.delta === 'string' && payload.delta.length > 0) {
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantId
                ? { ...message, content: message.content + payload.delta }
                : message
            )
          )
        }

        if (payload.done === true) {
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantId ? { ...message, pending: false } : message
            )
          )
        }
      })

      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId ? { ...message, pending: false } : message
        )
      )
    } catch (err) {
      const aborted = err instanceof DOMException && err.name === 'AbortError'
      const message = aborted ? 'Stopped' : err instanceof Error ? err.message : String(err)
      if (!aborted) setError(message)
      setMessages((current) =>
        current.map((item) =>
          item.id === assistantId
            ? {
                ...item,
                pending: false,
                content: item.content || (aborted ? 'Stopped.' : 'Request failed.'),
              }
            : item
        )
      )
    } finally {
      setIsStreaming(false)
      abortRef.current = null
      void loadBrowserApprovals()
    }
  }

  const applyQuickPrompt = (item: (typeof QUICK_PROMPTS)[number]) => {
    if (isStreaming) return
    setMode(item.mode)
    setPrompt(item.text)
  }

  const citationCount = evidence?.citations?.length ?? 0
  const quality = sourceQualityTone(evidence?.internet_source_quality_status)

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className={`min-h-full ${isDark ? 'text-[#E4E3E0]' : 'text-[#141414]'}`}
    >
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Ask</h1>
          <p className={`mt-1 text-xs font-mono ${muted}`}>AT-0 chat · Beacon evidence</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {threadId ? (
            <span className={`rounded-lg border px-3 py-2 text-xs font-mono ${border} ${panel}`}>
              Thread {threadId.slice(0, 8)}
            </span>
          ) : null}
          <button
            type="button"
            onClick={resetThread}
            disabled={isStreaming && !abortRef.current}
            className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${border} ${panel} ${hover} disabled:opacity-40`}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            New thread
          </button>
        </div>
      </div>

      <div className="grid min-h-[calc(100vh-12rem)] grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <section className={`flex min-h-[620px] flex-col overflow-hidden rounded-xl border ${border} ${panel}`}>
          <div className={`border-b px-4 py-3 ${border}`}>
            <div className="flex flex-wrap items-center gap-2">
              {MODE_OPTIONS.map((item) => {
                const Icon = item.icon
                const selected = mode === item.mode
                return (
                  <button
                    key={item.mode}
                    type="button"
                    onClick={() => setMode(item.mode)}
                    disabled={isStreaming}
                    className={`flex min-w-32 items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors ${
                      selected
                        ? isDark
                          ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                          : 'border-[#141414] bg-[#141414] text-[#E4E3E0]'
                        : `${border} ${subtle} ${hover}`
                    } disabled:opacity-50`}
                    aria-pressed={selected}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="min-w-0">
                      <span className="block text-xs font-semibold">{item.label}</span>
                      <span className="block truncate text-[10px] opacity-65">{item.detail}</span>
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          <div className={`flex-1 overflow-y-auto px-4 py-5 ${isDark ? 'bg-[#0A0A0A]' : 'bg-[#F4F3EF]'}`}>
            {messages.length === 0 ? (
              <div className={`rounded-xl border p-4 ${border} ${panel}`}>
                <div className="flex items-start gap-3">
                  <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${subtle}`}>
                    <Bot className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold">Ready</p>
                    <p className={`mt-1 max-w-2xl text-sm leading-6 ${muted}`}>
                      Ask Alpha directly, or route the turn through Beacon when the answer needs current public evidence.
                    </p>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {QUICK_PROMPTS.map((item) => (
                        <button
                          key={item.label}
                          type="button"
                          onClick={() => applyQuickPrompt(item)}
                          className={`rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${border} ${subtle} ${hover}`}
                        >
                          {item.label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            ) : null}

            <div className="space-y-4">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`flex gap-3 ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  {message.role === 'assistant' ? (
                    <div className={`mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${subtle}`}>
                      <Bot className="h-4 w-4" />
                    </div>
                  ) : null}
                  <div
                    className={`max-w-[min(760px,100%)] rounded-xl border px-4 py-3 ${
                      message.role === 'user'
                        ? isDark
                          ? 'border-emerald-500/30 bg-emerald-500/15'
                          : 'border-[#141414] bg-[#141414] text-[#E4E3E0]'
                        : `${border} ${panel}`
                    }`}
                  >
                    <div className="mb-2 flex items-center gap-2">
                      {message.role === 'user' ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
                      <span className="text-[10px] font-mono uppercase opacity-60">
                        {message.role === 'user' ? 'Ken' : 'JARVIS'}
                      </span>
                      {message.pending ? <Loader2 className="h-3.5 w-3.5 animate-spin opacity-60" /> : null}
                    </div>
                    <p className="whitespace-pre-wrap break-words text-sm leading-6">
                      {message.content || (message.pending ? 'Thinking...' : '')}
                    </p>
                    {message.metadata ? (
                      <div className={`mt-3 flex flex-wrap items-center gap-2 border-t pt-3 ${border}`}>
                        <span className={`rounded-full border px-2 py-1 text-[10px] font-mono ${sourceQualityTone(message.metadata.internet_source_quality_status).classes}`}>
                          {sourceQualityTone(message.metadata.internet_source_quality_status).text}
                        </span>
                        <span className={`text-[10px] font-mono ${muted}`}>
                          {modeLabel(message.metadata.internet_mode)} · {message.metadata.internet_citation_count ?? message.metadata.citations?.length ?? 0} citations
                        </span>
                      </div>
                    ) : null}
                  </div>
                  {message.role === 'user' ? (
                    <div className={`mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${subtle}`}>
                      <User className="h-4 w-4" />
                    </div>
                  ) : null}
                </div>
              ))}
              <div ref={scrollRef} />
            </div>
          </div>

          <form onSubmit={submitPrompt} className={`border-t p-4 ${border}`}>
            {error ? (
              <div className="mb-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-500">
                {error}
              </div>
            ) : null}
            <div className="flex gap-3">
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                rows={3}
                disabled={isStreaming}
                placeholder="Ask Alpha..."
                className={`min-h-24 flex-1 resize-none rounded-xl border px-4 py-3 text-sm outline-none transition-colors focus:ring-2 focus:ring-emerald-500/50 disabled:opacity-60 ${border} ${isDark ? 'bg-[#0A0A0A]' : 'bg-[#F8F7F4]'}`}
              />
              <div className="flex flex-col gap-2">
                {isStreaming ? (
                  <button
                    type="button"
                    onClick={stopStreaming}
                    className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-rose-500/30 bg-rose-500/10 text-rose-500 transition-colors hover:bg-rose-500/15"
                    aria-label="Stop response"
                  >
                    <Square className="h-4 w-4 fill-current" />
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={!prompt.trim()}
                    className={`inline-flex h-11 w-11 items-center justify-center rounded-lg border transition-colors disabled:opacity-40 ${
                      isDark
                        ? 'border-emerald-500/40 bg-emerald-500 text-[#0A0A0A] hover:bg-emerald-400'
                        : 'border-[#141414] bg-[#141414] text-[#E4E3E0] hover:bg-[#2A2926]'
                    }`}
                    aria-label="Send message"
                  >
                    <Send className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>
          </form>
        </section>

        <aside className="space-y-4">
          <section className={`rounded-xl border ${border} ${panel}`}>
            <div className={`flex items-center justify-between border-b px-4 py-3 ${border}`}>
              <div className="flex items-center gap-2">
                <Globe2 className="h-4 w-4" />
                <h2 className="text-sm font-semibold">Beacon Evidence</h2>
              </div>
              {evidence ? (
                <span className={`rounded-full border px-2 py-1 text-[10px] font-mono ${quality.classes}`}>
                  {quality.text}
                </span>
              ) : null}
            </div>
            <div className="space-y-4 p-4">
              {evidence ? (
                <>
                  <div className="grid grid-cols-2 gap-2">
                    <Metric label="Mode" value={modeLabel(evidence.internet_mode)} border={border} subtle={subtle} />
                    <Metric label="Tool" value={evidence.internet_selected_tool ?? 'none'} border={border} subtle={subtle} />
                    <Metric label="Citations" value={String(evidence.internet_citation_count ?? citationCount)} border={border} subtle={subtle} />
                    <Metric label="Accepted" value={String(evidence.internet_accepted_citation_count ?? 0)} border={border} subtle={subtle} />
                    <Metric label="Queries" value={String(evidence.internet_research_report_planned_query_count ?? 0)} border={border} subtle={subtle} />
                    <Metric label="Sources" value={String(evidence.internet_research_report_independent_source_count ?? 0)} border={border} subtle={subtle} />
                  </div>
                  <div className={`rounded-lg border p-3 ${border} ${subtle}`}>
                    <div className="flex items-center gap-2 text-xs font-medium">
                      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                      <span>{evidence.raw_web_content_is_untrusted ? 'Raw web content isolated' : 'Raw web content status unknown'}</span>
                    </div>
                    <p className={`mt-2 text-xs leading-5 ${muted}`}>
                      {evidence.internet_synthesis_required_behavior ?? 'No synthesis policy reported'}
                    </p>
                  </div>
                  {evidence.internet_research_report_coverage_warnings?.length ? (
                    <div className={`rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs leading-5 ${isDark ? 'text-amber-300' : 'text-amber-800'}`}>
                      {evidence.internet_research_report_coverage_warnings.slice(0, 3).join(' · ')}
                    </div>
                  ) : null}
                  <div>
                    <div className="mb-2 flex items-center justify-between">
                      <p className="text-xs font-semibold">Citations</p>
                      <span className={`text-[10px] font-mono ${muted}`}>{citationCount}</span>
                    </div>
                    <div className="space-y-2">
                      {evidence.citations?.length ? (
                        evidence.citations.slice(0, 8).map((citation, index) => {
                          const url = getCitationUrl(citation)
                          return (
                            <a
                              key={`${citation.host ?? 'source'}-${index}`}
                              href={url ?? undefined}
                              target="_blank"
                              rel="noreferrer"
                              className={`block rounded-lg border p-3 transition-colors ${border} ${subtle} ${url ? hover : ''}`}
                            >
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <p className={`truncate text-xs font-semibold ${strongMuted}`}>
                                    {citation.host ?? 'Source'}
                                  </p>
                                  <p className={`mt-1 line-clamp-2 text-xs leading-5 ${muted}`}>
                                    {citation.claim ?? citation.source_quality ?? 'Beacon source'}
                                  </p>
                                </div>
                                {url ? <ExternalLink className="h-3.5 w-3.5 shrink-0 opacity-50" /> : null}
                              </div>
                            </a>
                          )
                        })
                      ) : (
                        <p className={`rounded-lg border p-3 text-xs ${border} ${muted}`}>No citations for this turn.</p>
                      )}
                    </div>
                  </div>
                </>
              ) : (
                <p className={`text-sm leading-6 ${muted}`}>
                  Beacon metadata appears here when a turn uses web search or deep research.
                </p>
              )}
            </div>
          </section>

          <section className={`rounded-xl border ${border} ${panel}`}>
            <div className={`flex items-center justify-between border-b px-4 py-3 ${border}`}>
              <div className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4" />
                <h2 className="text-sm font-semibold">Browser Approvals</h2>
              </div>
              <button
                type="button"
                onClick={() => void loadBrowserApprovals()}
                disabled={approvalsLoading}
                className={`rounded-lg border p-1.5 transition-colors ${border} ${hover} disabled:opacity-40`}
                aria-label="Refresh browser approvals"
              >
                <RotateCcw className={`h-3.5 w-3.5 ${approvalsLoading ? 'animate-spin' : ''}`} />
              </button>
            </div>
            <div className="space-y-3 p-4">
              <div className={`rounded-lg border p-3 ${border} ${subtle}`}>
                <p className="text-2xl font-semibold">{approvalsLoading ? '...' : browserApprovals.length}</p>
                <p className={`mt-1 text-xs ${muted}`}>Pending Beacon browser-use approvals</p>
              </div>
              {approvalsError ? (
                <p className="text-xs text-amber-500">Approval queue unavailable.</p>
              ) : null}
              <Link
                to="/approvals"
                className={`inline-flex w-full items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${border} ${hover}`}
              >
                Open approvals
                <ExternalLink className="h-3.5 w-3.5" />
              </Link>
            </div>
          </section>
        </aside>
      </div>
    </motion.div>
  )
}

function Metric({
  label,
  value,
  border,
  subtle,
}: {
  label: string
  value: string
  border: string
  subtle: string
}) {
  return (
    <div className={`rounded-lg border p-3 ${border} ${subtle}`}>
      <p className="text-[10px] font-mono uppercase opacity-50">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold">{value}</p>
    </div>
  )
}
