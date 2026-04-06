# Middleware stack

| Order | Middleware | File | Purpose |
|---|---|---|---|
| 1 | TraceIdMiddleware | middleware/trace_id.py | Generate trace_id, attach to request + response |
| 2 | CORSMiddleware | (starlette built-in) | Allow Endpoint origin, handle preflight OPTIONS |
| 3 | JWTAuthMiddleware | middleware/jwt_auth.py | Decode RS256 JWT, set request.state.user_id/role/scopes |
| 4 | AuthMiddleware | middleware/auth_middleware.py | Legacy auth compat layer |
| 5 | RLSMiddleware | middleware/rls_middleware.py | Placeholder — RLS set per-transaction in route handlers |
| 6 | ApprovalMiddleware | middleware/approval.py | Classify route → risk tier, T1-T3 pass-through, T4/T5 block |
| 7 | RateLimitMiddleware | middleware/rate_limit_middleware.py | 300 req/min per user_id sliding window |
| 8 | LogMiddleware | middleware/log_middleware.py | Structured JSON access log |

## app.py registration (LIFO)

```python
app.add_middleware(LogMiddleware)           # 8th — runs last
app.add_middleware(RateLimitMiddleware)     # 7th
app.add_middleware(ApprovalMiddleware)      # 6th
app.add_middleware(RLSMiddleware)           # 5th
app.add_middleware(AuthMiddleware)          # 4th
app.add_middleware(JWTAuthMiddleware)       # 3rd
app.add_middleware(CORSMiddleware, ...)     # 2nd
app.add_middleware(TraceIdMiddleware)       # 1st — runs first
```

## CORS

- `allow_origins`: `https://jarvis-endpoint.tail40ed36.ts.net:4100` only
- `allow_credentials`: true
- `allow_methods`: `*`
- `allow_headers`: `*`

## JWT skip paths

These paths bypass JWT validation:

- `/health`
- `/v1/auth/pin`
- `/docs`, `/openapi.json`, `/redoc`
- `/v1/metrics/power`, `/v1/metrics/power/current`, `/v1/metrics/power/history`, `/v1/metrics/power/rollup`
- Honeypot trap paths: `/admin`, `/wp-login.php`, `/.env`, `/.git/config`, `/phpmyadmin`, `/api/v1/debug`
- OPTIONS method (all paths)

## Risk tiers (Approval)

| Tier | Action | Example |
|---|---|---|
| T1 | Pass, no audit | GET reads |
| T2 | Pass + audit | Writes, external calls |
| T3 | Pass + audit + notify | Cost-incurring calls |
| T4 | Block → queue for approval | Deploys, child-facing |
| T5 | Block → queue + PIN re-entry | Destructive, admin, unclassified |

## Rate limiting

- Window: 60 seconds sliding
- Max: 300 requests per user_id
- Bypass: `/health`, `/v1/health`, `/docs`, `/openapi.json`
- Returns: 429 with `Retry-After` header

## RLS note

RLS session variables (`rls.user_id`, `app.profile_id`, etc.) are set **per-transaction** inside route handlers using `conn.transaction()`. The middleware is a placeholder — actual RLS enforcement happens at the Postgres level via row-level security policies.

Key pattern (required for asyncpg):

```python
async with pool.acquire() as conn:
    try:
        async with conn.transaction():
            await _set_rls_user(conn, user_id, request)
            # ... queries ...
    finally:
        await _reset_rls(conn)
```

`set_config(..., true)` is transaction-local in Postgres. Without explicit `conn.transaction()`, asyncpg autocommit discards the config between statements.
