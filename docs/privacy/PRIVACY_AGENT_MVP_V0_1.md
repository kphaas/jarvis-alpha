# Privacy Agent MVP v0.1

Date: 2026-06-06
Status: Review-ready

## Definition

Privacy Agent MVP v0.1 is complete when a human operator can move one
synthetic privacy request through this full local workflow:

```text
subject intake
  -> target selection
  -> review packet draft
  -> approval handoff
  -> approved action queue
  -> manual disposition
  -> manual verification
  -> timeline and report
```

## Included

- Encrypted subject intake with identity tuple digests.
- Local target registry and selection UI.
- Review packet draft creation.
- Draft Review Inbox.
- Approval handoff through Alpha approvals.
- Approved action queue.
- Manual disposition and verification.
- Case timeline and local report metadata.
- Operator runbook and release marker.

## Not Included

- Public-internet scanning.
- Data broker form submission.
- Email/SMS sending.
- Court filing or court-record automation.
- Evidence upload.
- Scheduled runners.
- Action executors.

## Evidence

Chrome smoke on 2026-06-06 completed a synthetic `BeenVerified` case:

- Case: `b43d72a0-f706-4b57-8149-724fdff424db`
- Action: `5413e1e4-c747-4311-b76e-02de0d2c38d4`
- Final status: `confirmed`
- Timeline: `1 actions / 5 events`
- Report: generated after verification
- Brain logs: route responses were `200`; no sampled server errors

## Known Follow-Ups

- Auto-select or deep-link the matching case/action when `/privacy?case=...`
  is opened from Approvals.
- Filter or group completed actions so the operator queue focuses on work that
  still needs attention.
- Decide whether case draft status should move from `submitted_for_approval`
  to a terminal local workflow status after all actions are confirmed.
- Design a separately approved executor phase before any public-internet action.
