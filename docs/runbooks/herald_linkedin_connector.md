# Herald LinkedIn Connector

## Required LinkedIn Setup

- LinkedIn developer app with member posting access.
- OAuth token for Ken with `w_member_social`.
- Optional feed/comment discovery requires LinkedIn-approved
  `r_member_social_feed` and comment publishing requires `w_member_social_feed`.
  Until approved, Herald supports manual LinkedIn engagement inbox items only.
- Chrome check on 2026-06-27: LinkedIn blocked `Community Management API` on
  the current `AT-0Herald` app because that product must be the only product on
  an app. Create a separate LinkedIn app for that product before enabling
  automated engagement ingestion.
- References:
  - https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?view=li-lms-2026-06
  - https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/comments-api?view=li-lms-2026-06
  - https://developer.linkedin.com/product-catalog/marketing/community-management-api

## Alpha Secrets

Set on Brain, never in code:

```bash
AT0_LINKEDIN_ACCESS_TOKEN=...
AT0_LINKEDIN_AUTHOR_URN=urn:li:person:...
AT0_LINKEDIN_API_VERSION=202606
AT0_LINKEDIN_CLIENT_ID=...
AT0_LINKEDIN_CLIENT_SECRET=...
HERALD_LINKEDIN_INGEST_ENABLED=false
```

`202606` is the current default for this connector. Do not fall back to `202506`;
LinkedIn has marked that Marketing API version sunset.

## Token Health Monitor

`com.jarvis.alpha.herald-linkedin-health` runs on Brain every 6 hours. It calls
LinkedIn OAuth token introspection, verifies the token is active, checks
`w_member_social`, and exits non-zero when the token is inactive or inside the
renewal warning window.

Optional knobs:

```bash
AT0_LINKEDIN_REQUIRED_SCOPES=w_member_social
AT0_LINKEDIN_TOKEN_WARN_DAYS=14
AT0_LINKEDIN_HEALTH_FAIL_ON_DEGRADED=true
```

Renewal is still human-in-the-loop OAuth: regenerate the member token before the
warning window closes, then restart Alpha.

## Flow

1. Herald creates a Spark-informed LinkedIn draft.
2. Ken approves the draft in `/herald`.
3. `POST /v1/herald/social/drafts/{variant_id}/publish/linkedin` sends through Gateway to LinkedIn.
4. Herald records append-only start/success/failure events and marks the draft `linkedin_published` or `publish_failed`.

## Weekly Draft Automation

- `com.jarvis.alpha.herald-linkedin-weekly-draft` runs daily on Brain.
- It creates at most one active `linkedin-weekly-brand` draft, then stops until
  that draft is approved/published, archived, or rejected.
- It does not publish. It only creates a `needs_review` LinkedIn draft using
  Spark voice context and the weekly AT0/enterprise AI topic rotation.
- Cadence treats both manual receipts and direct LinkedIn publishes as the last
  published date.

## Engagement Inbox

- `GET /v1/herald/social/linkedin/read-plan` reports the read-access plan:
  `w_member_social` can publish approved top-level posts, but feed/comment
  discovery needs `r_member_social_feed`.
- `com.jarvis.alpha.herald-linkedin-target-scout` runs daily on Brain and uses
  Gateway Internet Scout public search to queue target candidates into the
  LinkedIn engagement inbox. It does not use Chrome, cookies, logged-in
  scraping, likes, follows, DMs, comments, or publish APIs.
- `POST /v1/herald/social/linkedin/engagements/scout` runs the same scout on
  demand from `/herald`, optionally with operator-supplied topics.
- `com.jarvis.alpha.herald-linkedin-engagement-scheduler` runs daily on Brain
  and creates up to 3 LinkedIn reply drafts per week from existing `needs_reply`
  engagement items.
- `POST /v1/herald/social/linkedin/engagements` creates a local `needs_reply`
  item from a public LinkedIn URL/comment Ken provides.
- `POST /v1/herald/social/linkedin/engagements/{item_id}/draft-reply` creates a
  Spark-informed LinkedIn reply draft and links it back to the engagement item.
- The generated reply lands in the normal social approval outbox. It cannot be
  posted until Ken approves the draft and then calls the publish route.
- `POST /v1/herald/social/linkedin/ingest` reads comments for a supplied
  LinkedIn post URN only when `HERALD_LINKEDIN_INGEST_ENABLED=true`.
- `POST /v1/herald/social/linkedin/engagements/{item_id}/publish-reply` posts an
  approved reply draft as a LinkedIn comment, then audits success/failure and
  marks the engagement `replied`.

## Boundary

- No autonomous posting.
- No automatic publish from the weekly scheduler.
- No automated LinkedIn read/like/DM path until LinkedIn approves the separate
  Community Management app.
- No scheduled ingestion loop; comment ingestion is manual and disabled by
  default.
- No scheduled comment publish. The scheduler only drafts replies for review.
- Target scouting uses public search results only and queues candidates for
  review; it does not guarantee every result is commentable on LinkedIn.
- No token values in audit events, logs, UI, or test fixtures.
