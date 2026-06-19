# Herald AT-0 Mail Runbook

Updated: 2026-06-18

## Scope

Herald MVP is the AT-0 mail-intake and approved-reply production slice:

- Read approved AT-0 Microsoft Graph mailboxes.
- Classify inbound messages into business-intent buckets.
- Create local AT-0 Spark reply drafts.
- Send only drafts that were explicitly approved in Alpha.
- Record append-only send audit events and Graph/send monitor health.

The social-presence Herald module is specified in `docs/specs/jarvis-herald-spec.md`
but is not implemented as a runtime connector yet.

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

Herald cannot manage social media accounts yet. Current repo state has:

- Product spec: `docs/specs/jarvis-herald-spec.md`
- Marketing/social drafting docs and brand assets
- No deployed social account connector, scheduler, approval queue, or publisher
  route for X, LinkedIn, Instagram, Threads, TikTok, Bluesky, or Mastodon

Recommended next slice: draft-only social cockpit first, then Buffer-backed
approved publishing after account policy, audit, and rollback rules are locked.
