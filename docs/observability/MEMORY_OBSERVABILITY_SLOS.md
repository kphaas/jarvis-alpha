# Memory Observability SLOs

Status: production monitor v1
Owner: Ken
Runner: `com.jarvis.alpha.memory-observability` on Brain every 15 minutes

## Scope

This monitor covers explicit semantic memory saves, high-visibility review
lanes, Dream proposal execution health, and Buddy event alert delivery. It
uses aggregate counts only; raw memory facts, Dream evidence, and user text
must never be logged or sent in alerts.

## Alert Contract

| SLO | Default | Severity |
|---|---:|---|
| Pending semantic review backlog | `<= 10` | fail |
| New review-required saves in 24h | `<= 5` | fail |
| Stale Dream reviewed writes older than 48h | `0` | fail |
| Dream approval queue mismatches | `0` | fail |
| Executed Dream proposals missing ledger rows | `0` | fail |
| High-priority memory Buddy events in 7d | `<= 10` | warn |
| Approved Dream writes waiting execution | `<= 100` | warn |

Overrides live in `~/jarvis/.secrets`:

```bash
MEMORY_OBS_MAX_PENDING_REVIEW=10
MEMORY_OBS_MAX_REVIEW_REQUIRED_24H=5
MEMORY_OBS_MAX_STALE_DREAM_REVIEWED_WRITES=0
MEMORY_OBS_MAX_DREAM_APPROVAL_MISMATCH_COUNT=0
MEMORY_OBS_MAX_DREAM_EXECUTED_WITHOUT_LEDGER=0
MEMORY_OBS_MAX_HIGH_PRIORITY_UNREAD=10
MEMORY_OBS_MAX_DREAM_APPROVED_WAITING_EXECUTION=100
MEMORY_OBS_ALERT_SUPPRESSION_HOURS=6
```

## Runbook

Manual dry run on Brain:

```bash
cd ~/jarvis-alpha
.venv/bin/python scripts/check_memory_observability.py --dry-run
```

Expected output is one JSON object with `status`, `metrics`, and
`violations`. `status=pass` exits 0, `status=warn` exits 0 after optionally
posting a suggestion event, and `status=fail` exits 2 after posting an alert
event unless a duplicate fingerprint was posted within the suppression window.

## Deploy Behavior

`jarvisalpha_pull.sh` installs/restarts this LaunchAgent when the monitor
script, plist template, or LaunchAgent installer changes. The remote pull path
also refuses to deploy from non-`main` branches unless
`JARVIS_ALPHA_ALLOW_BRANCH_DEPLOY=1` is explicitly set.
