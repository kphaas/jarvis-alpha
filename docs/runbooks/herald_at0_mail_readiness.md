# Herald AT-0 Mail Readiness

Updated: 2026-06-17

## Scope

Herald v1 is the AT-0 mail-intake production slice:

- Read AT-0 Microsoft Graph inbox metadata and body previews only.
- Classify inbound messages into business-intent buckets.
- Create local reply draft proposals for human review.
- Never send, move, delete, or write mailbox drafts.

The broader social-presence Herald module remains spec-ready but out of v1 scope.

## Runtime

- Brain API routes: `/v1/at0-mail/*`
- Scheduled scanner: `com.jarvis.alpha.at0-mail`
- Start script: `scripts/start_alpha_at0_mail.sh`
- Default cadence: hourly via LaunchAgent `StartInterval=3600`
- Freshness window: `AT0_HERALD_STALE_AFTER_MINUTES`, default 180

## Production Checks

Run the live smoke after deploy:

```bash
bash ~/jarvis-alpha/scripts/smoke_at0_herald_mail.sh
```

The smoke runs one read-only Graph scan and checks:

- `/v1/at0-mail/scan`
- `/v1/at0-mail/health`
- `/v1/at0-mail/dashboard`
- `/v1/at0-mail/messages`
- `/v1/at0-mail/drafts`

The health endpoint should return `status=ok` or `status=running` after a
successful scan. `missing`, `failed`, or `stale` means the scanner needs
operator attention.
