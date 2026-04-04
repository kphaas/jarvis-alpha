# Approval Gateway Spec — jarvis-alpha

Design Spec · April 2026 · Status: REVIEWED (Perplexity pass incorporated)

---

## 1. Summary

Every action in JARVIS is classified by risk tier. Low-risk actions execute immediately. High-risk actions require explicit human approval before execution. The system cannot bypass this — enforcement is at the Brain API layer, not the application layer.

**Core rule:** The system can never do more damage than its current approval level allows.

---

## 2. Design Principles

1. **Deny by default.** Unclassified actions are treated as highest risk tier (T5).
2. **Approval is infrastructure, not a feature.** Every route passes through the gateway — no ad-hoc paths.
3. **Immutable audit.** Every action gets a permanent record. If audit INSERT fails → block execution.
4. **Replay protection.** Each approval is single-use with a nonce. Replaying returns 409 Conflict.
5. **Overnight is stricter, not looser.** Lower human visibility = tighter constraints.
6. **Approvers are adults only.** Child profiles cannot approve any action.
7. **Auth before classification.** Never classify an unauthenticated request.

---

## 3. Action Classes

Every API action is tagged with one or more classes:

| Class | Description | Examples |
|---|---|---|
| `read` | No side effects, returns data only | GET /health, GET /v1/mesh/status |
| `write` | Modifies JARVIS-internal data | Memory writes, task state changes |
| `external_call` | Outbound network call (cloud API, UDM Pro) | Claude/Perplexity/Gemini calls, UniFi API |
| `cost_incurring` | Spends money (cloud tokens, API credits) | Any cloud LLM call via Gateway |
| `child_facing` | Content that will be seen or heard by a child | TTS responses to child profiles, child UI |
| `deploy` | Changes running code or config on a node | Forge deploy, config push, service restart |
| `admin` | System config, security settings, user management | Key rotation, scope changes, profile creation |
| `destructive` | Deletes data, revokes access, drops resources | Memory purge, token revocation, table drop |
| `unclassified` | Default for unregistered routes | Any route not in classification registry |

Actions can have multiple classes. Example: overnight deploy calling Claude for review = `deploy` + `external_call` + `cost_incurring`.

---

## 4. Risk Tiers

| Tier | Name | Behavior | Who Decides |
|---|---|---|---|
| T1 | Auto | Execute immediately, minimal log | System |
| T2 | Log | Execute immediately, structured audit log | System |
| T3 | Notify | Execute, push notification to admin after | System + notify |
| T4 | Approve | Pause, require adult approval before execution | Human (Ken or adult) |
| T5 | Confirm | Pause, require admin PIN re-entry before execution | Ken (admin only) |

### Tier Assignment Rules

| Action Classes | → Risk Tier | Rationale |
|---|---|---|
| `read` only | T1 | No side effects |
| `write` to own data | T2 | Internal state change, auditable |
| `external_call` (non-cost) | T2 | UniFi status, health pings |
| `cost_incurring` | T3 | Spends money — notify |
| `child_facing` | T4 | Content to children — always human-approved |
| `deploy` | T4 | Changes running system |
| `external_call` + `cost_incurring` | T3 | Cloud LLM call with budget |
| `admin` | T5 | Security-critical |
| `destructive` | T5 | Irreversible |
| `deploy` + `child_facing` | T5 | Compound risk — highest tier |
| `unclassified` | T5 | Deny by default |

---

## 5. Overnight Mode

### 5.1 Activation

Overnight mode is an explicit Brain config flag, not an assumption:
- `overnight_mode: bool` — toggled by cron job at 22:00–06:00 local time
- Manual override: `POST /v1/admin/overnight/toggle` (T5 — requires PIN)
- Buddy checks this flag before executing any queued work

### 5.2 Tier Behavior

| Tier | Daytime | Overnight |
|---|---|---|
| T1 | Auto | Auto (same) |
| T2 | Log | Log (same) |
| T3 | Execute + notify | Execute only if under nightly budget cap, else queue |
| T4 | Approve | **Queue for morning review — never auto-execute** |
| T5 | PIN confirm | **Queue for morning review — never auto-execute** |

### 5.3 Overnight Budget Cap

| Resource | Nightly Limit | On Exceed |
|---|---|---|
| Cloud API spend | $2.00 | Queue remaining, alert Ken |
| Cloud API calls | 50 requests | Queue remaining, alert Ken |
| File writes | 100 files | Pause agent, alert Ken |
| Deploys | 0 (zero) | Always queued — never overnight |

### 5.4 Pre-Approved Overnight Patterns

Ken can pre-approve specific action patterns for overnight execution:

```json
{
  "pattern": "forge.plan.*",
  "max_tier": "T3",
  "budget_usd": 1.00,
  "expires": "2026-04-05T06:00:00Z"
}
```

Pre-approvals are:
- Time-limited (single night or explicit expiry)
- Scope-limited (specific pattern, max tier T3 — never T4/T5)
- Budget-limited
- **Max 5 active** (non-revoked, non-expired) at a time — enforced at app layer before INSERT
- Can be revoked mid-night without deleting the row (`revoked_at` + `revoked_by`)
- Reviewed in morning briefing

---

## 6. Approval Flow

### 6.1 Request Path

```
Actor → Brain API route
  → Auth (validate JWT + actor_type)       ← MUST run BEFORE classification
  → Approval Gateway middleware
      → Classify action classes
      → Determine risk tier
      → Check overnight restrictions
      → T1/T2: execute + log
      → T3: execute + notify
      → T4: pause → INSERT alpha_approval_queue → Pushover notify → poll
      → T5: pause → INSERT alpha_approval_queue → Pushover notify + PIN → poll
  → Execute route handler
  → INSERT alpha_approval_audit            ← If INSERT fails → BLOCK execution
```

**Key rules:**
- Auth check runs BEFORE classification — never classify an unauthenticated request
- If audit INSERT fails → block execution (availability sacrificed for immutability)
- Concurrent T4/T5 requests for same resource: advisory lock or `UNIQUE(actor_sub, parameters_hash)` where `status = 'pending'`

### 6.2 Approval Notification

When T4/T5 action is paused:
1. Write pending record to `alpha_approval_queue`
2. Push notification via Pushover API (through Gateway)
3. Include: action description, actor, parameters preview, risk tier
4. If Pushover fails: set `notification_sent = false`, background poller retries every 5 min
5. UI shows pending approval in Buddy Events feed

### 6.3 Approval Response

Adult approver (Ken or future adult profile):
1. Views pending action in UI or notification
2. Sees: action class, risk tier, actor, parameter preview (500 chars, secrets stripped), timestamp
3. Actions: **Approve** (T4) or **Approve + PIN** (T5) or **Deny**
4. Approval is signed with approver's JWT
5. Nonce prevents replay — duplicate nonce returns 409 Conflict

### 6.4 PIN Re-Entry (T5)

- PIN sent to Brain endpoint in `POST /v1/approval/{id}/decide` body
- Brain hashes with bcrypt and compares against stored hash in `alpha_admin_config` table
- Never send hash to UI, never store plaintext PIN
- Failed PIN → increment attempt counter, lock after 5 failures for 15 minutes

### 6.5 Timeout

| Tier | Timeout | On Timeout |
|---|---|---|
| T4 | 24 hours | Auto-deny, log, notify |
| T5 | 12 hours | Auto-deny, log, notify |

---

## 7. Forge Pipeline Integration

Forge's pipeline stages map to approval tiers:

| Pipeline Stage | Action Classes | Risk Tier | Behavior |
|---|---|---|---|
| Backlog → Planned | `write` | T2 | Log only |
| Plan (local Ollama) | `write` | T2 | Log only |
| Plan (cloud Claude) | `write` + `external_call` + `cost_incurring` | T3 | Execute + notify |
| Build (Cursor prompt gen) | `write` | T2 | Log only |
| Review (cloud Claude) | `external_call` + `cost_incurring` | T3 | Execute + notify |
| Deploy | `deploy` | T4 | **Require approval** |
| Deploy with child-facing | `deploy` + `child_facing` | T5 | **Require PIN** |
| Overnight planning batch | `write` + `cost_incurring` | T3 | Budget-capped |
| Overnight deploy | `deploy` | T4 | **Queued for morning** |

### Forge → Brain Approval API

When Forge reaches a T4+ action:

```
POST /v1/approval/request
Authorization: Bearer <forge_service_token>
{
  "action_class": ["deploy"],
  "actor_sub": "forge",
  "actor_type": "service",
  "description": "Deploy F-064: Brain routes /v1/forge/lessons",
  "parameters": { "feature_id": "F-064", "target_node": "brain" },
  "nonce": "a1b2c3d4e5f6"
}
```

Brain returns:
- `202 Accepted` — queued, includes `approval_id`
- `409 Conflict` — duplicate nonce (idempotency)
- Forge polls `GET /v1/approval/{approval_id}/status` every 10s, max 30 min before local timeout

---

## 8. Database Schema

### 8.1 alpha_approval_queue (Brain Postgres)

```sql
CREATE TABLE alpha_approval_queue (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action_class       TEXT[] NOT NULL,
    risk_tier          TEXT NOT NULL CHECK (risk_tier IN ('T1','T2','T3','T4','T5')),
    actor_sub          TEXT NOT NULL,
    actor_type         TEXT NOT NULL CHECK (actor_type IN ('user','service','agent')),
    actor_node         TEXT,
    description        TEXT NOT NULL,
    parameters_hash    TEXT NOT NULL,
    parameters_preview TEXT,
    nonce              TEXT NOT NULL UNIQUE,
    notification_sent  BOOLEAN NOT NULL DEFAULT false,
    status             TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','denied','expired','executed')),
    requested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_by         TEXT,
    decided_at         TIMESTAMPTZ,
    executed_at        TIMESTAMPTZ,
    expires_at         TIMESTAMPTZ NOT NULL,
    overnight          BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX idx_approval_status ON alpha_approval_queue(status);
CREATE INDEX idx_approval_actor ON alpha_approval_queue(actor_sub);
```

**`parameters_hash`:** SHA-256 of raw JSON parameters string.
**`parameters_preview`:** First 500 chars of parameters with secrets stripped — for human review.
**`notification_sent`:** Tracks Pushover delivery — background poller retries where `false`.

### 8.2 alpha_approval_audit (Brain Postgres — immutable)

```sql
CREATE TABLE alpha_approval_audit (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_id     UUID REFERENCES alpha_approval_queue(id),
    action_class    TEXT[] NOT NULL,
    risk_tier       TEXT NOT NULL,
    actor_sub       TEXT NOT NULL,
    actor_type      TEXT NOT NULL,
    description     TEXT NOT NULL,
    parameters_hash TEXT NOT NULL,
    nonce           TEXT NOT NULL,
    decision        TEXT NOT NULL CHECK (decision IN ('approved','denied','expired','auto')),
    decided_by      TEXT,
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    overnight       BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX idx_audit_approval_id ON alpha_approval_audit(approval_id);
CREATE INDEX idx_audit_decided_at ON alpha_approval_audit(decided_at);

REVOKE DELETE, UPDATE ON alpha_approval_audit FROM jarvis_alpha_app;
```

**Immutability:** App role can INSERT but never UPDATE or DELETE. Belt + suspenders with RLS.

### 8.3 alpha_overnight_approvals (Brain Postgres)

```sql
CREATE TABLE alpha_overnight_approvals (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern     TEXT NOT NULL,
    max_tier    TEXT NOT NULL CHECK (max_tier IN ('T1','T2','T3')),
    budget_usd  NUMERIC(10,2),
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    revoked_by  TEXT
);
```

**Max 5 active (non-revoked, non-expired) at a time.** Enforced at app layer before INSERT.

---

## 9. Route Classification Registry

**Implemented as a prefix-match function, not a plain dict** (wildcards don't work in Python dict keys):

```python
ROUTE_CLASSIFICATION = {
    "GET /health":                   ["read"],
    "GET /v1/mesh/status":           ["read"],
    "GET /v1/home/summary":          ["read"],
    "POST /v1/ask":                  ["write", "external_call", "cost_incurring"],
    "POST /v1/cloud/call":           ["external_call", "cost_incurring"],
    "POST /v1/tasks/ingest":         ["write"],
    "POST /v1/forge/lessons":        ["write"],
    "POST /v1/approval/request":     ["write"],
    "GET /v1/approval/{id}/status":  ["read"],
    "POST /v1/approval/{id}/decide": ["admin"],
    "POST /v1/admin/overnight/toggle": ["admin"],
    "DELETE /v1/memory/*":           ["destructive"],
}
```

Lookup function matches by method + longest prefix. Unregistered routes → `["unclassified"]` → T5.

---

## 10. Approval API Routes

```
POST /v1/approval/request
  Auth: Bearer token (any actor)
  Body: { action_class, actor_sub, actor_type, description, parameters, nonce }
  Returns: 202 Accepted + { approval_id }
  Returns: 409 Conflict on duplicate nonce

GET /v1/approval/{id}/status
  Auth: Bearer token (same actor_sub or admin)
  Returns: { status, decided_by, decided_at } or pending
  Forge poll: 10s interval, 30 min max

POST /v1/approval/{id}/decide
  Auth: Bearer token (admin or adult with user.approve scope)
  Body: { "decision": "approve"|"deny", "pin": "<plaintext>" }  (pin required for T5 only)
  Returns: 200 + updated status
```

---

## 11. Migration Path

| Step | What | Effort |
|---|---|---|
| 1 | Create `alpha_approval_queue` + `alpha_approval_audit` + `alpha_overnight_approvals` tables | 20 min |
| 2 | Write route classification registry as prefix-match function | 30 min |
| 3 | Write approval gateway middleware (auth-first, then classify) | 1 hour |
| 4 | Wire T1-T3 flow (auto/log/notify — non-blocking) | 30 min |
| 5 | Wire T4-T5 flow (pause + queue + poll) | 1 hour |
| 6 | Write approval API routes (request, status, decide) | 30 min |
| 7 | Write approval UI component (pending list + approve/deny + PIN) | 1 hour |
| 8 | Update Forge pipeline to call approval API before deploy | 30 min |
| 9 | Wire overnight mode config flag + cron toggle + budget cap | 30 min |
| 10 | Add Pushover notification on T4/T5 + retry poller (5 min interval) | 30 min |
| 11 | REVOKE DELETE, UPDATE on audit table | 5 min |
| 12 | Test: Forge deploy without approval → blocked | 10 min |
| 13 | Test: overnight T4 → queued not executed | 10 min |
| 14 | Test: duplicate nonce → 409 Conflict | 5 min |
| 15 | Test: audit INSERT failure → execution blocked | 10 min |
| **Total** | | **~7.5 hours** |

---

## 12. Failure Modes

| Failure | Impact | Mitigation |
|---|---|---|
| Brain down, approval pending | Action stays queued | Forge queues locally, retries when Brain returns |
| Approver timeout | Action denied | Auto-deny at T4=24hr, T5=12hr + notification |
| Audit INSERT fails | **Execution blocked** | Availability sacrificed for immutability |
| Nonce collision | 409 returned | Caller retries with new nonce |
| Overnight budget exceeded | Remaining queued | Morning briefing shows spend + queue |
| Pushover down | notification_sent=false | Background poller retries every 5 min |
| Concurrent duplicate requests | Race condition | Advisory lock or UNIQUE(actor_sub, parameters_hash) where pending |
| PIN brute force | Account lockout | 5 failed attempts → 15 min lockout |

---

## 13. What This Does NOT Cover

- **Notification mechanism details** — Pushover selected. Fallback to email TBD.
- **UI wireframes** — approval component designed separately.
- **Dynamic risk reclassification** — tiers static per route. Future: ML scoring.
- **Multi-approver T5** — single approver sufficient for household.

---

*Approval Gateway Spec V2 · jarvis-alpha · April 2026 · Perplexity review incorporated*
