# Herald Social Gap Memory

Updated: 2026-06-27

## Purpose

This is the working memory for Herald's social-media expansion. Keep it short,
current, and check-off-able. Mark a gap complete only when the repo has shipped
code, tests or smoke coverage, and a runbook/update that proves the behavior.

## Gap Tracker

| ID | Gap | State | Complete When |
|---|---|---|---|
| HSG-001 | Unified interaction ledger across email and social | Open | Email messages, social mentions, drafts, approvals, sends, and failures share one typed interaction model or adapter contract, with append-only outbound audit. |
| HSG-002 | Social connector layer | Partial | At least one approved connector path exists for read + draft/schedule/publish handoff, with token scope docs, health check, and policy limits. Prefer Postiz/Buffer before direct browser automation. |
| HSG-003 | Social approval outbox | Done | Herald can create platform-specific social drafts, queue them for approve/reject, preserve versions, and block every outbound action until explicit approval. |
| HSG-004 | Social inbox UI | Partial | `/herald` separates email from social channels and lets Ken triage account/platform streams without autonomous replies, likes, follows, or DMs. |
| HSG-005 | Analytics feedback loop | Open | Herald stores per-account/per-post metric snapshots, shows trend context, and emits a weekly digest that feeds future drafting recommendations. |
| HSG-006 | Brand and voice memory per platform | Done | AT0 Spark has platform-specific voice rules, audience notes, safety lint, and repeat-post prevention that are visible in the draft workflow. |

## Council 4-Lens Review

| Lens | Read | Recommendation |
|---|---|---|
| CIO | The mail slice is production-grade, but social is still spec-only. Building connectors first would create integration risk before the workflow exists. | Start with HSG-003 and HSG-006 as a draft-only cockpit, then add HSG-002 for approved scheduling/publishing. |
| Cyber | Social APIs and unofficial automation can create account bans, token leakage, and accidental public sends. Herald's strongest asset is its approval/audit posture. | Preserve draft-first, least-privilege tokens, no autonomous engagement, rate caps, and monitor every connector like Graph send health. |
| EA | Ken needs a simple operating surface, not another social tool to babysit. The UI should answer: what arrived, what should I say, what is waiting for approval, what shipped. | Split Herald into Email, Social Inbox, Drafts, Scheduled, and Analytics views as the product grows. |
| Jobs | The real job is relationship-aware communication at lower effort, not raw follower growth. Herald should help keep the AT-0 voice consistent and make approval quick. | Optimize for high-trust drafting, timely replies, reusable campaign memory, and a clean weekly decision loop. |

## Next Recommended Slice

Connect the approved publishing path only after LinkedIn weekly cadence and
manual receipt workflow are deployed and smoke-tested:

1. Keep Postiz/Buffer behind an explicit connector layer.
2. Require a fresh approval before any platform publish.
3. Add connector health, token-scope docs, and rate caps before enabling send.
4. Confirm LinkedIn API product access before implementing direct post/read.

## Completion Log

| Date | Gap | Evidence |
|---|---|---|
| 2026-06-26 | HSG-003 | Added `alpha_herald_social_draft_requests`, `alpha_herald_social_draft_variants`, append-only `alpha_herald_social_draft_events`, `/v1/herald/social/drafts`, approve/reject/archive, Herald UI outbox, and `scripts/smoke_herald_social_outbox.sh`. |
| 2026-06-26 | HSG-006 | Added per-platform social voice profiles for X and LinkedIn, profile snapshots on each draft, safety flags, voice score, repeat detection, and visible rules in `/herald`. |
| 2026-06-27 | HSG-002 | Partial: added LinkedIn weekly draft endpoint, approved-draft schedule date, manual publish receipt URL, cadence readout, route classification, and smoke coverage. No LinkedIn API connector yet. |
| 2026-06-27 | HSG-004 | Partial: added `/herald` LinkedIn engagement reply drafting from operator-provided source/context. No autonomous social inbox read/like/reply/DM actions. |
| 2026-06-27 | HSG-002 | Partial: added approved LinkedIn publish connector through Gateway, Spark-informed draft audit hashes, and `docs/runbooks/herald_linkedin_connector.md`. Still missing LinkedIn read/engagement ingestion and connector health monitor. |
| 2026-06-27 | HSG-004 | Partial: added `alpha_herald_social_engagement_items`, `/v1/herald/social/linkedin/engagements`, `/draft-reply`, `/read-plan`, Herald needs-reply queue UI, and smoke coverage. Automated LinkedIn discovery still waits on approved `r_member_social_feed`. |
| 2026-06-27 | HSG-004 | Partial: added disabled-by-default LinkedIn comment ingestion and approval-gated reply comment publishing through Gateway. Chrome verified `Community Management API` cannot be requested on the current app because LinkedIn requires a separate app for that product. |
| 2026-06-27 | HSG-002 | Partial: added Brain LaunchAgent `com.jarvis.alpha.herald-linkedin-weekly-draft` for automatic weekly LinkedIn draft creation. It creates review-only Spark drafts and never publishes. |
| 2026-06-28 | HSG-004 | Partial: added Brain LaunchAgent `com.jarvis.alpha.herald-linkedin-engagement-scheduler` to draft up to 3 LinkedIn replies per week from existing `needs_reply` items. It does not discover posts or publish comments. |
| 2026-06-28 | HSG-004 | Partial: added `com.jarvis.alpha.herald-linkedin-target-scout` and `/v1/herald/social/linkedin/engagements/scout` so Herald can discover public AI/business-transformation targets through Gateway Internet Scout and queue them for review. No logged-in scraping or autonomous comment/publish. |
