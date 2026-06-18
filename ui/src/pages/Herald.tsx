import { useCallback, useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import {
  CheckCircle2,
  Inbox,
  LoaderCircle,
  MailCheck,
  RefreshCw,
  Send,
  ShieldCheck,
  XCircle,
} from 'lucide-react'
import { apiJson } from '../lib/apiFetch'
import { useAppStore } from '../store'

interface CountRow {
  mailbox?: string | null
  classification?: string | null
  status: string
  priority?: string | null
  count: number
}

interface DraftCountRow {
  mailbox?: string | null
  status: string
  count: number
}

interface ScanRun {
  id: string
  trigger: string
  status: string
  started_at: string
  finished_at: string | null
  mailbox_count: number
  max_results: number
  messages_seen: number
  messages_new: number
  draft_proposals_created: number
  error_type?: string | null
  error_message?: string | null
}

interface Dashboard {
  message_counts: CountRow[]
  draft_counts: DraftCountRow[]
  latest_scan: ScanRun | null
}

interface MailboxList {
  mailboxes: string[]
}

interface MailMessage {
  id: string
  mailbox: string
  sender_name: string | null
  sender_email: string | null
  subject: string | null
  received_at: string | null
  body_preview: string | null
  classification: string
  priority: string
  status: string
  classification_reason: string
}

interface MessageList {
  messages: MailMessage[]
}

interface Draft {
  id: string
  mail_message_id: string
  mailbox: string
  recipient_email: string | null
  reply_subject: string
  proposed_body: string
  status: string
  reviewer_notes: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  sent_at: string | null
  send_failed_at: string | null
  send_error_type: string | null
  send_error_message: string | null
  send_attempt_count: number
  created_at: string
  sender_name: string | null
  sender_email: string | null
  original_subject: string | null
  received_at: string | null
  classification: string
  priority: string
}

interface DraftList {
  drafts: Draft[]
}

interface ScanResponse {
  messages_seen: number
  messages_new: number
  draft_proposals_created: number
}

interface SendResponse {
  mailbox: string
  status: 'sent'
  graph_status_code: number
  send_attempt_count: number
  sent_at: string
}

const ALL_MAILBOXES = 'all'

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

function classTone(value: string) {
  if (value === 'high' || value === 'press' || value === 'investor') {
    return 'border-amber-400/30 bg-amber-500/10 text-amber-300'
  }
  if (value === 'support') return 'border-sky-400/30 bg-sky-500/10 text-sky-300'
  if (value === 'lead' || value === 'approved') return 'border-emerald-400/30 bg-emerald-500/10 text-emerald-300'
  if (value === 'rejected' || value === 'noise') return 'border-zinc-400/30 bg-zinc-500/10 text-zinc-400'
  return 'border-white/10 bg-white/5 text-zinc-300'
}

function Pill({ label }: { label: string }) {
  return (
    <span className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${classTone(label)}`}>
      {label.replace(/_/g, ' ')}
    </span>
  )
}

export default function Herald() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-white/[0.04]' : 'bg-[#141414]/[0.03]'
  const strongPanel = isDark ? 'bg-zinc-950/50' : 'bg-white'
  const muted = isDark ? 'text-zinc-400' : 'text-zinc-500'
  const strong = isDark ? 'text-white' : 'text-[#141414]'

  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [mailboxes, setMailboxes] = useState<string[]>([])
  const [selectedMailbox, setSelectedMailbox] = useState(ALL_MAILBOXES)
  const [messages, setMessages] = useState<MailMessage[]>([])
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [actingDraftId, setActingDraftId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const mailboxQuery = selectedMailbox === ALL_MAILBOXES ? '' : `&mailbox=${encodeURIComponent(selectedMailbox)}`
      const [mailboxRes, dashboardRes, messageRes, draftRes] = await Promise.all([
        apiJson<MailboxList>('/v1/at0-mail/mailboxes'),
        apiJson<Dashboard>('/v1/at0-mail/dashboard'),
        apiJson<MessageList>(`/v1/at0-mail/messages?limit=12${mailboxQuery}`),
        apiJson<DraftList>(`/v1/at0-mail/drafts?status=all&limit=12${mailboxQuery}`),
      ])
      setMailboxes(mailboxRes.mailboxes)
      if (selectedMailbox !== ALL_MAILBOXES && !mailboxRes.mailboxes.includes(selectedMailbox)) {
        setSelectedMailbox(ALL_MAILBOXES)
      }
      setDashboard(dashboardRes)
      setMessages(messageRes.messages)
      setDrafts(draftRes.drafts)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load Herald')
    } finally {
      setLoading(false)
    }
  }, [selectedMailbox])

  useEffect(() => {
    load()
  }, [load])

  const totals = useMemo(() => {
    const inSelectedMailbox = (mailbox?: string | null) => (
      selectedMailbox === ALL_MAILBOXES || mailbox === selectedMailbox
    )
    const countFor = (classification: string) =>
      dashboard?.message_counts
        .filter((row) => row.classification === classification && inSelectedMailbox(row.mailbox))
        .reduce((sum, row) => sum + row.count, 0) ?? 0
    const draftNeedsReview = dashboard?.draft_counts
      .filter((row) => row.status === 'needs_review' && inSelectedMailbox(row.mailbox))
      .reduce((sum, row) => sum + row.count, 0) ?? 0
    return {
      leads: countFor('lead'),
      support: countFor('support'),
      press: countFor('press') + countFor('partner') + countFor('investor'),
      drafts: draftNeedsReview,
    }
  }, [dashboard, selectedMailbox])

  const selectedLabel = selectedMailbox === ALL_MAILBOXES ? 'all inboxes' : selectedMailbox

  const selectMailbox = (mailbox: string) => {
    setLoading(true)
    setSelectedMailbox(mailbox)
  }

  const runScan = async () => {
    setScanning(true)
    setNotice(null)
    try {
      const mailboxQuery = selectedMailbox === ALL_MAILBOXES ? '' : `&mailbox=${encodeURIComponent(selectedMailbox)}`
      const result = await apiJson<ScanResponse>(`/v1/at0-mail/scan?max_results=25${mailboxQuery}`, {
        method: 'POST',
      })
      setNotice(`Scan complete for ${selectedLabel}: ${result.messages_new} new / ${result.draft_proposals_created} drafts`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scan failed')
    } finally {
      setScanning(false)
    }
  }

  const setDraftStatus = async (draftId: string, status: 'approved' | 'rejected') => {
    setActingDraftId(draftId)
    setNotice(null)
    try {
      await apiJson(`/v1/at0-mail/drafts/${draftId}/status`, {
        method: 'POST',
        body: JSON.stringify({ status }),
      })
      setNotice(`Draft ${status}`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Draft update failed')
    } finally {
      setActingDraftId(null)
    }
  }

  const sendDraft = async (draftId: string) => {
    setActingDraftId(draftId)
    setNotice(null)
    try {
      const result = await apiJson<SendResponse>(`/v1/at0-mail/drafts/${draftId}/send`, {
        method: 'POST',
      })
      setNotice(`Reply sent from ${result.mailbox}`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Send failed')
      await load()
    } finally {
      setActingDraftId(null)
    }
  }

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="max-w-6xl space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex items-center gap-3">
          <div className={`flex h-10 w-10 items-center justify-center rounded-lg border ${border} ${panel}`}>
            <Inbox className="h-5 w-5 text-emerald-400" />
          </div>
          <div>
            <h1 className={`font-serif italic text-3xl ${strong}`}>Herald</h1>
            <p className={`mt-1 text-[10px] font-mono uppercase tracking-widest ${muted}`}>
              AT-0 mail intake
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className={`grid grid-cols-3 overflow-hidden rounded-lg border text-center text-[10px] font-mono uppercase ${border}`}>
            <div className={`px-3 py-2 ${panel}`}>read only</div>
            <div className={`border-x px-3 py-2 ${border}`}>scoped</div>
            <div className={`px-3 py-2 ${panel}`}>approved send</div>
          </div>
          <button
            type="button"
            onClick={runScan}
            disabled={scanning}
            className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-emerald-600 px-4 text-sm font-bold text-white transition hover:bg-emerald-500 disabled:opacity-45"
          >
            {scanning ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {selectedMailbox === ALL_MAILBOXES ? 'Scan all' : 'Scan inbox'}
          </button>
        </div>
      </div>

      <div className={`flex flex-col gap-3 rounded-xl border p-3 ${border} ${panel}`}>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => selectMailbox(ALL_MAILBOXES)}
            className={`min-h-10 max-w-full rounded-lg border px-3 text-left text-sm font-bold transition ${
              selectedMailbox === ALL_MAILBOXES
                ? 'border-emerald-400/50 bg-emerald-500/15 text-emerald-300'
                : `${border} ${strongPanel} ${muted}`
            }`}
          >
            All inboxes
          </button>
          {mailboxes.map((mailbox) => (
            <button
              key={mailbox}
              type="button"
              onClick={() => selectMailbox(mailbox)}
              className={`min-h-10 max-w-full break-all rounded-lg border px-3 text-left text-sm font-bold transition ${
                selectedMailbox === mailbox
                  ? 'border-emerald-400/50 bg-emerald-500/15 text-emerald-300'
                  : `${border} ${strongPanel} ${muted}`
              }`}
            >
              {mailbox}
            </button>
          ))}
        </div>
        <div className={`break-all text-[10px] font-mono uppercase tracking-widest ${muted}`}>
          Viewing {selectedLabel}
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
          {notice}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ['Leads', totals.leads],
          ['Support', totals.support],
          ['Press / partners', totals.press],
          ['Draft review', totals.drafts],
        ].map(([label, value]) => (
          <div key={label} className={`rounded-xl border p-4 ${border} ${panel}`}>
            <p className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>{label}</p>
            <p className="mt-3 text-3xl font-bold">{value}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <section className={`rounded-xl border ${border} ${panel} p-5`}>
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <MailCheck className="h-4 w-4 text-emerald-400" />
              <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>Recent mail</h2>
            </div>
            <span className={`text-[10px] font-mono uppercase ${muted}`}>
              {loading ? 'Loading' : `${messages.length} shown · ${selectedLabel}`}
            </span>
          </div>
          <div className="mt-4 space-y-3">
            {messages.map((message) => (
              <article key={message.id} className={`rounded-lg border p-4 ${border} ${strongPanel}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <Pill label={message.classification} />
                  <Pill label={message.priority} />
                  <span className={`ml-auto text-[10px] font-mono uppercase ${muted}`}>{message.mailbox}</span>
                </div>
                <h3 className="mt-3 line-clamp-1 text-sm font-bold">{message.subject ?? 'No subject'}</h3>
                <p className={`mt-1 text-xs ${muted}`}>
                  {message.sender_name ?? message.sender_email ?? 'Unknown sender'} · {timeText(message.received_at)}
                </p>
                <p className={`mt-3 line-clamp-2 text-sm ${muted}`}>{message.body_preview || message.classification_reason}</p>
              </article>
            ))}
            {!loading && messages.length === 0 && (
              <div className={`rounded-lg border p-4 text-sm ${border} ${muted}`}>No messages ingested yet.</div>
            )}
          </div>
        </section>

        <section className={`rounded-xl border ${border} ${panel} p-5`}>
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-emerald-400" />
              <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>AT-0 Spark drafts</h2>
            </div>
            <span className={`text-[10px] font-mono uppercase ${muted}`}>
              {selectedLabel} · Last scan {timeText(dashboard?.latest_scan?.finished_at ?? dashboard?.latest_scan?.started_at ?? null)}
            </span>
          </div>
          <div className="mt-4 space-y-4">
            {drafts.map((draft) => (
              <article key={draft.id} className={`rounded-lg border p-4 ${border} ${strongPanel}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <Pill label={draft.classification} />
                  <Pill label={draft.status} />
                  <span className={`ml-auto text-[10px] font-mono uppercase ${muted}`}>{draft.mailbox}</span>
                </div>
                <h3 className="mt-3 text-sm font-bold">{draft.reply_subject}</h3>
                <p className={`mt-1 text-xs ${muted}`}>
                  To {draft.recipient_email ?? 'unknown'} · {timeText(draft.created_at)}
                </p>
                <pre className={`mt-3 max-h-44 overflow-auto whitespace-pre-wrap rounded-lg border p-3 text-xs leading-relaxed ${border} ${panel}`}>
                  {draft.proposed_body}
                </pre>
                {draft.status === 'send_failed' && (
                  <div className="mt-3 rounded-lg border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                    {draft.send_error_message ?? 'Send failed. Review and retry.'}
                  </div>
                )}
                {draft.status === 'sent' && (
                  <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${border} ${panel}`}>
                    Sent {timeText(draft.sent_at)} · attempt {draft.send_attempt_count}
                  </div>
                )}
                {draft.status === 'needs_review' && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => setDraftStatus(draft.id, 'approved')}
                      disabled={actingDraftId === draft.id}
                      className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-emerald-600 px-3 text-sm font-bold text-white transition hover:bg-emerald-500 disabled:opacity-45"
                    >
                      <CheckCircle2 className="h-4 w-4" />
                      Approve
                    </button>
                    <button
                      type="button"
                      onClick={() => setDraftStatus(draft.id, 'rejected')}
                      disabled={actingDraftId === draft.id}
                      className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-bold transition ${border} ${panel} disabled:opacity-45`}
                    >
                      <XCircle className="h-4 w-4" />
                      Reject
                    </button>
                  </div>
                )}
                {(draft.status === 'approved' || draft.status === 'send_failed') && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => sendDraft(draft.id)}
                      disabled={actingDraftId === draft.id}
                      className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-emerald-600 px-3 text-sm font-bold text-white transition hover:bg-emerald-500 disabled:opacity-45"
                    >
                      {actingDraftId === draft.id ? (
                        <LoaderCircle className="h-4 w-4 animate-spin" />
                      ) : (
                        <Send className="h-4 w-4" />
                      )}
                      {draft.status === 'send_failed' ? 'Retry send' : 'Send reply'}
                    </button>
                  </div>
                )}
              </article>
            ))}
            {!loading && drafts.length === 0 && (
              <div className={`rounded-lg border p-4 text-sm ${border} ${muted}`}>No draft proposals for this inbox.</div>
            )}
          </div>
        </section>
      </div>
    </motion.div>
  )
}
