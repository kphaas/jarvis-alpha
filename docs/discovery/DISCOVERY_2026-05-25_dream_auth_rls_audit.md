# DISCOVERY — Dream Auth + RLS Posture Audit

Date: 2026-05-25
Repo: `jarvis-alpha`
Scope: Dream Mode HTTP routes, Temporal activities, approval gate, and stale
TD-X42 handoff context.

---

## Executive Summary

Dream Mode's May 11 TD-X42 handoff warning is superseded by PR #95
(`fix(dream): TD-X42 elevate RLS role on 6 write handlers`, merged
2026-05-12) plus the later D3.4/D3.5 Dream work. The current route and activity
surface is consistent with the production posture:

- request-scoped human reads use `rls_connection(request)`
- platform-level Dream writes use transaction-scoped
  `set_config('rls.role','platform_admin',true)`
- Temporal activities use `brain.dream._db.activity_db()`
- Dream approval queue insertion uses a SECURITY DEFINER helper with internal
  `set_config('rls.role','platform_admin',true)`

No immediate TD-X42 code fix remains open in `brain/routes/dream.py`.

---

## Four-Lens Review

| Lens | Read |
|---|---|
| CIO | Current Dream write posture is acceptable for bounded production hardening: route auth gates access, RLS elevation is explicit, and halt flags now block execution entry points. |
| Enterprise Architecture | The system still has two caller patterns: `rls_connection(request)` for request-scoped reads and raw pool + platform-admin GUC for platform Dream writes. This is coherent but should become typed RLSContext when the design questions are answered. |
| AI Solo Developer | The explicit pattern is easy to reason about today and avoids hidden magic while Dream is still evolving. The risk is copy/paste drift in new routes. |
| Code Production | Tests now cover halt rejection on workflow start, read-only execution, and execution-step transitions. CI now runs real pytest after PR #131. |

---

## Current Auth Contract

| Surface | Requirement |
|---|---|
| Create/list/get/start/session health/read-only/gated/briefing | `dream.execute` or admin user |
| Kill | `dream.execute` plus `dream.kill`, or admin user |
| Step update | `dream.execute` or admin user |

Admin user bypass is implemented in `brain/middleware/scopes.py`. Service tokens
must carry the relevant scopes.

---

## Current RLS Contract

| Caller | Pattern | Status |
|---|---|---|
| `list_sessions` / `get_session` | `rls_connection(request)` | PASS |
| `create_session` | raw pool, transaction, `rls.role = platform_admin` | PASS |
| `dream_health` | raw pool, transaction, `rls.role = platform_admin` | PASS |
| `start_session` | raw pool, transaction, `rls.role = platform_admin` | PASS |
| `kill_session` | raw pool, transaction, `rls.role = platform_admin` | PASS |
| `get_next_step` | raw pool, transaction, `rls.role = platform_admin` | PASS |
| `execute_readonly_session` | raw pool, transaction, `rls.role = platform_admin` | PASS |
| `execute_gated_session` | raw pool, transaction, `rls.role = platform_admin` | PASS |
| `get_dream_session_briefing` / `publish_dream_session_briefing` | raw pool, transaction, `rls.role = platform_admin` | PASS |
| `update_step` | raw pool, transaction, `rls.role = platform_admin` | PASS |
| `complete_session` | raw pool, transaction, `rls.role = platform_admin` | PASS |
| Temporal activities | `activity_db(user_id, role)` sets `rls.user_id` + `rls.role` | PASS |
| Dream approval gate | `enqueue_dream_step_approval_request` SECDEF sets `rls.role` internally | PASS |

---

## Halt-Gate Hardening Added In This Pass

Before this pass, `execute-gated` checked halt flags but `start`, the read-only
execution slice, and legacy direct step execution transitions did not.

Now these execution entry points reject with `409 dream_halt_flag_active` when
any Dream halt flag is active:

- `POST /v1/dream/sessions/{id}/start`
- `POST /v1/dream/sessions/{id}/execute-readonly`
- `POST /v1/dream/sessions/{id}/execute-gated`
- `PATCH /v1/dream/steps/{id}` when target status is `running` or `completed`

`GET /v1/dream/health` now includes `active_halt_flags` and reports `degraded`
while a halt flag is active.

---

## Remaining Architecture Decision

RLSContext remains valuable, but it should not be rushed into the Dream code
without preserving the current distinction:

- request-scoped reads: identity comes from JWT and should use
  `rls_connection(request)`
- platform-level Dream execution writes: identity is the service operation and
  must bind a platform execution context

Recommended next RLSContext shape for Dream:

1. Keep `rls_connection(request)` for request/user reads.
2. Add a typed platform helper such as `platform_admin_connection(source,
   audit_actor)` or the RLSContext dataclass from `jarvis-standards`.
3. Migrate raw `pool.acquire()` + inline `set_config` Dream blocks to that helper
   one route group at a time.
4. Add a linter or focused test that fails new Dream route write callsites that
   touch FORCE-RLS tables without either `rls_connection` or the platform helper.

---

## Disposition

- TD-X42 as described in the 2026-05-11 handoff is resolved for the current
  `brain/routes/dream.py` write surface.
- No new emergency issue is required.
- Follow-up should be tracked under the broader RLSContext implementation, not
  as a Dream-specific hotfix.
