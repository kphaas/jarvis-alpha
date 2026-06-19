# Herald Social Gap Memory

Updated: 2026-06-19

## Purpose

This is the working memory for Herald's social-media expansion. Keep it short,
current, and check-off-able. Mark a gap complete only when the repo has shipped
code, tests or smoke coverage, and a runbook/update that proves the behavior.

## Gap Tracker

| ID | Gap | State | Complete When |
|---|---|---|---|
| HSG-001 | Unified interaction ledger across email and social | Open | Email messages, social mentions, drafts, approvals, sends, and failures share one typed interaction model or adapter contract, with append-only outbound audit. |
| HSG-002 | Social connector layer | Open | At least one approved connector path exists for read + draft/schedule/publish handoff, with token scope docs, health check, and policy limits. Prefer Postiz/Buffer before direct browser automation. |
| HSG-003 | Social approval outbox | Open | Herald can create platform-specific social drafts, queue them for approve/reject, preserve versions, and block every outbound action until explicit approval. |
| HSG-004 | Social inbox UI | Open | `/herald` separates email from social channels and lets Ken triage account/platform streams without autonomous replies, likes, follows, or DMs. |
| HSG-005 | Analytics feedback loop | Open | Herald stores per-account/per-post metric snapshots, shows trend context, and emits a weekly digest that feeds future drafting recommendations. |
| HSG-006 | Brand and voice memory per platform | Open | AT-0 Spark has platform-specific voice rules, audience notes, safety lint, and repeat-post prevention that are visible in the draft workflow. |

## Council 4-Lens Review

| Lens | Read | Recommendation |
|---|---|---|
| CIO | The mail slice is production-grade, but social is still spec-only. Building connectors first would create integration risk before the workflow exists. | Start with HSG-003 and HSG-006 as a draft-only cockpit, then add HSG-002 for approved scheduling/publishing. |
| Cyber | Social APIs and unofficial automation can create account bans, token leakage, and accidental public sends. Herald's strongest asset is its approval/audit posture. | Preserve draft-first, least-privilege tokens, no autonomous engagement, rate caps, and monitor every connector like Graph send health. |
| EA | Ken needs a simple operating surface, not another social tool to babysit. The UI should answer: what arrived, what should I say, what is waiting for approval, what shipped. | Split Herald into Email, Social Inbox, Drafts, Scheduled, and Analytics views as the product grows. |
| Jobs | The real job is relationship-aware communication at lower effort, not raw follower growth. Herald should help keep the AT-0 voice consistent and make approval quick. | Optimize for high-trust drafting, timely replies, reusable campaign memory, and a clean weekly decision loop. |

## Next Recommended Slice

Build a draft-only social cockpit:

1. Store social draft requests, variants, review state, and append-only events.
2. Generate per-platform drafts using AT-0 Spark voice memory.
3. Add `/herald` UI sections for Social Drafts and platform/account filters.
4. Add approve/reject/archive controls, but no publishing connector yet.
5. Add a smoke script that proves drafts can be created, reviewed, and audited.

## Completion Log

| Date | Gap | Evidence |
|---|---|---|
| TBD | TBD | TBD |
