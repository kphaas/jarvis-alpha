# Herald AT-0 Mail Runbook

Updated: 2026-06-26

## Scope

Herald MVP is the AT-0 mail-intake and approved-reply production slice:

- Read approved AT-0 Microsoft Graph mailboxes.
- Classify inbound messages into business-intent buckets.
- Create local AT-0 Spark reply drafts.
- Send only drafts that were explicitly approved in Alpha.
- Record append-only send audit events and Graph/send monitor health.

The social-presence Herald module now has a draft-only approval outbox. It does
not publish to social platforms yet.

The press-outreach lane is also draft-only. It maintains sourced targets and
weekly pitch drafts, but does not auto-send pitches or scrape contact data.

## Runtime

| Surface | Value |
|---|---|
| UI | `/herald` |
| API routes | `/v1/at0-mail/*` |
| Scanner LaunchAgent | `com.jarvis.alpha.at0-mail` |
| Graph health LaunchAgent | `com.jarvis.alpha.at0-mail-health` |
| Scanner cadence | hourly |
| Graph health cadence | 15 minutes |
| Freshness window | `AT0_HERALD_STALE_AFTER_MINUTES`, default 180 |

## Mailbox Scope

Current approved mailboxes:

- `hello@at-0.com`
- `support@at-0.com`

Microsoft Graph `Mail.Send` is restricted with an Exchange Application Access
Policy scoped to `at0-herald-approved-mailboxes@at-0.com`.

## Production Checks

Run the live smoke after deploy:

```bash
bash ~/jarvis-alpha/scripts/smoke_at0_herald_mail.sh
```

Run the focused restore drill:

```bash
bash ~/jarvis-alpha/scripts/smoke_at0_herald_restore_drill.sh
```

Run the Graph/send monitor one-shot:

```bash
cd ~/jarvis-alpha
set -a && source ~/jarvis/.secrets && set +a
PYTHONPATH="$(pwd)/common${PYTHONPATH:+:$PYTHONPATH}" \
  .venv/bin/python3.12 -m brain.agents.at0_mail_health_watcher \
  --trigger smoke --max-results 1
```

Expected health:

- `/v1/at0-mail/health` returns `status=ok`.
- `latest_graph_health.status=ok`.
- `graph_roles` includes `Mail.Send`.
- `missing_graph_roles=[]`.
- `current_send_failures=0`.
- `stuck_sending_count=0`.

## Failure Triage

| Symptom | Check | Action |
|---|---|---|
| `missing_graph_roles` includes `Mail.Send` | Azure app permission/admin consent | Restore `Mail.Send` application permission and rerun monitor |
| `current_send_failures > 0` | Herald UI draft list and `alpha_at0_mail_send_events` | Inspect failure type, correct Graph/mailbox issue, retry approved draft |
| `stuck_sending_count > 0` | Drafts with `status='sending'` and old `last_send_attempt_at` | Treat as interrupted send; inspect send events before manual remediation |
| Health `stale` | `com.jarvis.alpha.at0-mail` | Reload scanner LaunchAgent and run mail smoke |
| Graph health unavailable | `com.jarvis.alpha.at0-mail-health` | Reload health LaunchAgent and run one-shot monitor |
| Mailbox denied unexpectedly | Exchange Application Access Policy | Test allowed and denied mailboxes before changing scope |

## Backup + Restore Evidence

The focused drill covers:

- `public.alpha_at0_mail_scan_runs`
- `public.alpha_at0_mail_messages`
- `public.alpha_at0_mail_draft_proposals`
- `public.alpha_at0_mail_send_events`
- `public.alpha_at0_mail_graph_health`

Reports are written to `docs/reports/herald_restore_drill_YYYY-MM-DD.md`.
They intentionally include row counts and metadata only, not mail body previews,
reply text, Graph tokens, or secrets.

## Social Media Track

Herald can draft and review social posts locally, but cannot publish or ingest
social inboxes yet. Current repo state has:

- Product spec: `docs/specs/jarvis-herald-spec.md`
- Gap memory: `docs/runbooks/herald_social_gap_memory.md`
- Draft-only API: `/v1/herald/social/*`
- UI surface: `/herald` → Social approval outbox
- LinkedIn needs-reply inbox: `/v1/herald/social/linkedin/engagements`
- Read plan: `/v1/herald/social/linkedin/read-plan` (`r_member_social` pending)
- Smoke: `bash ~/jarvis-alpha/scripts/smoke_herald_social_outbox.sh`
- Marketing/social drafting docs and brand assets
- Per-platform voice profiles for X and LinkedIn
- No automated social account read connector for X, LinkedIn, Instagram,
  Threads, TikTok, Bluesky, or Mastodon

Recommended next slice: LinkedIn `r_member_social` approval, connector health,
rate caps, and automated ingestion into the existing needs-reply inbox.

## Press Outreach Track

Herald can now support AT0 press work as a reviewable drafting loop:

- Runbook and 30 sourced targets: `docs/runbooks/herald_press_outreach.md`
- First weekly draft batch: `docs/runbooks/herald_press_week_01_drafts.md`
- Draft generator: `brain/services/herald_press_outreach.py`
- Weekly cap: 5 pitch drafts
- No autonomous sends, follow-ups, private email scraping, or Graph send calls

Send remains manual and Ken-approved until a dedicated press-send design has
been reviewed with mailbox scope, audit events, retry behavior, and rate caps.
