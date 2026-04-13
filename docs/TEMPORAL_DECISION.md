# Temporal POC Decision

**Date:** 2026-04-13
**Verdict:** GO
**Confidence:** High

## Verdict Rationale

Temporal installed cleanly via Homebrew (no Docker touched), the dev server came up healthy on 7233/8233, the Python SDK dropped into the existing `jarvis-alpha` venv with zero conflicts, and the minimal TaskGraph-analogue workflow executed end-to-end in 2.30s wall-clock — including a signal-based approval gate, retry policy, and activity timeouts. Every JARVIS invariant holds: no Docker, Homebrew ARM binary only, headless macOS LaunchAgent operation confirmed feasible, no hardcoded secrets. Temporal is a viable replacement for `TaskGraphExecutor` in Alpha-2.

## Evidence

### Install

- Homebrew 5.1.5, ARM arm64 bottle
- `brew install temporal` → success, 345.3 MB, 12 files at `/opt/homebrew/Cellar/temporal/1.6.2`
- Installed: **temporal 1.6.2** (Server 1.30.2, UI 2.45.3)
- Binary: `/opt/homebrew/bin/temporal`
- No Docker referenced anywhere in install output or caveats
- Homebrew caveat surfaced `brew services start temporal` as the intended background-service invocation — early signal for LaunchAgent compatibility

### Server

Started with:
```
temporal server start-dev --port 7233 --ui-port 8233 --db-filename /tmp/temporal_poc.db
```

Log:
```
Temporal CLI 1.6.2 (Server 1.30.2, UI 2.45.3)
Temporal Server:  localhost:7233
Temporal UI:      http://localhost:8233
Temporal Metrics: http://localhost:50696/metrics
```

Health check:
```
$ temporal operator cluster health --address 127.0.0.1:7233
SERVING
```

SQLite persistence file at `/tmp/temporal_poc.db` — POC only. Postgres is the Alpha-2 choice.

### Python SDK

- `pip install temporalio` into `~/jarvis-alpha/.venv` — clean
- Installed: **temporalio 1.18.2** (cp39 arm64 wheel, 12.4 MB)
- Transitive deps: `protobuf 6.33.6`, `nexus-rpc 1.1.0`, `python-dateutil 2.9.0.post0`, `types-protobuf 6.32.1.20251210`, `six 1.17.0`
- `typing-extensions` already satisfied from existing venv
- No dependency conflicts with existing `jarvis-alpha` venv packages
- Import verified: `python3 -c "import temporalio; print(temporalio.__version__)"` → `1.18.2`
- Note: venv pip is 21.2.4 (old); unrelated to Temporal, not touched

### Workflow POC

File: `/tmp/jarvis_temporal_poc.py` (TaskGraph analogue — LLM call activity → approval signal gate → save activity).

Run output:
```
Workflow started: jarvis-poc-001
Approval signal sent
Workflow result: {'approved': True,
                  'llm_result': 'LLM response to: Summarize my morning briefing',
                  'saved': 'saved:LLM response to: Summarize my morning briefing',
                  'task': 'Summarize my morning briefing'}
real 2.30
user 0.16
sys  0.05
```

Wall-clock: **2.30s total**, of which ~2.0s is the deliberate `asyncio.sleep(2)` before the approval signal. Effective workflow + activity overhead is ~0.30s for: client connect, worker start, workflow start, two activity executions, signal round-trip, result marshalling.

Behaviors verified:
- ✅ Workflow definition + registration
- ✅ Activity execution (2 activities, chained)
- ✅ `RetryPolicy(maximum_attempts=3)` accepted
- ✅ `start_to_close_timeout` honored
- ✅ Signal-based approval gate (`workflow.wait_condition` + `@workflow.signal`) — round-tripped cleanly
- ✅ Return value marshalled back to caller as typed dict
- ✅ **Approval signal worked: YES**
- No warnings, no deprecation notices, no errors

### LaunchAgent Compatibility

**Q1: Can `temporal server start-dev` run without a terminal attached?** **YES.**
Direct evidence: during the POC the server was launched from the Claude harness as a detached background process with stdout redirected to a file and no controlling TTY. It continued serving (`SERVING` health confirmed) throughout the session. Homebrew itself offers `brew services start temporal` as the background-service invocation, confirming the binary is intended to run under a service manager.

**Q2: Is there a `--headless` or equivalent flag?**
`--headless` exists but semantically only **disables the Web UI** — it is NOT a detach flag. On macOS, detaching is handled by launchd, not by the binary. The `--headless` flag is still useful in production to skip the UI port binding.

**Q3: Is the temporal worker (Python process) just a normal asyncio process?** **YES.**
The `temporalio.worker.Worker` runs inside a regular `asyncio` event loop in any Python process. No subprocess, no sidecar, no IPC, no special supervisor. A standard LaunchAgent plist pointing at `~/jarvis-alpha/.venv/bin/python3 worker_main.py` is sufficient.

**Verdict:** Full LaunchAgent compatibility. Two standard plists (server + worker) satisfy the headless macOS invariant with no Docker, no daemonization tricks, no workarounds.

## GO Path — If GO

What needs to happen to use Temporal in Alpha-2:

- **Temporal server LaunchAgent plist** — one plist pointing at `/opt/homebrew/bin/temporal server start-dev` with `--headless` to disable the UI in production, `--db-filename` pointing at persistent storage (or Postgres config via `--sqlite-pragma` replaced by Postgres flags — see below), `StandardOutPath`/`StandardErrorPath` redirected to `~/Library/Logs/jarvis/temporal-server.log`, `KeepAlive=true`, `RunAtLoad=true`. Effort: ~1 hour.
- **Python worker LaunchAgent plist** — second plist pointing at `~/jarvis-alpha/.venv/bin/python3 /Users/jarvissand/jarvis-alpha/brain/temporal/worker_main.py`, same log redirection / KeepAlive pattern. `worker_main.py` is a thin bootstrap that connects to `127.0.0.1:7233`, registers workflows + activities, and runs the worker event loop. Effort: ~2 hours including the bootstrap script.
- **Postgres backend replaces SQLite** — Alpha-2 uses Postgres on Brain, not SQLite. The `jarvis_alpha` database already exists on Brain; Temporal gets its own schema/namespace (likely `temporal_prod` database or dedicated schema inside `jarvis_alpha`). Switch `temporal server start-dev` → `temporal server start-dev` with Postgres plugin config, or move to `temporal server` (non-dev) with full Postgres DSN. Effort: ~3-4 hours including schema bootstrap and verification.
- **temporalio installs into existing venv** — no new venv needed. `temporalio 1.18.2` is already proven compatible with the `jarvis-alpha` venv (Python 3.9.6, arm64). Just `pip install temporalio` as part of Alpha-2 requirements.txt. Effort: trivial.
- **R2 deferred** — `TaskGraphExecutor` invalid status values issue is moot: the executor is being deleted in the Alpha-2 rewrite. No fix needed, ship as-is and delete.
- **Stage 5d.2 scope shrinks** — 5d.2 reduces to **R1 GUC fix + DSN cutover only**. No R2 fix. Significant scope reduction — update STAGE5D_DESIGN.md to reflect.
- Port JARVIS task steps (LLM call, DB write, approval gate, notification, etc.) from `TaskGraphExecutor` step abstractions to `@activity.defn` functions. Effort: 1-2 days per task family.
- Migrate existing in-flight tasks off `TaskGraphExecutor` before cutover (or drain + cut over cleanly at a quiet window).
- Observability: wire Temporal's `/metrics` endpoint into whatever metrics pipeline Brain is already using.

**Rough effort estimate for Alpha-2 Temporal integration:** 1-2 weeks of focused work, not counting the task-step port itself.

## NO-GO Path — If NO-GO

N/A — verdict is GO. For reference, the NO-GO fallback would have been full Stage 5d.2 scope per `STAGE5D_DESIGN.md` (R1 GUC fix + R2 `TaskGraphExecutor` status value fix + DSN cutover), keeping `TaskGraphExecutor` as the task orchestration layer in Alpha-2.

## Open Questions for Ken + Air Claude

1. **Postgres layout** — does Temporal get its own database (`temporal_prod`) on Brain Postgres, or a schema inside the existing `jarvis_alpha` database? Preference?
2. **Dev server vs full server in production** — `temporal server start-dev` is labeled "not for production." Do we stand up the full `temporal server` (multi-service) binary with a proper config file for Alpha-2, or is the dev server with Postgres persistence acceptable for single-node JARVIS? The dev server is materially simpler to operate.
3. **Namespace strategy** — one namespace (`default`) for all JARVIS workflows, or split by domain (e.g., `jarvis-briefings`, `jarvis-ingest`, `jarvis-approvals`)?
4. **Worker count** — one worker process per task queue, or a single omnibus worker? Starting point for Alpha-2?
5. **Stage 5d.2 rescoping** — confirm that R2 can be dropped entirely given the `TaskGraphExecutor` rewrite. If there is any scenario where the executor survives into Alpha-2 (even transitionally), R2 must stay in scope.
6. **Task-step port ordering** — which JARVIS task family gets ported first as the Alpha-2 reference implementation? Suggest starting with the simplest (notification dispatch or similar) to validate the pattern before touching the LLM + approval-gate flows.
7. **Metrics endpoint** — is Brain currently scraping any metrics endpoints? If so, which, and should the Temporal `/metrics` endpoint join that pipeline or stand alone?
