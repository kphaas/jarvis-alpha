# Service Identity Model — jarvis-alpha

Design Spec · April 2026 · Status: REVIEWED (Perplexity pass incorporated)

---

## 1. Summary

Every actor in JARVIS gets a cryptographically distinct identity with scoped permissions. No service reuses the user auth path. Brain validates identity by public key and enforces scopes per route.

**Pattern:** Per-node RS256 keypairs + scoped JWT claims
**Token lifetime:** 7 days (services/agents), 30 days (users)
**Actor types:** `user`, `service`, `agent`

---

## 2. Design Principles

1. **Identity ≠ Authorization.** JWT proves who you are. Scopes limit what you can do.
2. **No shared credentials.** Forge key ≠ Gateway key ≠ user key.
3. **Brain validates, never trusts.** Every request checked against public key + scopes + iss/actor_type pair.
4. **Forge → Brain only.** Forge never calls Gateway directly. Brain decides cloud routing.
5. **Compromise containment.** Stolen Forge token grants Forge scopes only — no lateral movement.
6. **Graceful degradation.** Services hold valid tokens locally. Brain outage doesn't invalidate existing tokens until expiry.
7. **Deny by default.** Undecorated routes require admin (`*`) scope. No route is implicitly public.
8. **No PII in tokens.** Child age stored in Brain DB only, never in JWT claims.

---

## 3. Actor Types

| actor_type | Identity | Key Location | Token Lifetime |
|---|---|---|---|
| `user` | Ken, future adults, child profiles | Brain signs with Brain private key | 30 days |
| `service` | Forge, Gateway | Each node's own private key | 7 days |
| `agent` | Buddy, future overnight agents | Brain private key (runs on Brain) | 7 days |

---

## 4. Keypair Inventory

| Node | Key Purpose | Private Key Location | Public Key on Brain |
|---|---|---|---|
| Brain | Signs user + agent tokens | `~/jarvis/pki/jwt/jwt_private.pem` | `~/jarvis-alpha/brain/pki/jwt_public.pem` (self) |
| Gateway | Signs Gateway service tokens | `~/jarvis/pki/jwt/gateway_private.pem` | `~/jarvis-alpha/brain/pki/gateway_public.pem` |
| Sandbox (Forge) | Signs Forge service tokens | `~/.pki/jwt/forge_private.pem` | `~/jarvis-alpha/brain/pki/forge_public.pem` |

**Note:** Sandbox secrets path is `~/` not `~/jarvis/` — consistent with existing `~/.secrets` convention.

---

## 5. Brain Multi-Key Validation

**DO NOT use a trial-key loop.** Use `iss`-based direct lookup:

```python
# config/keys.py
ISS_TO_KEY_FILE = {
    "jarvis-brain":   "jwt_public",
    "jarvis-forge":   "forge_public",
    "jarvis-gateway": "gateway_public",
}

VALID_ISS_ACTOR_PAIRS = {
    "jarvis-brain":   {"user", "agent"},
    "jarvis-forge":   {"service"},
    "jarvis-gateway": {"service"},
}
```

**Validation flow:**
1. Decode JWT header (no verify) → extract `iss`
2. Look up key via `ISS_TO_KEY_FILE[iss]` → reject if `iss` unknown
3. Verify signature with that key
4. Assert `actor_type` in `VALID_ISS_ACTOR_PAIRS[iss]` → reject if mismatch
5. Key mapping cached in memory at startup (loaded once from `brain/pki/`)

Brain loads all `.pem` files from `brain/pki/` at startup. Adding a new service = drop a public key file + restart Brain.

---

## 6. Token Claims

### 6.1 User Token (admin)

```json
{
  "sub": "ken",
  "actor_type": "user",
  "role": "admin",
  "scopes": ["*"],
  "iss": "jarvis-brain",
  "jti": "<uuid4>",
  "iat": 1743724800,
  "exp": 1746316800
}
```

### 6.2 User Token (adult — future spouse/partner)

```json
{
  "sub": "adult_2",
  "actor_type": "user",
  "role": "adult",
  "scopes": [
    "user.ask", "user.memory.own", "user.home.read",
    "user.mesh.read", "user.costs.read", "user.approve"
  ],
  "iss": "jarvis-brain",
  "jti": "<uuid4>",
  "iat": 1743724800,
  "exp": 1746316800
}
```

### 6.3 User Token (child)

```json
{
  "sub": "ryleigh",
  "actor_type": "user",
  "role": "child",
  "profile_id": "child_ryleigh",
  "scopes": ["child.ask", "child.home.read"],
  "iss": "jarvis-brain",
  "jti": "<uuid4>",
  "iat": 1743724800,
  "exp": 1746316800
}
```

**⚠️ No `age` field.** Age is PII — stored in Brain DB only. Brain looks up child restrictions from DB using `profile_id`.

### 6.4 Service Token (Forge)

```json
{
  "sub": "forge",
  "actor_type": "service",
  "node": "sandbox",
  "scopes": [
    "forge.llm.call",
    "forge.costs.report",
    "forge.tasks.ingest",
    "forge.gaps.submit",
    "forge.lessons.sync",
    "forge.context.read",
    "forge.health.read",
    "forge.approval.request",
    "forge.approval.poll"
  ],
  "iss": "jarvis-forge",
  "jti": "<uuid4>",
  "iat": 1743724800,
  "exp": 1744329600
}
```

### 6.5 Service Token (Gateway)

```json
{
  "sub": "gateway",
  "actor_type": "service",
  "node": "gateway",
  "scopes": [
    "gateway.llm.proxy",
    "gateway.unifi.proxy",
    "gateway.cloud.call",
    "gateway.health.read"
  ],
  "iss": "jarvis-gateway",
  "jti": "<uuid4>",
  "iat": 1743724800,
  "exp": 1744329600
}
```

### 6.6 Agent Token (Buddy)

```json
{
  "sub": "buddy",
  "actor_type": "agent",
  "node": "brain",
  "scopes": [
    "memory.evict",
    "memory.promote",
    "tasks.scan",
    "buddy.events.write"
  ],
  "iss": "jarvis-brain",
  "jti": "<uuid4>",
  "iat": 1743724800,
  "exp": 1744329600
}
```

**All tokens include `jti: str(uuid4())` for future deny-list support.**

---

## 7. Scope Registry

### 7.1 Forge Scopes

| Scope | Grants | Brain Route |
|---|---|---|
| `forge.llm.call` | Call Brain's Ollama for planning/review | POST /v1/ask |
| `forge.costs.report` | Submit cost data | POST /v1/costs/ingest |
| `forge.tasks.ingest` | Submit tasks to TaskGraph | POST /v1/tasks/ingest |
| `forge.gaps.submit` | Submit gap detector results | POST /v1/gaps |
| `forge.lessons.sync` | Sync lessons to Brain pgvector | POST /v1/forge/lessons |
| `forge.context.read` | Read project context | GET /v1/forge/context |
| `forge.health.read` | Read Brain health status | GET /health |
| `forge.approval.request` | Request approval for deploy actions | POST /v1/approval/request |
| `forge.approval.poll` | Poll approval status | GET /v1/approval/{id}/status |

### 7.2 Gateway Scopes

| Scope | Grants | Brain Route |
|---|---|---|
| `gateway.llm.proxy` | Proxy cloud LLM calls (Claude/Perplexity/Gemini) | POST /v1/cloud/call |
| `gateway.unifi.proxy` | Proxy UDM Pro API calls | /v1/unifi/* |
| `gateway.cloud.call` | General outbound cloud calls | POST /v1/cloud/call |
| `gateway.health.read` | Read Brain health status | GET /health |

### 7.3 Agent Scopes (Buddy)

| Scope | Grants |
|---|---|
| `memory.evict` | Delete expired working memory rows |
| `memory.promote` | Promote episodic → semantic |
| `tasks.scan` | Read TaskGraph for stuck steps |
| `buddy.events.write` | Write alpha_buddy_events rows |

### 7.4 User Scopes (non-admin)

| Scope | Grants |
|---|---|
| `user.ask` | POST questions to /v1/ask |
| `user.memory.own` | Read/write own memory only |
| `user.home.read` | GET home summary |
| `user.mesh.read` | GET mesh status |
| `user.costs.read` | GET cost summary |
| `user.approve` | Approve actions in approval gateway |

### 7.5 Child Scopes

| Scope | Grants | Restrictions |
|---|---|---|
| `child.ask` | POST questions — content-filtered at Brain before response | No admin, no raw LLM, no cloud direct |
| `child.home.read` | GET home summary — filtered view | No cost data, no security info |

### 7.6 Admin

| Scope | Grants | Audit Rule |
|---|---|---|
| `*` | Wildcard — full access to all routes | MUST log `scopes_used: ["*"]` — never silent bypass |

---

## 8. Brain Middleware Changes

### 8.1 Middleware Stack (LIFO)

```
app.add_middleware(RateLimitMiddleware)    # added 1st → runs 5th
app.add_middleware(RLSContextMiddleware)   # added 2nd → runs 4th
app.add_middleware(ScopeMiddleware)        # added 3rd → runs 3rd
app.add_middleware(AuthMiddleware)         # added 4th → runs 2nd
app.add_middleware(CORSMiddleware)         # added 5th → runs 1st
```

**Execution order:** `CORS → Auth → Scopes → RLS → RateLimit → route handler`

### 8.2 Scope Enforcement

Each route declares required scopes:

```python
@router.post("/v1/forge/lessons")
@require_scopes(["forge.lessons.sync"])
async def sync_lessons(...):
```

**Undecorated routes default to `require_scopes(["*"])` — not open access.** No route is implicitly public.

Wildcard `*` bypasses scope check (admin only) — but MUST log `scopes_used: ["*"]` in audit.

### 8.3 Child Content Filter

`child.ask` requests pass through a content filter middleware layer AFTER scope check, BEFORE route handler. This is infrastructure, not app logic — treat it like Auth middleware, not a route handler feature.

### 8.4 Audit Fields

Every audit log entry and DB write includes:

| Field | Source |
|---|---|
| `actor_sub` | JWT `sub` claim (ken, forge, buddy, ryleigh) |
| `actor_type` | JWT `actor_type` claim (user, service, agent) |
| `actor_node` | JWT `node` claim if present (nullable) |
| `scopes_used` | List of scopes checked for this request (`["*"]` for admin) |

---

## 9. Token Generation and Rotation

### 9.1 Generation Scripts

| Script | Location | Generates |
|---|---|---|
| `gen_service_token.py` | `~/jarvis-alpha/scripts/` on Brain | Agent tokens (Buddy) |
| `gen_forge_token.py` | `~/jarvis/pki/jwt/` on Sandbox | Forge service token |
| `gen_gateway_token.py` | `~/jarvis/pki/jwt/` on Gateway | Gateway service token |

Each script:
1. Loads private key from local filesystem
2. Builds claims including `jti: str(uuid4())`
3. Signs with RS256
4. **Validates the new token against the public key before writing** — fail hard if validation fails
5. Writes to secrets file with `chmod 600`

Token destinations:
- Forge: `~/.secrets/FORGE_SERVICE_TOKEN` on Sandbox
- Gateway: `~/jarvis/.secrets/GATEWAY_SERVICE_TOKEN` on Gateway
- Buddy: `~/jarvis/.secrets/BUDDY_AGENT_TOKEN` on Brain

### 9.2 Weekly Auto-Rotation (LaunchAgent)

Runs every 6 days (1-day overlap before 7-day expiry):

1. Run generation script (generate + validate new token)
2. **If generation fails: send alert, DO NOT restart service** — keep running on existing valid token
3. If generation succeeds: write to secrets file (`chmod 600`)
4. Restart local service to pick up new token
5. Write structured JSON log entry: `{ "timestamp", "node", "result": "success|failure", "reason" }`
6. **On failure:** write `rotation_failures` row to Brain DB → Buddy surfaces in morning briefing

### 9.3 Keypair Rotation (Quarterly — Manual Runbook)

1. Generate new keypair on service node
2. SCP new public key to Brain `pki/` (use Tailscale hostname, not hardcoded IP)
3. **Verify on Brain:** `openssl rsa -in <new_public.pem> -pubin -noout -text`
4. Restart Brain (loads new key alongside old key — keep old key during transition)
5. Generate new service token with new private key, validate it
6. Restart service node
7. **Confirm:** new token validates AND one successful API call in audit log
8. Only after confirmation: remove old public key from Brain `pki/`
9. Restart Brain to drop old key

---

## 10. Public Key Distribution (Initial Setup)

### Sandbox (Forge)

```
▶ SANDBOX —
mkdir -p ~/.pki/jwt
openssl genrsa -out ~/.pki/jwt/forge_private.pem 2048
chmod 600 ~/.pki/jwt/forge_private.pem
openssl rsa -in ~/.pki/jwt/forge_private.pem -pubout -out ~/.pki/jwt/forge_public.pem
scp ~/.pki/jwt/forge_public.pem jarvisbrain@jarvis-brain.tail40ed36.ts.net:~/jarvis-alpha/brain/pki/forge_public.pem
```

### Gateway

```
▶ GATEWAY —
mkdir -p ~/jarvis/pki/jwt
openssl genrsa -out ~/jarvis/pki/jwt/gateway_private.pem 2048
chmod 600 ~/jarvis/pki/jwt/gateway_private.pem
openssl rsa -in ~/jarvis/pki/jwt/gateway_private.pem -pubout -out ~/jarvis/pki/jwt/gateway_public.pem
scp ~/jarvis/pki/jwt/gateway_public.pem jarvisbrain@jarvis-brain.tail40ed36.ts.net:~/jarvis-alpha/brain/pki/gateway_public.pem
```

### Verify on Brain (after each SCP)

```
▶ BRAIN —
openssl rsa -in ~/jarvis-alpha/brain/pki/forge_public.pem -pubin -noout -text
openssl rsa -in ~/jarvis-alpha/brain/pki/gateway_public.pem -pubin -noout -text
```

---

## 11. Migration Path

| Step | What | Effort |
|---|---|---|
| 1 | Generate keypairs on Gateway + Sandbox | 10 min |
| 2 | SCP + verify public keys on Brain | 10 min |
| 3 | Write `config/keys.py` — ISS_TO_KEY_FILE, VALID_ISS_ACTOR_PAIRS, loader | 30 min |
| 4 | Write `@require_scopes` decorator with deny-by-default | 30 min |
| 5 | Add Scopes middleware to LIFO stack | 20 min |
| 6 | Write `gen_*_token.py` per node with validate-before-write | 30 min |
| 7 | Update Forge to send Bearer token on Brain calls | 20 min |
| 8 | Update Gateway to send Bearer token on Brain calls | 20 min |
| 9 | Add audit fields to log entries | 20 min |
| 10 | Write LaunchAgent for weekly rotation + failure alerting | 30 min |
| 11 | Test: wrong key → 401 | 10 min |
| 12 | Test: valid key, wrong scope → 403 | 10 min |
| 13 | Test: unknown iss → rejected | 5 min |
| 14 | Test: iss/actor_type mismatch → rejected | 5 min |
| **Total** | | **~4.5 hours** |

---

## 12. Failure Modes

| Failure | Impact | Mitigation |
|---|---|---|
| Token expires, rotation failed | Service calls rejected (401) | 1-day overlap + failure alert + morning briefing row |
| Brain can't load a public key | That service locked out | Startup log warns, other services unaffected |
| Forge token stolen | Attacker gets Forge scopes only | Narrow scopes, 7-day window, jti enables deny-list |
| Brain private key compromised | User + agent tokens compromised | Rotate Brain key, reissue all user/agent tokens |
| Gateway private key compromised | Gateway scopes compromised | Rotate Gateway key, revoke old public key on Brain |
| Unknown iss in token | Rejected at step 2 | Fast fail, never tries keys |
| iss/actor_type mismatch | Rejected at step 4 | Prevents forge token claiming user identity |

---

## 13. What This Does NOT Cover

- **mTLS between nodes** — deferred. Tailscale + ACLs + service tokens = 8/10.
- **OAuth / OIDC** — not needed for household.
- **Dynamic scope grants** — static per service. Future: approval gateway temporary elevation.
- **Token deny-list** — jti added now, deny-list table built later.
- **Multi-approver flows** — single approver sufficient.

---

*Service Identity Model V2 · jarvis-alpha · April 2026 · Perplexity review incorporated*
