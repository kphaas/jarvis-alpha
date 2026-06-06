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

## Rollback

This runbook changes no runtime state. Runtime rollback for the MVP remains a
normal Alpha deploy rollback to the previous main commit. The live synthetic
case can remain in the append-only ledger as smoke evidence.
