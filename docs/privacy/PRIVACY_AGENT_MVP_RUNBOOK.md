# Privacy Agent MVP Runbook

Date: 2026-06-06
Scope: MVP v0.1 manual privacy workflow
Surface: Alpha `/privacy` and `/approvals`

## Boundary

The MVP is local and manual. It can:

- create encrypted privacy subjects;
- select local target registry entries;
- create review packet case drafts;
- submit case drafts to Alpha approvals;
- approve or deny the draft handoff;
- record manual operator disposition;
- record manual verification;
- show append-only timeline metadata and a local case report.

The MVP must not:

- scrape public websites;
- submit broker opt-out forms;
- send email or SMS;
- upload evidence;
- file court documents;
- run a scheduled privacy runner;
- consume approved privacy actions through an executor.

## Operator Smoke

Use a synthetic subject and one broker target. Do not use real PII for smoke
tests.

1. Open `https://jarvis-endpoint.tail40ed36.ts.net:4100/privacy`.
2. Create an adult synthetic subject with one email identity tuple.
3. Select one target from Target Registry, preferably `BeenVerified`.
4. Create a review packet draft.
5. Select the new draft in Draft Inbox.
6. Submit it for approval.
7. Open `https://jarvis-endpoint.tail40ed36.ts.net:4100/approvals`.
8. Unlock with the operator PIN and approve the privacy draft handoff.
9. Return to `/privacy`.
10. Confirm the action appears in Approved Actions with status `approved`.
11. Record manual disposition with synthetic evidence, for example:
    `smoke://privacy/mvp-v01/disposition/<date>`.
12. Confirm the action moves to `sent` and timeline includes `SENT`.
13. Record verification with synthetic evidence, for example:
    `smoke://privacy/mvp-v01/verification/<date>`.
14. Confirm the action moves to `confirmed`, timeline shows 5 events, and the
    P3-G report regenerates.

## Live Smoke Evidence

2026-06-06 live smoke completed through Chrome against the deployed Alpha UI.

| Item | Value |
|---|---|
| Subject ID | `8244e5f0-54fe-478c-b374-e6215f1b9b8a` |
| Case ID | `b43d72a0-f706-4b57-8149-724fdff424db` |
| Approval Queue ID | `4216ebf6-3ea8-478d-9d8b-114e6528c108` |
| Action ID | `5413e1e4-c747-4311-b76e-02de0d2c38d4` |
| Target | `BeenVerified` |
| Final action status | `confirmed` |
| Timeline | `1 actions / 5 events` |
| Report | Generated at completion |

Brain log checks showed `200` responses for subject create, draft create,
approval submit, approval decide, manual disposition, timeline/report refresh,
and verification. No `ERROR`, `Traceback`, or `500` appeared in the sampled log
window.

## Failure Handling

- If subject creation fails, confirm privacy crypto secrets are present before
  retrying.
- If draft creation is disabled, confirm a subject and at least one target are
  selected.
- If approvals do not show the queue item, refresh `/approvals` and search by
  the case short ID.
- If approval actions fail, confirm the operator PIN unlock is active.
- If disposition or verification fails, inspect Brain logs by action ID and
  leave the case in its current state; do not retry with real target data until
  the cause is known.

## Verification Commands

```bash
ssh jarvisbrain@jarvis-brain.tail40ed36.ts.net \
  "tail -n 500 ~/jarvis-alpha/logs/alpha_brain.log | grep -E 'CASE_OR_ACTION_ID|/v1/privacy|ERROR|Traceback| 500 ' || true"
```

## Automated Smoke

The repo-owned synthetic smoke exercises the same manual MVP workflow without
printing tokens, PINs, or raw identifiers:

```bash
cd ~/jarvis-alpha
.venv/bin/python scripts/smoke_privacy_agent.py
```

It uses a Ken/admin user-style token, creates a synthetic adult subject, selects
one broker target, submits the review packet for approval, unlocks/approves the
handoff, records manual disposition, records verification, and checks the
timeline/report evidence manifest. Set `PRIVACY_SMOKE_APPROVAL_PIN` or provide
`ALPHA_PIN` in `~/jarvis/.secrets` for local runs. Remote live smoke requires an
explicit `PRIVACY_SMOKE_APPROVAL_PIN` matching the active approval PIN accepted
by `/v1/approvals/unlock`; the script exits `2` before any mutable Privacy Agent
calls when required smoke configuration is intentionally unavailable.

To avoid exposing the approval PIN to an automation shell, run operator mode:

```bash
.venv/bin/python scripts/smoke_privacy_agent.py \
  --approval-mode operator \
  --approval-wait-seconds 900
```

Operator mode prints the approval queue ID immediately, waits while the operator
approves that synthetic Privacy Agent handoff in `/approvals`, then continues
with manual disposition, verification, timeline, and report checks.

## P5-A Authorization + Lifecycle

The next Incogni-like control-plane slice is local-only:

- create encrypted signed authorizations with
  `POST /v1/privacy/subjects/{subject_id}/authorizations`;
- list authorization hashes with
  `GET /v1/privacy/subjects/{subject_id}/authorizations`;
- queue an approved action into the local removal ledger with
  `POST /v1/privacy/actions/{action_id}/removal-request`;
- list lifecycle rows with `GET /v1/privacy/removal-requests`;
- move a request through `queued`, `sent`, `acknowledged`, `monitoring`,
  `completed`, `failed`, `escalated`, or `blocked` with
  `POST /v1/privacy/removal-requests/{request_id}/transition`.

Lifecycle transitions store encrypted event payloads and optional encrypted
evidence proof references. They do not send broker forms, emails, API requests,
or browser automation. Broker submission remains blocked until a separate
executor phase is reviewed and approved.

## P5-B Gateway Dry Run

Dry-run executor proof is available only as a Gateway egress no-op:

- `POST /v1/privacy/removal-requests/{request_id}/dry-run` prepares an encrypted
  dry-run envelope for a queued or approved removal request;
- Brain calls only Gateway path `/v1/cloud/privacy/removal/dry-run`;
- Gateway validates `mode=dry_run`, `egress_owner=gateway`,
  `outbound_enabled=false`, `would_send=false`, and an empty `allowed_effects`
  list;
- the response returns hash/status metadata only, including
  `dry_run_payload_hash`, `idempotency_key_digest`, `gateway_status`, and
  `gateway_path`;
- the request remains in its existing lifecycle status. No broker form, browser,
  email, SMS, or public API execution occurs.

Dry-run failures should be treated as executor preflight failures. Do not move a
request to `sent` from a dry run alone.

## P5-C Gateway Live Preflight

One-target live preflight is available for BeenVerified only:

- `POST /v1/privacy/removal-requests/{request_id}/live-preflight` requires a
  queued BeenVerified `web_form` request with an existing P5-B dry-run proof;
- Brain verifies a fresh `alpha_approval_queue` binding before calling Gateway:
  status `approved`, unexpired, and decided within the last 15 minutes;
- Brain calls only Gateway path `/v1/cloud/privacy/removal/live-preflight`;
- Gateway defaults to `live_disabled` unless
  `PRIVACY_EXECUTOR_LIVE_ENABLED=true`;
- when enabled, Gateway performs one fixed GET to
  `https://www.beenverified.com/app/optout/search`;
- Gateway still returns `would_send=false` and blocks browser automation, email,
  SMS, broker form submit, and PII payload submit;
- Alpha records encrypted proof metadata only:
  `live_preflight_payload_hash`, `live_preflight_status`,
  `live_preflight_approval_queue_id`, and `gateway_idempotency_key_digest`.

Live preflight does not move a request to `sent`. It proves the kill switch,
fresh approval binding, and Gateway-owned target reachability before any later
executor PR is allowed to submit a removal request.

## Rollback

This runbook changes no runtime state. Runtime rollback for the MVP remains a
normal Alpha deploy rollback to the previous main commit. The live synthetic
case can remain in the append-only ledger as smoke evidence.

For P5-C, unset `PRIVACY_EXECUTOR_LIVE_ENABLED` or set it to `false` to block
all target HTTP immediately. Schema rollback is
`brain/db/rollbacks/20260618_110000_privacy_gateway_live_preflight_rollback.sql`.
