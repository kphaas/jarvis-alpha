# Discovery — Small P1/P2 Ops Debt Closure

Date: 2026-05-25  
Repo: `jarvis-alpha`  
Branch: `claude-code/ops-debt-cleanup-before-agents`

## Decision Frame

This pass used the four-lens review Ken requested:

| Lens | Choice |
|---|---|
| CIO | Close low-risk operational drag before agent-management work; park feature-sized items instead of muddying scope. |
| Enterprise Architect | Prefer repo-owned config, deterministic deploy behavior, and CI guardrails over machine-local tribal knowledge. |
| AI Solo Developer | Make pull/deploy scripts recover from common Sandbox drift without needing manual babysitting. |
| Code Production | Keep runtime changes narrowly scoped, testable, and deploy-gated by existing fan-out checks. |

## Closed Or Dispositioned

| Item | Prior State | Disposition |
|---|---|---|
| TD-94 watchdog `-15` | Brain watchdog was healthy, but old logs showed traceback noise during normal launchctl stop/restart. | Fixed watchdog SIGTERM/SIGINT handling so shutdown logs cleanly instead of raising `KeyboardInterrupt`/`CancelledError` tracebacks. Deploy now restarts watchdog when its code changes. |
| Audit trigger backfill note | Architecture doc listed “6 of 10 expected audit triggers” as P1. | Dispositioned stale. Current prod trigger inventory showed four active triggers, and no repo source of truth defines a 10-trigger target. Removed from next-priority list rather than inventing triggers. |
| TD-117 / alpha #56 | Fan-out could continue after Sandbox pull failure. | Fixed: `scripts/jarvisalpha_deploy.sh` now gates Endpoint SCP and runtime-node fan-out behind a clean Sandbox step. |
| TD-118 / alpha #57 | Sandbox auto-pull failed on untracked-file collision. | Fixed with `scripts/sandbox_safe_pull.sh`: refuses tracked/staged changes, removes only byte-identical untracked files that now exist in `origin/main`, and fails closed on divergent collisions. |
| TD-119 / alpha #58 | Sandbox `jarvisalpha_pull.sh` required `GITHUB_TOKEN` even when an existing clone could use native git auth. | Fixed: missing secrets file now warns; first clone still requires `GITHUB_TOKEN`, existing clones use the current remote/native auth unless a token is available. |
| TD-111 / alpha #51 | Brain Fluent Bit and Loki configs lived only on the host filesystem. | Fixed: config templates now live under `config/observability/brain/`, render node-specific paths/bind addresses during Brain deploy, and restart Fluent Bit/Loki when changed. |
| TD-106 / alpha #49 | No CI guard for duplicate config drift. | Fixed: `scripts/check_duplicate_config_drift.py` scans active `.plist`, `.conf`, `.yaml`, `.yml` files and fails if duplicate basenames diverge; wired into CI and unit-tested. |
| TD-99 / alpha #47 | V2 architecture review needed regeneration. | Already effectively closed before this pass; V2 exists and was updated to remove stale P1 ops items. |

## Parked As Not Small Ops Debt

| Item | Reason |
|---|---|
| AI-1 real UniFi WAN/client wiring | Feature implementation on Gateway, not small operational debt. |
| AI-4 `call_tool_agent` stub | Agent/tool architecture work; better handled during the agent-management track. |
| TD-110 LaunchAgent categorical rename | Maintenance window work because labels must be booted out and bootstrapped across nodes. |
| TD-93 Endpoint passwordless sudo | Requires machine-local sudoers policy, not safe as a repo-only change. |
| TD-X40 staging `schema_migrations` drift | Larger runner/resync design, not a small same-session closure. |

## Verification Plan

- `bash -n scripts/jarvisalpha_pull.sh scripts/jarvisalpha_deploy.sh scripts/sandbox_safe_pull.sh`
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run pytest -q`
- `uv run python scripts/check_no_xtrace_secrets.py`
- `uv run python scripts/check_duplicate_config_drift.py`
- `npm --prefix ui run build`

## Agent-Work Readiness

After this pass, the remaining Alpha P1s are feature-sized rather than operational cleanup:

- AI-1 — real UDM Pro data path
- AI-4 — tool-agent execution path

That makes the next good conversation the agent-management design session: define the Agent Spec, registry, policy gates, observability, and first low-risk agent path before building.
