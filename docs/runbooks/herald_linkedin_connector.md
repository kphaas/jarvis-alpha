# Herald LinkedIn Connector

## Required LinkedIn Setup

- LinkedIn developer app with member posting access.
- OAuth token for Ken with `w_member_social`.
- Optional future read access requires `r_member_social`; this PR does not read LinkedIn.
- Reference: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?view=li-lms-2026-06

## Alpha Secrets

Set on Brain, never in code:

```bash
AT0_LINKEDIN_ACCESS_TOKEN=...
AT0_LINKEDIN_AUTHOR_URN=urn:li:person:...
AT0_LINKEDIN_API_VERSION=202606
```

`202606` is the current default for this connector. Do not fall back to `202506`;
LinkedIn has marked that Marketing API version sunset.

## Flow

1. Herald creates a Spark-informed LinkedIn draft.
2. Ken approves the draft in `/herald`.
3. `POST /v1/herald/social/drafts/{variant_id}/publish/linkedin` sends through Gateway to LinkedIn.
4. Herald records append-only start/success/failure events and marks the draft `linkedin_published` or `publish_failed`.

## Boundary

- No autonomous posting.
- No LinkedIn read/comment/like/DM path.
- No token values in audit events, logs, UI, or test fixtures.
