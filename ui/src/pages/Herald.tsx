import { useCallback, useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import {
  CheckCircle2,
  Archive,
  CalendarClock,
  ExternalLink,
  Inbox,
  LoaderCircle,
  MailCheck,
  Megaphone,
  MessageCircle,
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

interface GraphHealth {
  status: 'ok' | 'failed'
  trigger: string
  checked_at: string
  mailboxes_checked: number
  messages_seen: number
  graph_roles: string[]
  missing_graph_roles: string[]
  current_send_failures: number
  stuck_sending_count: number
  last_sent_at: string | null
  error_type: string | null
  requires_attention: boolean
}

interface HealthResponse {
  status: string
  requires_attention: boolean
  latest_graph_health: GraphHealth | null
}

type SocialPlatformKey = 'x' | 'linkedin'

interface SocialPlatformProfile {
  platform: SocialPlatformKey
  display_name: string
  account_label: string
  audience_notes: string
  voice_rules: string[]
  safety_rules: string[]
  max_chars: number
  profile_version: number
  active: boolean
}

interface SocialPlatformList {
  platforms: SocialPlatformProfile[]
}

interface SocialDraft {
  id: string
  request_id: string
  topic: string
  source_url: string | null
  campaign: string | null
  draft_kind: 'post' | 'reply'
  engagement_author: string | null
  platform: SocialPlatformKey
  account_label: string
  draft_text: string
  status: 'needs_review' | 'approved' | 'rejected' | 'archived'
  publish_status: 'not_scheduled' | 'scheduled' | 'manual_published' | 'sending' | 'linkedin_published' | 'publish_failed'
  scheduled_for: string | null
  published_at: string | null
  published_url: string | null
  publish_attempt_count: number
  last_publish_attempt_at: string | null
  publish_error_type: string | null
  publish_error_message: string | null
  provider_post_urn: string | null
  variant_version: number
  profile_version: number
  audience_notes: string
  voice_rules: string[]
  safety_rules: string[]
  voice_score: number
  safety_flags: string[]
  repeat_of_variant_id: string | null
  reviewer_notes: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  created_at: string
}

interface SocialDraftList {
  drafts: SocialDraft[]
}

interface SocialDraftCreateResponse {
  request_id: string
  drafts: SocialDraft[]
}

interface LinkedInCadence {
  today: string
  next_due_date: string
  last_published_at: string | null
  next_scheduled_for: string | null
  approved_ready_count: number
}

interface LinkedInReadPlan {
  status: 'planned_pending_linkedin_approval'
  write_scope: string
  required_read_scopes: string[]
  discovery_targets: string[]
  boundary: string[]
}

interface SocialEngagement {
  id: string
  platform: 'linkedin'
  source: 'manual' | 'linkedin_api'
  account_label: string
  provider_item_urn: string | null
  provider_post_urn: string | null
  item_url: string | null
  author_name: string
  item_text: string
  status: 'needs_reply' | 'draft_created' | 'ignored' | 'replied' | 'archived'
  reply_variant_id: string | null
  discovered_at: string
  created_at: string
  updated_at: string
}

interface SocialEngagementList {
  items: SocialEngagement[]
}

interface LinkedInScoutResponse {
  created_count: number
  skipped_count: number
  reason: string
  item_ids: string[]
}

interface LinkedInOperatorDashboard {
  post_due: boolean
  comments_due: number
  best_topic: string
  best_reply_style: 'strong_short' | 'practical' | 'warm'
  targets_ready: number
  approval_backlog: number
  active_thought_leaders: number
  metric_snapshots_30d: number
}

interface LinkedInMetricResponse {
  engagement_total: number
  engagement_rate: number
  spark_memory_saved: boolean
}

interface ThoughtLeaderTarget {
  id: string
  person_name: string
  company_name: string | null
  role_title: string | null
  profile_url: string | null
  topics: string[]
  priority: number
  relationship_notes: string | null
  last_interaction_at: string | null
  status: 'active' | 'paused' | 'archived'
}

interface ThoughtLeaderTargetList {
  targets: ThoughtLeaderTarget[]
}

interface MetricDraftInput {
  impressions: string
  reactions: string
  comments: string
  reposts: string
  profile_clicks: string
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

function dateText(value: string | null) {
  if (!value) return 'TBD'
  const date = new Date(`${value}T00:00:00`)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString([], {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
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

function replyStyleLabel(flags: string[]) {
  if (flags.includes('reply_style_strong_short')) return 'Strong short'
  if (flags.includes('reply_style_warm')) return 'Warm'
  if (flags.includes('reply_style_practical')) return 'Practical'
  return null
}

function replyStyleText(value?: string | null) {
  if (value === 'strong_short') return 'Strong short'
  if (value === 'warm') return 'Warm'
  return 'Practical'
}

function metricNumber(value: string | undefined) {
  const parsed = Number.parseInt(value || '0', 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0
}

function Pill({ label }: { label: string }) {
  return (
    <span className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${classTone(label)}`}>
      {label.replace(/_/g, ' ')}
    </span>
  )
}

function graphHealthTone(health: GraphHealth | null | undefined) {
  if (!health) return 'border-zinc-400/30 bg-zinc-500/10 text-zinc-400'
  if (health.requires_attention || health.status !== 'ok') {
    return 'border-rose-400/30 bg-rose-500/10 text-rose-300'
  }
  return 'border-emerald-400/30 bg-emerald-500/10 text-emerald-300'
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
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [mailboxes, setMailboxes] = useState<string[]>([])
  const [selectedMailbox, setSelectedMailbox] = useState(ALL_MAILBOXES)
  const [messages, setMessages] = useState<MailMessage[]>([])
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [socialProfiles, setSocialProfiles] = useState<SocialPlatformProfile[]>([])
  const [socialDrafts, setSocialDrafts] = useState<SocialDraft[]>([])
  const [linkedinCadence, setLinkedinCadence] = useState<LinkedInCadence | null>(null)
  const [linkedinReadPlan, setLinkedinReadPlan] = useState<LinkedInReadPlan | null>(null)
  const [linkedinOperatorDashboard, setLinkedinOperatorDashboard] = useState<LinkedInOperatorDashboard | null>(null)
  const [engagementItems, setEngagementItems] = useState<SocialEngagement[]>([])
  const [thoughtLeaders, setThoughtLeaders] = useState<ThoughtLeaderTarget[]>([])
  const [socialTopic, setSocialTopic] = useState('')
  const [socialSelectedPlatforms, setSocialSelectedPlatforms] = useState<SocialPlatformKey[]>(['x', 'linkedin'])
  const [engagementAuthor, setEngagementAuthor] = useState('')
  const [engagementUrl, setEngagementUrl] = useState('')
  const [engagementContext, setEngagementContext] = useState('')
  const [scoutTopics, setScoutTopics] = useState('AI and enterprise transformation, AT0 private AI progress')
  const [thoughtLeaderName, setThoughtLeaderName] = useState('')
  const [thoughtLeaderCompany, setThoughtLeaderCompany] = useState('')
  const [thoughtLeaderTopics, setThoughtLeaderTopics] = useState('enterprise AI, business transformation')
  const [thoughtLeaderNotes, setThoughtLeaderNotes] = useState('')
  const [scheduleDates, setScheduleDates] = useState<Record<string, string>>({})
  const [publishedUrls, setPublishedUrls] = useState<Record<string, string>>({})
  const [socialDraftFeedback, setSocialDraftFeedback] = useState<Record<string, string>>({})
  const [metricInputs, setMetricInputs] = useState<Record<string, MetricDraftInput>>({})
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [actingDraftId, setActingDraftId] = useState<string | null>(null)
  const [creatingSocialDraft, setCreatingSocialDraft] = useState(false)
  const [creatingLinkedinWeekly, setCreatingLinkedinWeekly] = useState(false)
  const [creatingEngagementDraft, setCreatingEngagementDraft] = useState(false)
  const [scoutingLinkedinTargets, setScoutingLinkedinTargets] = useState(false)
  const [creatingThoughtLeader, setCreatingThoughtLeader] = useState(false)
  const [recordingMetricId, setRecordingMetricId] = useState<string | null>(null)
  const [actingSocialDraftId, setActingSocialDraftId] = useState<string | null>(null)
  const [actingEngagementId, setActingEngagementId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const mailboxQuery = selectedMailbox === ALL_MAILBOXES ? '' : `&mailbox=${encodeURIComponent(selectedMailbox)}`
      const [
        mailboxRes,
        dashboardRes,
        messageRes,
        draftRes,
        healthRes,
        socialProfileRes,
        socialDraftRes,
        linkedinCadenceRes,
        linkedinReadPlanRes,
        linkedinOperatorDashboardRes,
        engagementRes,
        thoughtLeaderRes,
      ] = await Promise.all([
        apiJson<MailboxList>('/v1/at0-mail/mailboxes'),
        apiJson<Dashboard>('/v1/at0-mail/dashboard'),
        apiJson<MessageList>(`/v1/at0-mail/messages?limit=12${mailboxQuery}`),
        apiJson<DraftList>(`/v1/at0-mail/drafts?status=all&limit=12${mailboxQuery}`),
        apiJson<HealthResponse>('/v1/at0-mail/health'),
        apiJson<SocialPlatformList>('/v1/herald/social/platforms'),
        apiJson<SocialDraftList>('/v1/herald/social/drafts?status=all&limit=12'),
        apiJson<LinkedInCadence>('/v1/herald/social/linkedin/cadence'),
        apiJson<LinkedInReadPlan>('/v1/herald/social/linkedin/read-plan'),
        apiJson<LinkedInOperatorDashboard>('/v1/herald/social/linkedin/operator-dashboard'),
        apiJson<SocialEngagementList>('/v1/herald/social/linkedin/engagements?status=all&limit=12'),
        apiJson<ThoughtLeaderTargetList>('/v1/herald/social/linkedin/thought-leaders?status=active&limit=8'),
      ])
      setMailboxes(mailboxRes.mailboxes)
      if (selectedMailbox !== ALL_MAILBOXES && !mailboxRes.mailboxes.includes(selectedMailbox)) {
        setSelectedMailbox(ALL_MAILBOXES)
      }
      setDashboard(dashboardRes)
      setMessages(messageRes.messages)
      setDrafts(draftRes.drafts)
      setHealth(healthRes)
      setSocialProfiles(socialProfileRes.platforms)
      setSocialDrafts(socialDraftRes.drafts)
      setLinkedinCadence(linkedinCadenceRes)
      setLinkedinReadPlan(linkedinReadPlanRes)
      setLinkedinOperatorDashboard(linkedinOperatorDashboardRes)
      setEngagementItems(engagementRes.items)
      setThoughtLeaders(thoughtLeaderRes.targets)
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

  const approvedReplyVariantIds = useMemo(
    () => new Set(
      socialDrafts
        .filter((draft) => draft.draft_kind === 'reply' && draft.status === 'approved')
        .map((draft) => draft.id),
    ),
    [socialDrafts],
  )

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
  const graphHealth = health?.latest_graph_health ?? null

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

  const toggleSocialPlatform = (platform: SocialPlatformKey) => {
    setSocialSelectedPlatforms((current) => (
      current.includes(platform)
        ? current.filter((item) => item !== platform)
        : [...current, platform]
    ))
  }

  const createSocialDraft = async () => {
    const topic = socialTopic.trim()
    if (!topic) {
      setError('Social draft topic required')
      return
    }
    if (socialSelectedPlatforms.length === 0) {
      setError('Select at least one social platform')
      return
    }
    setCreatingSocialDraft(true)
    setNotice(null)
    try {
      const result = await apiJson<SocialDraftCreateResponse>('/v1/herald/social/drafts', {
        method: 'POST',
        body: JSON.stringify({
          topic,
          platforms: socialSelectedPlatforms,
          account_label: 'AT0',
        }),
      })
      setSocialTopic('')
      setNotice(`Social drafts created: ${result.drafts.length}`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Social draft failed')
    } finally {
      setCreatingSocialDraft(false)
    }
  }

  const createLinkedinWeeklyDraft = async () => {
    setCreatingLinkedinWeekly(true)
    setNotice(null)
    try {
      const result = await apiJson<SocialDraftCreateResponse>('/v1/herald/social/linkedin/weekly', {
        method: 'POST',
      })
      setNotice(`LinkedIn weekly draft created: ${result.drafts.length}`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'LinkedIn weekly draft failed')
    } finally {
      setCreatingLinkedinWeekly(false)
    }
  }

  const createLinkedinEngagementDraft = async () => {
    const itemText = engagementContext.trim()
    if (!itemText) {
      setError('Engagement context required')
      return
    }
    setCreatingEngagementDraft(true)
    setNotice(null)
    try {
      await apiJson<SocialEngagement>('/v1/herald/social/linkedin/engagements', {
        method: 'POST',
        body: JSON.stringify({
          item_text: itemText,
          author_name: engagementAuthor.trim() || 'LinkedIn member',
          item_url: engagementUrl.trim() || undefined,
          account_label: 'AT0',
        }),
      })
      setEngagementAuthor('')
      setEngagementUrl('')
      setEngagementContext('')
      setNotice('LinkedIn engagement added')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'LinkedIn engagement add failed')
    } finally {
      setCreatingEngagementDraft(false)
    }
  }

  const scoutLinkedinTargets = async () => {
    const topics = scoutTopics
      .split(/[\n,]/)
      .map((item) => item.trim())
      .filter(Boolean)
    setScoutingLinkedinTargets(true)
    setNotice(null)
    try {
      const result = await apiJson<LinkedInScoutResponse>('/v1/herald/social/linkedin/engagements/scout', {
        method: 'POST',
        body: JSON.stringify({
          topics,
          per_topic: 2,
          max_targets: 6,
        }),
      })
      setNotice(`LinkedIn targets scouted: ${result.created_count} new, ${result.skipped_count} skipped`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'LinkedIn target scout failed')
    } finally {
      setScoutingLinkedinTargets(false)
    }
  }

  const createThoughtLeaderTarget = async () => {
    const name = thoughtLeaderName.trim()
    if (!name) {
      setError('Thought leader name required')
      return
    }
    const topics = thoughtLeaderTopics
      .split(/[\n,]/)
      .map((item) => item.trim())
      .filter(Boolean)
    setCreatingThoughtLeader(true)
    setNotice(null)
    try {
      await apiJson<ThoughtLeaderTarget>('/v1/herald/social/linkedin/thought-leaders', {
        method: 'POST',
        body: JSON.stringify({
          person_name: name,
          company_name: thoughtLeaderCompany.trim() || undefined,
          topics,
          priority: 3,
          relationship_notes: thoughtLeaderNotes.trim() || undefined,
        }),
      })
      setThoughtLeaderName('')
      setThoughtLeaderCompany('')
      setThoughtLeaderNotes('')
      setNotice('Thought leader target added')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Thought leader add failed')
    } finally {
      setCreatingThoughtLeader(false)
    }
  }

  const draftLinkedinEngagementReply = async (itemId: string) => {
    setActingEngagementId(itemId)
    setNotice(null)
    try {
      const result = await apiJson<SocialDraftCreateResponse>(`/v1/herald/social/linkedin/engagements/${itemId}/draft-reply`, {
        method: 'POST',
      })
      setNotice(`LinkedIn reply options created: ${result.drafts.length}`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'LinkedIn reply draft failed')
    } finally {
      setActingEngagementId(null)
    }
  }

  const publishLinkedinEngagementReply = async (itemId: string) => {
    setActingEngagementId(itemId)
    setNotice(null)
    try {
      await apiJson(`/v1/herald/social/linkedin/engagements/${itemId}/publish-reply`, {
        method: 'POST',
      })
      setNotice('LinkedIn reply published')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'LinkedIn reply publish failed')
      await load()
    } finally {
      setActingEngagementId(null)
    }
  }

  const setEngagementStatus = async (itemId: string, status: 'ignored' | 'replied' | 'archived') => {
    setActingEngagementId(itemId)
    setNotice(null)
    try {
      await apiJson(`/v1/herald/social/linkedin/engagements/${itemId}/status`, {
        method: 'POST',
        body: JSON.stringify({ status }),
      })
      setNotice(`LinkedIn engagement ${status}`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'LinkedIn engagement update failed')
    } finally {
      setActingEngagementId(null)
    }
  }

  const setSocialDraftStatus = async (draftId: string, status: 'approved' | 'rejected' | 'archived') => {
    const reviewerNotes = socialDraftFeedback[draftId]?.trim()
    setActingSocialDraftId(draftId)
    setNotice(null)
    try {
      await apiJson(`/v1/herald/social/drafts/${draftId}/status`, {
        method: 'POST',
        body: JSON.stringify({
          status,
          reviewer_notes: reviewerNotes || undefined,
        }),
      })
      setSocialDraftFeedback((current) => {
        const next = { ...current }
        delete next[draftId]
        return next
      })
      setNotice(`Social draft ${status}`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Social draft update failed')
    } finally {
      setActingSocialDraftId(null)
    }
  }

  const scheduleSocialDraft = async (draftId: string) => {
    const scheduledFor = scheduleDates[draftId]
    if (!scheduledFor) {
      setError('Schedule date required')
      return
    }
    setActingSocialDraftId(draftId)
    setNotice(null)
    try {
      await apiJson(`/v1/herald/social/drafts/${draftId}/schedule`, {
        method: 'POST',
        body: JSON.stringify({ scheduled_for: scheduledFor }),
      })
      setNotice('LinkedIn draft scheduled')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'LinkedIn schedule failed')
    } finally {
      setActingSocialDraftId(null)
    }
  }

  const markSocialDraftPublished = async (draftId: string) => {
    const publishedUrl = publishedUrls[draftId]?.trim()
    if (!publishedUrl) {
      setError('Published URL required')
      return
    }
    setActingSocialDraftId(draftId)
    setNotice(null)
    try {
      await apiJson(`/v1/herald/social/drafts/${draftId}/publish/manual`, {
        method: 'POST',
        body: JSON.stringify({ published_url: publishedUrl }),
      })
      setNotice('LinkedIn manual publish recorded')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'LinkedIn publish receipt failed')
    } finally {
      setActingSocialDraftId(null)
    }
  }

  const publishLinkedinDraft = async (draftId: string) => {
    setActingSocialDraftId(draftId)
    setNotice(null)
    try {
      await apiJson(`/v1/herald/social/drafts/${draftId}/publish/linkedin`, {
        method: 'POST',
      })
      setNotice('LinkedIn post published')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'LinkedIn publish failed')
      await load()
    } finally {
      setActingSocialDraftId(null)
    }
  }

  const setMetricInput = (draftId: string, field: keyof MetricDraftInput, value: string) => {
    setMetricInputs((current) => {
      const input = current[draftId] ?? {
        impressions: '',
        reactions: '',
        comments: '',
        reposts: '',
        profile_clicks: '',
      }
      return {
        ...current,
        [draftId]: {
          ...input,
          [field]: value,
        },
      }
    })
  }

  const recordSocialMetrics = async (draftId: string) => {
    const input = metricInputs[draftId] ?? {
      impressions: '',
      reactions: '',
      comments: '',
      reposts: '',
      profile_clicks: '',
    }
    setRecordingMetricId(draftId)
    setNotice(null)
    try {
      const result = await apiJson<LinkedInMetricResponse>('/v1/herald/social/linkedin/metrics', {
        method: 'POST',
        body: JSON.stringify({
          variant_id: draftId,
          impressions: metricNumber(input.impressions),
          reactions: metricNumber(input.reactions),
          comments: metricNumber(input.comments),
          reposts: metricNumber(input.reposts),
          profile_clicks: metricNumber(input.profile_clicks),
        }),
      })
      setMetricInputs((current) => {
        const next = { ...current }
        delete next[draftId]
        return next
      })
      setNotice(
        `Metrics recorded: ${result.engagement_total} engagements${result.spark_memory_saved ? ' · Spark updated' : ''}`,
      )
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Metric record failed')
    } finally {
      setRecordingMetricId(null)
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
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
          <div className={`rounded-lg border p-3 ${border} ${strongPanel}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${graphHealthTone(graphHealth)}`}>
                {graphHealth ? `Graph send ${graphHealth.status}` : 'Graph send unknown'}
              </span>
              <span className={`text-[10px] font-mono uppercase ${muted}`}>
                {graphHealth ? `checked ${timeText(graphHealth.checked_at)}` : 'no monitor row'}
              </span>
            </div>
            <div className={`mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] ${muted}`}>
              <span>Mailboxes <span className={strong}>{graphHealth?.mailboxes_checked ?? 0}</span></span>
              <span>Mail.Send <span className={graphHealth?.graph_roles.includes('Mail.Send') ? 'text-emerald-300' : 'text-rose-300'}>
                {graphHealth?.graph_roles.includes('Mail.Send') ? 'present' : 'missing'}
              </span></span>
              <span>Failures <span className={graphHealth?.current_send_failures ? 'text-rose-300' : strong}>
                {graphHealth?.current_send_failures ?? 0}
              </span></span>
              <span>Stuck <span className={graphHealth?.stuck_sending_count ? 'text-rose-300' : strong}>
                {graphHealth?.stuck_sending_count ?? 0}
              </span></span>
              <span>Last sent <span className={strong}>{timeText(graphHealth?.last_sent_at ?? null)}</span></span>
            </div>
          </div>
          <div className={`rounded-lg border p-3 ${border} ${strongPanel}`}>
            <div className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>Send mode</div>
            <div className={`mt-2 text-sm font-bold ${strong}`}>Approved drafts only</div>
          </div>
        </div>
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

      <section className={`rounded-xl border ${border} ${panel} p-5`}>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex items-center gap-2">
            <Megaphone className="h-4 w-4 text-amber-400" />
            <div>
              <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>Social approval outbox</h2>
              <p className={`mt-1 text-sm ${muted}`}>AT0 Spark · draft only · {socialDrafts.length} variants</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {socialProfiles.map((profile) => (
              <label
                key={profile.platform}
                className={`inline-flex min-h-10 cursor-pointer items-center gap-2 rounded-lg border px-3 text-sm font-bold ${border} ${strongPanel}`}
              >
                <input
                  type="checkbox"
                  checked={socialSelectedPlatforms.includes(profile.platform)}
                  onChange={() => toggleSocialPlatform(profile.platform)}
                  className="h-4 w-4 accent-emerald-500"
                />
                {profile.display_name}
              </label>
            ))}
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
          {[
            ['Post due', linkedinOperatorDashboard?.post_due ? 'Yes' : 'No'],
            ['Comments due', linkedinOperatorDashboard?.comments_due ?? 0],
            ['Targets ready', linkedinOperatorDashboard?.targets_ready ?? 0],
            ['Approval backlog', linkedinOperatorDashboard?.approval_backlog ?? 0],
            ['Thought leaders', linkedinOperatorDashboard?.active_thought_leaders ?? 0],
            ['Metrics 30d', linkedinOperatorDashboard?.metric_snapshots_30d ?? 0],
          ].map(([label, value]) => (
            <div key={label} className={`rounded-lg border p-3 ${border} ${strongPanel}`}>
              <p className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>{label}</p>
              <p className={`mt-2 text-lg font-bold ${strong}`}>{value}</p>
            </div>
          ))}
        </div>
        <div className={`mt-3 rounded-lg border p-3 text-xs ${border} ${strongPanel}`}>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <span>Best topic <span className={strong}>{linkedinOperatorDashboard?.best_topic ?? 'TBD'}</span></span>
            <span>Best style <span className={strong}>{replyStyleText(linkedinOperatorDashboard?.best_reply_style)}</span></span>
          </div>
        </div>

        <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
          <div className={`rounded-lg border p-4 ${border} ${strongPanel}`}>
            <div className={`rounded-lg border p-3 ${border} ${panel}`}>
              <div className="flex flex-wrap items-center gap-2">
                <Pill label="LinkedIn weekly" />
                <span className={`text-[10px] font-mono uppercase ${muted}`}>
                  next due {dateText(linkedinCadence?.next_due_date ?? null)}
                </span>
              </div>
              <div className={`mt-2 grid gap-2 text-xs ${muted}`}>
                <span>Last published <span className={strong}>{timeText(linkedinCadence?.last_published_at ?? null)}</span></span>
                <span>Next scheduled <span className={strong}>{dateText(linkedinCadence?.next_scheduled_for ?? null)}</span></span>
                <span>Approved ready <span className={strong}>{linkedinCadence?.approved_ready_count ?? 0}</span></span>
              </div>
              <button
                type="button"
                onClick={createLinkedinWeeklyDraft}
                disabled={creatingLinkedinWeekly}
                className="mt-3 inline-flex min-h-10 items-center gap-2 rounded-lg bg-[#0a66c2] px-4 text-sm font-bold text-white transition hover:bg-[#0957a5] disabled:opacity-45"
              >
                {creatingLinkedinWeekly ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <CalendarClock className="h-4 w-4" />}
                Draft weekly LinkedIn
              </button>
            </div>

            <label className={`mt-5 block text-[10px] font-mono uppercase tracking-widest ${muted}`} htmlFor="social-topic">
              Topic
            </label>
            <textarea
              id="social-topic"
              value={socialTopic}
              onChange={(event) => setSocialTopic(event.target.value)}
              rows={5}
              className={`mt-2 w-full resize-none rounded-lg border px-3 py-2 text-sm outline-none ${border} ${panel} ${strong}`}
              placeholder="What should Herald draft?"
            />
            <button
              type="button"
              onClick={createSocialDraft}
              disabled={creatingSocialDraft}
              className="mt-3 inline-flex min-h-10 items-center gap-2 rounded-lg bg-amber-500 px-4 text-sm font-bold text-[#141414] transition hover:bg-amber-400 disabled:opacity-45"
            >
              {creatingSocialDraft ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Megaphone className="h-4 w-4" />}
              Draft social
            </button>

            <div className={`mt-5 rounded-lg border p-3 ${border} ${panel}`}>
              <div className="flex items-center gap-2">
                <MessageCircle className="h-4 w-4 text-sky-400" />
                <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
                  LinkedIn engagement inbox
                </span>
              </div>
              <div className={`mt-2 flex flex-wrap gap-2 text-[10px] font-mono uppercase ${muted}`}>
                <Pill label={`write ${linkedinReadPlan?.write_scope ?? 'w_member_social_feed'}`} />
                <Pill label={`read ${linkedinReadPlan?.required_read_scopes.join(', ') ?? 'r_member_social_feed'} pending`} />
                <Pill label={`${engagementItems.length} items`} />
              </div>
              <label className={`mt-3 block text-[10px] font-mono uppercase tracking-widest ${muted}`} htmlFor="linkedin-scout-topics">
                Scout topics
              </label>
              <textarea
                id="linkedin-scout-topics"
                value={scoutTopics}
                onChange={(event) => setScoutTopics(event.target.value)}
                rows={3}
                className={`mt-2 w-full resize-none rounded-lg border px-3 py-2 text-sm outline-none ${border} ${strongPanel} ${strong}`}
                placeholder="AI transformation, enterprise operating model"
              />
              <button
                type="button"
                onClick={scoutLinkedinTargets}
                disabled={scoutingLinkedinTargets}
                className="mt-3 inline-flex min-h-10 items-center gap-2 rounded-lg bg-emerald-600 px-4 text-sm font-bold text-white transition hover:bg-emerald-500 disabled:opacity-45"
              >
                {scoutingLinkedinTargets ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                Scout targets
              </button>
              <div className="mt-3 grid gap-2">
                <input
                  value={engagementAuthor}
                  onChange={(event) => setEngagementAuthor(event.target.value)}
                  className={`min-h-10 rounded-lg border px-3 text-sm outline-none ${border} ${strongPanel} ${strong}`}
                  placeholder="Author name"
                />
                <input
                  value={engagementUrl}
                  onChange={(event) => setEngagementUrl(event.target.value)}
                  className={`min-h-10 rounded-lg border px-3 text-sm outline-none ${border} ${strongPanel} ${strong}`}
                  placeholder="LinkedIn URL"
                />
                <textarea
                  value={engagementContext}
                  onChange={(event) => setEngagementContext(event.target.value)}
                  rows={4}
                  className={`w-full resize-none rounded-lg border px-3 py-2 text-sm outline-none ${border} ${strongPanel} ${strong}`}
                  placeholder="What should Herald respond to?"
                />
              </div>
              <button
                type="button"
                onClick={createLinkedinEngagementDraft}
                disabled={creatingEngagementDraft}
                className="mt-3 inline-flex min-h-10 items-center gap-2 rounded-lg bg-sky-600 px-4 text-sm font-bold text-white transition hover:bg-sky-500 disabled:opacity-45"
              >
                {creatingEngagementDraft ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <MessageCircle className="h-4 w-4" />}
                Add to inbox
              </button>

              <div className="mt-4 space-y-2">
                {engagementItems.map((item) => (
                  <article key={item.id} className={`rounded-lg border p-3 ${border} ${strongPanel}`}>
                    <div className="flex flex-wrap items-center gap-2">
                      <Pill label={item.provider_item_urn?.startsWith('herald:scout:') ? 'Scout' : item.source === 'linkedin_api' ? 'LinkedIn API' : 'Manual'} />
                      <Pill label={item.status} />
                      <span className={`ml-auto text-[10px] font-mono uppercase ${muted}`}>
                        {timeText(item.discovered_at)}
                      </span>
                    </div>
                    <div className="mt-2 text-sm font-bold">{item.author_name}</div>
                    <p className={`mt-1 line-clamp-3 text-xs ${muted}`}>{item.item_text}</p>
                    {item.item_url && (
                      <a href={item.item_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs text-sky-300">
                        Source <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => draftLinkedinEngagementReply(item.id)}
                        disabled={actingEngagementId === item.id}
                        className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-sky-600 px-3 text-sm font-bold text-white transition hover:bg-sky-500 disabled:opacity-45"
                      >
                        {actingEngagementId === item.id ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <MessageCircle className="h-4 w-4" />}
                        Draft reply
                      </button>
                      {item.reply_variant_id && item.status === 'draft_created' && (
                        <button
                          type="button"
                          onClick={() => publishLinkedinEngagementReply(item.id)}
                          disabled={
                            actingEngagementId === item.id
                            || !approvedReplyVariantIds.has(item.reply_variant_id)
                          }
                          className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-[#0a66c2] px-3 text-sm font-bold text-white transition hover:bg-[#0957a5] disabled:opacity-45"
                        >
                          {actingEngagementId === item.id ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                          Post reply
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => setEngagementStatus(item.id, 'ignored')}
                        disabled={actingEngagementId === item.id}
                        className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-bold transition ${border} ${strongPanel} disabled:opacity-45`}
                      >
                        Ignore
                      </button>
                    </div>
                  </article>
                ))}
                {!loading && engagementItems.length === 0 && (
                  <div className={`rounded-lg border p-3 text-xs ${border} ${muted}`}>No LinkedIn items need reply.</div>
                )}
              </div>
            </div>

            <div className={`mt-5 rounded-lg border p-3 ${border} ${panel}`}>
              <div className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-emerald-400" />
                <span className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
                  Thought-leader target graph
                </span>
              </div>
              <div className="mt-3 grid gap-2">
                <input
                  value={thoughtLeaderName}
                  onChange={(event) => setThoughtLeaderName(event.target.value)}
                  className={`min-h-10 rounded-lg border px-3 text-sm outline-none ${border} ${strongPanel} ${strong}`}
                  placeholder="Person"
                />
                <input
                  value={thoughtLeaderCompany}
                  onChange={(event) => setThoughtLeaderCompany(event.target.value)}
                  className={`min-h-10 rounded-lg border px-3 text-sm outline-none ${border} ${strongPanel} ${strong}`}
                  placeholder="Company"
                />
                <input
                  value={thoughtLeaderTopics}
                  onChange={(event) => setThoughtLeaderTopics(event.target.value)}
                  className={`min-h-10 rounded-lg border px-3 text-sm outline-none ${border} ${strongPanel} ${strong}`}
                  placeholder="Topics"
                />
                <textarea
                  value={thoughtLeaderNotes}
                  onChange={(event) => setThoughtLeaderNotes(event.target.value)}
                  rows={3}
                  className={`resize-none rounded-lg border px-3 py-2 text-sm outline-none ${border} ${strongPanel} ${strong}`}
                  placeholder="Relationship notes"
                />
              </div>
              <button
                type="button"
                onClick={createThoughtLeaderTarget}
                disabled={creatingThoughtLeader}
                className="mt-3 inline-flex min-h-10 items-center gap-2 rounded-lg bg-emerald-600 px-4 text-sm font-bold text-white transition hover:bg-emerald-500 disabled:opacity-45"
              >
                {creatingThoughtLeader ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                Add target
              </button>
              <div className="mt-4 space-y-2">
                {thoughtLeaders.map((target) => (
                  <div key={target.id} className={`rounded-lg border p-3 ${border} ${strongPanel}`}>
                    <div className="flex flex-wrap items-center gap-2">
                      <Pill label={`P${target.priority}`} />
                      <span className={`text-sm font-bold ${strong}`}>{target.person_name}</span>
                      {target.company_name && <span className={`text-xs ${muted}`}>{target.company_name}</span>}
                    </div>
                    {target.relationship_notes && (
                      <p className={`mt-2 line-clamp-2 text-xs ${muted}`}>{target.relationship_notes}</p>
                    )}
                    <div className="mt-2 flex flex-wrap gap-1">
                      {target.topics.slice(0, 3).map((topic) => (
                        <span key={topic} className={`rounded-md border px-2 py-1 text-[10px] ${border} ${panel}`}>
                          {topic}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-5 space-y-3">
              {socialProfiles.map((profile) => (
                <div key={profile.platform} className={`rounded-lg border p-3 ${border} ${panel}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <Pill label={profile.display_name} />
                    <span className={`text-[10px] font-mono uppercase ${muted}`}>v{profile.profile_version}</span>
                  </div>
                  <p className={`mt-2 text-xs ${muted}`}>{profile.audience_notes}</p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {profile.voice_rules.slice(0, 3).map((rule) => (
                      <span key={rule} className={`rounded-md border px-2 py-1 text-[10px] ${border} ${strongPanel}`}>
                        {rule}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-4">
            {socialDrafts.map((draft) => (
              <article key={draft.id} className={`rounded-lg border p-4 ${border} ${strongPanel}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <Pill label={draft.platform === 'x' ? 'X' : 'LinkedIn'} />
                  <Pill label={draft.draft_kind} />
                  {draft.draft_kind === 'reply' && replyStyleLabel(draft.safety_flags) && (
                    <Pill label={replyStyleLabel(draft.safety_flags) ?? ''} />
                  )}
                  <Pill label={draft.status} />
                  <Pill label={draft.publish_status} />
                  <span className={`ml-auto text-[10px] font-mono uppercase ${muted}`}>
                    Voice {Math.round(draft.voice_score * 100)}%
                  </span>
                </div>
                <h3 className="mt-3 line-clamp-2 text-sm font-bold">{draft.topic}</h3>
                <div className={`mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs ${muted}`}>
                  {draft.engagement_author && <span>Reply to <span className={strong}>{draft.engagement_author}</span></span>}
                  {draft.scheduled_for && <span>Scheduled <span className={strong}>{dateText(draft.scheduled_for)}</span></span>}
                  {draft.published_at && <span>Published <span className={strong}>{timeText(draft.published_at)}</span></span>}
                  {draft.published_url && (
                    <a
                      href={draft.published_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-sky-300"
                    >
                      Published URL <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                  {draft.source_url && (
                    <a
                      href={draft.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-sky-300"
                    >
                      Source <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                </div>
                <pre className={`mt-3 max-h-52 overflow-auto whitespace-pre-wrap rounded-lg border p-3 text-xs leading-relaxed ${border} ${panel}`}>
                  {draft.draft_text}
                </pre>
                <div className="mt-3 flex flex-wrap gap-1">
                  {draft.safety_flags.map((flag) => (
                    <span key={flag} className={`rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${classTone(flag)}`}>
                      {flag.replace(/_/g, ' ')}
                    </span>
                  ))}
                  {draft.repeat_of_variant_id && (
                    <span className="rounded-md border border-amber-400/30 bg-amber-500/10 px-2 py-1 text-[10px] font-mono uppercase text-amber-300">
                      possible repeat
                    </span>
                  )}
                </div>
                {draft.publish_status === 'publish_failed' && (
                  <div className="mt-3 rounded-lg border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                    {draft.publish_error_message ?? draft.publish_error_type ?? 'LinkedIn publish failed'}
                  </div>
                )}
                {draft.platform === 'linkedin' && draft.draft_kind === 'post' && draft.status === 'approved' && !['manual_published', 'linkedin_published'].includes(draft.publish_status) && (
                  <div className={`mt-3 grid gap-2 rounded-lg border p-3 ${border} ${panel}`}>
                    <button
                      type="button"
                      onClick={() => publishLinkedinDraft(draft.id)}
                      disabled={actingSocialDraftId === draft.id || draft.publish_status === 'sending'}
                      className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-[#0a66c2] px-3 text-sm font-bold text-white transition hover:bg-[#0957a5] disabled:opacity-45"
                    >
                      {draft.publish_status === 'sending' ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                      Post to LinkedIn
                    </button>
                    <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                      <input
                        type="date"
                        value={scheduleDates[draft.id] ?? draft.scheduled_for ?? ''}
                        onChange={(event) => setScheduleDates((current) => ({
                          ...current,
                          [draft.id]: event.target.value,
                        }))}
                        className={`min-h-10 rounded-lg border px-3 text-sm outline-none ${border} ${strongPanel} ${strong}`}
                      />
                      <button
                        type="button"
                        onClick={() => scheduleSocialDraft(draft.id)}
                        disabled={actingSocialDraftId === draft.id}
                        className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border px-3 text-sm font-bold transition ${border} ${strongPanel} disabled:opacity-45`}
                      >
                        <CalendarClock className="h-4 w-4" />
                        Schedule
                      </button>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                      <input
                        value={publishedUrls[draft.id] ?? draft.published_url ?? ''}
                        onChange={(event) => setPublishedUrls((current) => ({
                          ...current,
                          [draft.id]: event.target.value,
                        }))}
                        className={`min-h-10 rounded-lg border px-3 text-sm outline-none ${border} ${strongPanel} ${strong}`}
                        placeholder="LinkedIn published URL"
                      />
                      <button
                        type="button"
                        onClick={() => markSocialDraftPublished(draft.id)}
                        disabled={actingSocialDraftId === draft.id}
                        className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-[#0a66c2] px-3 text-sm font-bold text-white transition hover:bg-[#0957a5] disabled:opacity-45"
                      >
                        <CheckCircle2 className="h-4 w-4" />
                        Mark published
                      </button>
                    </div>
                  </div>
                )}
                {draft.platform === 'linkedin' && ['manual_published', 'linkedin_published'].includes(draft.publish_status) && (
                  <div className={`mt-3 rounded-lg border p-3 ${border} ${panel}`}>
                    <div className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>Analytics feedback loop</div>
                    <div className="mt-2 grid gap-2 sm:grid-cols-5">
                      {[
                        ['impressions', 'Impressions'],
                        ['reactions', 'Reactions'],
                        ['comments', 'Comments'],
                        ['reposts', 'Reposts'],
                        ['profile_clicks', 'Clicks'],
                      ].map(([field, label]) => (
                        <input
                          key={field}
                          type="number"
                          min="0"
                          inputMode="numeric"
                          value={metricInputs[draft.id]?.[field as keyof MetricDraftInput] ?? ''}
                          onChange={(event) => setMetricInput(draft.id, field as keyof MetricDraftInput, event.target.value)}
                          className={`min-h-10 rounded-lg border px-2 text-sm outline-none ${border} ${strongPanel} ${strong}`}
                          placeholder={label}
                        />
                      ))}
                    </div>
                    <button
                      type="button"
                      onClick={() => recordSocialMetrics(draft.id)}
                      disabled={recordingMetricId === draft.id}
                      className="mt-2 inline-flex min-h-10 items-center gap-2 rounded-lg bg-emerald-600 px-3 text-sm font-bold text-white transition hover:bg-emerald-500 disabled:opacity-45"
                    >
                      {recordingMetricId === draft.id ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                      Record metrics
                    </button>
                  </div>
                )}
                {draft.status === 'needs_review' && (
                  <div className="mt-3 space-y-2">
                    <textarea
                      value={socialDraftFeedback[draft.id] ?? ''}
                      onChange={(event) => setSocialDraftFeedback((current) => ({
                        ...current,
                        [draft.id]: event.target.value,
                      }))}
                      placeholder="Feedback for rejection or next draft"
                      className={`min-h-20 w-full rounded-lg border px-3 py-2 text-sm outline-none ${border} ${panel} ${strong}`}
                    />
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => setSocialDraftStatus(draft.id, 'approved')}
                        disabled={actingSocialDraftId === draft.id}
                        className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-emerald-600 px-3 text-sm font-bold text-white transition hover:bg-emerald-500 disabled:opacity-45"
                      >
                        <CheckCircle2 className="h-4 w-4" />
                        Approve
                      </button>
                      <button
                        type="button"
                        onClick={() => setSocialDraftStatus(draft.id, 'rejected')}
                        disabled={actingSocialDraftId === draft.id}
                        className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-bold transition ${border} ${panel} disabled:opacity-45`}
                      >
                        <XCircle className="h-4 w-4" />
                        Reject
                      </button>
                      <button
                        type="button"
                        onClick={() => setSocialDraftStatus(draft.id, 'archived')}
                        disabled={actingSocialDraftId === draft.id}
                        className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-bold transition ${border} ${panel} disabled:opacity-45`}
                      >
                        <Archive className="h-4 w-4" />
                        Archive
                      </button>
                    </div>
                  </div>
                )}
                {draft.status !== 'needs_review' && draft.reviewer_notes && (
                  <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${border} ${panel}`}>
                    Feedback: {draft.reviewer_notes}
                  </div>
                )}
              </article>
            ))}
            {!loading && socialDrafts.length === 0 && (
              <div className={`rounded-lg border p-4 text-sm ${border} ${muted}`}>No social drafts yet.</div>
            )}
          </div>
        </div>
      </section>

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
