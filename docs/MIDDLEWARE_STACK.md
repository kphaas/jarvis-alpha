# JARVIS Alpha — Middleware Stack & Request Lifecycle

**April 2026 · github.com/kphaas/jarvis-alpha · main**
**Purpose:** Document the request lifecycle, middleware order, and authorization model for jarvis-alpha Brain.

---

## 1. Middleware Stack

FastAPI executes middleware in **reverse registration order** (LIFO) — the last `add_middleware()` call runs first on the request path, last on the response path.

| Order | Middleware | File | Purpose |
|---|---|---|---|
| 1 | TraceIdMiddleware | `middleware/trace_id.py` | Generate trace_id, attach to request + response |
| 2 | CORSMiddleware | (starlette built-in) | Allow Endpoint origin, handle preflight OPTIONS |
| 3 | JWTAuthMiddleware | `middleware/jwt_auth.py` | Decode RS256 JWT, set request.state.user_id/role/scopes/iss/actor_type |
| 4 | AuthMiddleware | `middleware/auth_middleware.py` | Legacy auth compat layer (set/normalize user_id) |
| 5 | RLSMiddleware | `middleware/rls_middleware.py` | Placeholder — RLS set per-transaction in route handlers |
| 6 | ApprovalMiddleware | `middleware/approval.py` | Classify route → risk tier, T1-T3 pass-through, T4/T5 block |
| 7 | RateLimitMiddleware | `middleware/rate_limit_middleware.py` | 300 req/min per user_id sliding window |
| 8 | LogMiddleware | `middleware/log_middleware.py` | Structured JSON access log |

**Execution order:** `TraceId → CORS → JWT → Auth → RLS → Approval → RateLimit → Log → handler`

## 2. app.py Registration (LIFO)
```python
app.add_middleware(LogMiddleware)           # 8th — runs last on request
app.add_middleware(RateLimitMiddleware)     # 7th
app.add_middleware(ApprovalMiddleware)      # 6th
app.add_middleware(RLSMiddleware)           # 5th
app.add_middleware(AuthMiddleware)          # 4th
app.add_middleware(JWTAuthMiddleware)       # 3rd
app.add_middleware(CORSMiddleware, ...)     # 2nd
app.add_middleware(TraceIdMiddleware)       # 1st — runs first on request
```

## 3. CORS Configuration

| Setting | Value |
|---|---|
| allow_origins | `https://jarvis-endpoint.tail40ed36.ts.net:4100` only |
| allow_credentials | true |
| allow_methods | `*` |
| allow_headers | `*` |

---

## 4. JWT Authentication

### 4.1 Algorithm and Keys

- **Algorithm:** RS256 (asymmetric)
- **Key registry:** Multi-key validation by `iss` claim — Brain loads all `*.pem` files from `brain/pki/`
- **Keys:**
  - `jwt_public.pem` — Brain's own key (users + agents like Buddy)
  - `gateway_public.pem` — Gateway service key
  - `forge_public.pem` (via sandbox iss) — Sandbox/Forge service key
- **Issuer mapping:** Each token's `iss` claim selects the verification key. Validation tries the iss-mapped key first, falls back to all keys for legacy compat.

### 4.2 Token Claims

Every token MUST include:

| Claim | Example | Purpose |
|---|---|---|
| `sub` | `ken`, `forge-service`, `buddy` | Subject identifier |
| `iss` | `brain`, `gateway`, `sandbox`, `buddy` | Issuer — selects verification key |
| `actor_type` | `user`, `service`, `agent` | Distinguishes humans from machines |
| `role` | `admin`, `user`, `child`, `service` | RBAC role (only meaningful for actor_type=user) |
| `scopes` | `["forge.briefings.ingest", "briefings.read"]` | Capability list (see Scope Registry) |
| `iat` / `exp` | Unix timestamps | Lifetime |

### 4.3 Skip Paths (No JWT Required)

These paths bypass JWT validation:

- `/health`
- `/v1/auth/pin`
- `/docs`, `/openapi.json`, `/redoc`
- `/v1/metrics/power`, `/v1/metrics/power/current`, `/v1/metrics/power/history`, `/v1/metrics/power/rollup`
- Honeypot trap paths: `/admin`, `/wp-login.php`, `/.env`, `/.git/config`, `/phpmyadmin`, `/api/v1/debug`
- OPTIONS method (all paths)

---

## 5. Authorization (Scopes) — Enforcement Pattern

**IMPORTANT:** Scope enforcement is done via **inline `check_scopes()` calls inside route handlers**, NOT via a ScopeMiddleware layer or a `@require_scopes` decorator.

### 5.1 Why Inline (Not Middleware or Decorator)

| Approach | Status | Reason |
|---|---|---|
| Middleware (ScopeMiddleware) | ❌ Not implemented | Would require route-pattern matching at middleware level — fragile and slow |
| Decorator (`@require_scopes`) | ❌ Removed in April 2026 | Decorator silently failed to enforce — replaced with inline calls during Dream Mode debugging |
| **Inline (`check_scopes()`)** | ✅ Current standard | Explicit, testable, traceable in code review |

### 5.2 Helper Function

`brain/middleware/scopes.py` exposes:
```python
def check_scopes(request: Request, *required: str) -> None:
    """Raises HTTPException(403) if caller doesn't have at least one required scope.
    Admin users (actor_type=user, role=admin) bypass scope checks.
    Wildcard scope (*) bypasses scope checks.
    """
```

### 5.3 Required Pattern in Route Handlers
```python
from brain.middleware.scopes import check_scopes

@router.post("/v1/briefings/ingest", status_code=201)
async def ingest_briefing(request: Request, body: BriefingIngest):
    check_scopes(request, "forge.briefings.ingest")  # MUST be first line
    # ... handler logic ...
```

**Rules:**
1. `check_scopes()` MUST be the first line inside the handler body
2. The handler function MUST accept `request: Request` as a parameter
3. Multiple acceptable scopes can be passed: `check_scopes(request, "scope.a", "scope.b")` (OR logic)
4. Read endpoints typically check `<domain>.read`; write endpoints check `<domain>.<action>`

### 5.4 Scope Registry

The canonical scope registry lives in the JARVIS Alpha architecture spec (project knowledge: SERVICE_IDENTITY_MODEL.md). Key namespaces:

| Namespace | Owner | Examples |
|---|---|---|
| `forge.*` | jarvis-forge service | `forge.briefings.ingest`, `forge.llm.call`, `forge.costs.report` |
| `gateway.*` | jarvis-alpha gateway | `gateway.llm.proxy`, `gateway.cloud.call` |
| `buddy.*` | Buddy agent | `buddy.events.write` |
| `dream.*` | Dream Mode (overnight) | `dream.execute`, `dream.kill` |
| `memory.*` | Buddy/agents | `memory.evict`, `memory.promote` |
| `briefings.*` | Generic readers | `briefings.read` |
| `user.*` | Human users | `user.ask`, `user.home.read` |
| `child.*` | Child profiles | `child.ask`, `child.home.read` |
| `*` | Admin only | Wildcard — bypasses scope check entirely |

### 5.5 Apple-Style Naming Convention

Scopes follow `<producer>.<resource>.<action>` for write operations and `<resource>.<action>` for generic reads.

- `forge.briefings.ingest` — only forge writes briefings
- `briefings.read` — anyone with read access can read briefings
- Future: `buddy.briefings.ingest` if Buddy starts producing briefings (different producer = different scope)

---

## 6. Approval Risk Tiers

| Tier | Action | Example |
|---|---|---|
| T1 | Pass, no audit | GET reads |
| T2 | Pass + audit | Writes, external calls |
| T3 | Pass + audit + notify | Cost-incurring calls |
| T4 | Block → queue for approval | Deploys, child-facing |
| T5 | Block → queue + PIN re-entry | Destructive, admin, unclassified |

The classification map lives in `brain/middleware/approval_classes.py`. Routes not in the map are denied by default (T5 effectively).

---

## 7. Rate Limiting

| Setting | Value |
|---|---|
| Window | 60 seconds sliding |
| Max | 300 requests per user_id |
| Bypass paths | `/health`, `/v1/health`, `/docs`, `/openapi.json` |
| Response | 429 with `Retry-After` header |

---

## 8. RLS — Critical Pattern

Row-Level Security session variables (`rls.user_id`, `app.profile_id`, etc.) are set **per-transaction** inside route handlers using `conn.transaction()`. The RLSMiddleware is a placeholder — actual enforcement happens at the Postgres level via row-level security policies.

### 8.1 Required Pattern (asyncpg)
```python
async with pool.acquire() as conn:
    try:
        async with conn.transaction():
            await _set_rls_user(conn, user_id, request)
            # ... queries ...
    finally:
        await _reset_rls(conn)
```

### 8.2 Why This Matters

`set_config(..., true)` is **transaction-local** in Postgres. Without explicit `conn.transaction()`, asyncpg autocommit discards the config between statements, and queries run with no RLS context — silently leaking data across users.

**Tables under RLS today:**
- `alpha_conversation_memory` — policy `alpha_memory_isolation`

**Tables NOT under RLS yet (planned for Alpha-2):**
- `alpha_briefings` — admin-only data, deferred
- `chat_threads`, `chat_messages` — child profile RLS pending
- `alpha_workspaces` — workspace isolation pending

---

## 9. JSONB Encoding — asyncpg Gotcha

asyncpg requires explicit `json.dumps()` for JSONB column writes and `json.loads()` for reads. Pydantic dict/list values are NOT auto-converted.

### 9.1 Write Pattern
```python
await conn.execute(
    "INSERT INTO alpha_briefings (summary, results) VALUES ($1, $2)",
    json.dumps(body.summary),    # NOT body.summary
    json.dumps(body.results),    # NOT body.results
)
```

### 9.2 Read Pattern

asyncpg returns JSONB columns as **strings**. Routes must parse them before returning:
```python
def _parse_jsonb(value):
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value
```

### 9.3 Failure Mode

Without `json.dumps()` on write: `asyncpg.exceptions.DataError: invalid input for query argument $N: {...} (expected str, got dict)` → 500 error.

Without `json.loads()` on read: Pydantic silently coerces unparseable strings to empty dict/list defaults → API returns `{}` or `[]` instead of the actual data, with no error.

---

## 10. Inter-Node HTTP Calls — curl + asyncio.to_thread

**Never use httpx for inter-node calls.** Python httpx fails against Tailscale TLS due to OpenSSL 3.x strict behavior.

### Established Pattern
```python
import asyncio
import subprocess

async def call_brain(payload: dict) -> dict:
    def _curl():
        result = subprocess.run(
            ["curl", "-sk", "-X", "POST",
             "-H", f"Authorization: Bearer {token}",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload),
             "https://jarvis-brain.tail40ed36.ts.net:8186/v1/some/endpoint"],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout
    raw = await asyncio.to_thread(_curl)
    return json.loads(raw)
```

---

## 11. Logging Standards

All middleware and route handlers log structured JSON via `jarvis_common.logging_config.get_logger()`. Required fields:

| Field | Source |
|---|---|
| `ts` | ISO8601 UTC timestamp |
| `level` | DEBUG / INFO / WARNING / ERROR |
| `service` | `alpha_brain`, `alpha_brain_access`, etc. |
| `node` | `brain`, `gateway`, `endpoint`, `sandbox` |
| `trace_id` | From TraceIdMiddleware |
| `message` | Human-readable summary |

Optional audit fields for sensitive operations:

| Field | Source |
|---|---|
| `actor_sub` | JWT `sub` claim |
| `actor_type` | JWT `actor_type` claim |
| `actor_iss` | JWT `iss` claim |
| `scopes_used` | Which scopes were checked for this request |

---

## 12. Anti-Patterns — DO NOT

- ❌ `@require_scopes` decorator — removed April 2026, use inline `check_scopes()`
- ❌ httpx for inter-node HTTPS calls — use curl + `asyncio.to_thread`
- ❌ Raw dict/list to asyncpg JSONB columns — wrap with `json.dumps()`
- ❌ DB queries outside `conn.transaction()` when RLS is required
- ❌ Hardcoded IPs/hostnames — use `node_addresses.py` and `os.getenv`
- ❌ macOS Keychain in headless services — use `~/jarvis/.secrets` (chmod 600)
- ❌ Bare `print()` for logs — use structured `get_logger()`
- ❌ Relying on FastAPI's default 500 handler for known error states — return explicit HTTPException

---

*MIDDLEWARE_STACK.md · April 2026 · github.com/kphaas/jarvis-alpha*
