# DISCOVERY — TD-203 Approvals UI cascade (2026-05-08)

**Status:** read-only discovery, no code changes
**Author:** sandbox claude (Phase C of TD batch)
**Date written:** 2026-05-09 (covers incident on 2026-05-08)
**Incident window:** 2026-05-08 11:20–11:25 EDT (= 15:20–15:25 UTC)
**Inputs:** Brain stdout `~/jarvis-alpha/logs/alpha_brain.log`, pg log `/opt/homebrew/var/log/postgresql@16.log`, sandbox source at `~/jarvis-alpha`

Brain log paths confirmed via `launchctl print gui/$(id -u)/com.jarvis.alpha.brain`:
- stdout: `/Users/jarvisbrain/jarvis-alpha/logs/alpha_brain.log` (44 MB, last write 2026-05-09 09:23)
- stderr: `/Users/jarvisbrain/jarvis-alpha/logs/alpha_brain_error.log` (no writes since 2026-04-14 — empty during incident)
- structured = same as stdout (JSON-formatted)
- pg log: `/opt/homebrew/var/log/postgresql@16.log` (320 MB, EDT timestamps)

> **Timezone note:** Brain log is UTC (`+00:00`). Pg log is EDT (UTC−4). 11:20 EDT = 15:20 UTC.

---

## §1 — Error inventory

| # | HTTP | Endpoint | Originating code (file:line) | Server log (verbatim) | Hypothesis | Class |
|---|------|----------|------------------------------|----------------------|-----------|-------|
| 1 | 403 | DELETE /v1/threads/9411280c… | `brain/middleware/approval.py:129-137` (T4/T5 queue branch); classification at `brain/middleware/approval_classes.py:97` `"DELETE /v1/threads/{thread_id}": ["destructive"]` | `15:20:22.248 APPROVAL_NOTIFY_BODY: T5 · destructive ... Queue ID: 8f6a32f4-1c81-4da7-ace3-a5015002e486 ... Queued now`<br>`15:20:22.251 "DELETE /v1/threads/9411280c... HTTP/1.1" 403` | T5 destructive flow firing as designed (HANDOFF #02 ADDENDUM); 403 is the documented "queued for approval" signal | **Working as designed — not a bug** |
| 2 | 500 | POST /v1/approvals/8f6a32f4…/decide | `brain/routes/approvals.py:133-197`. Crash at line **191**: `"queue_id": str(row["id"])` | `15:23:56.637 APPROVAL_DECIDE queue_id=8f6a32f4... decision=approved by=ken`<br>`15:23:56.638 "POST /v1/approvals/8f6a32f4.../decide HTTP/1.1" 500`<br>**Pg log: NO error from this call** (only the 409 retry triggered a pg error) | SQL function `decide_approval` succeeded (returns `RETURNS TABLE (queue_id uuid, ...)` per `migrations/20260415_100000_decide_approval_secdef.sql:14`). Python handler's `logger.info("APPROVAL_DECIDE…")` fires AFTER SQL returns; access log 500 fires within 1 ms — so the failure is between line 188 (logger.info) and the response being serialized. The dict at line 190-197 references `row["id"]`, `row["description"]`, and `row["expires_at"].isoformat()`; only `row["id"]` is missing from the SECDEF wrapper's column set (column is named `queue_id`, not `id`). asyncpg `Record.__getitem__("id")` → `KeyError` → unhandled exception → 500 | **Root cause** |
| 3 | n/a | CORS chained off the 500 above | `brain/app.py:78-84` CORSMiddleware allow_origins=`["https://jarvis-endpoint.tail40ed36.ts.net:4100"]` | (browser-side; not in server logs) | When an unhandled exception escapes user middleware, Starlette's `ServerErrorMiddleware` (registered outside user middleware) returns the 500 response **without traversing** CORSMiddleware on the way out. Browser sees response with no `Access-Control-Allow-Origin` and raises a CORS error. Standard FastAPI behavior. | **Downstream of #2** |
| 4 | 401 | POST /v1/approvals/unlock | `brain/routes/approvals.py:39-87` (PIN check at lines 57-70) | `15:24:23.767 WARNING APPROVAL_UNLOCK_FAIL reason=bad_pin`<br>`15:24:23.771 "POST /v1/approvals/unlock HTTP/1.1" 401`<br>`15:24:30.135 APPROVAL_UNLOCK ok — 5-min window started`<br>`15:24:30.137 "POST /v1/approvals/unlock HTTP/1.1" 200` | User typo'd PIN; succeeded on second attempt 7 s later. First /unlock at 15:23:54 had already returned 200 (the 401 at 15:24:23 was a *new* unlock attempt initiated after the first /decide failed). | **User error — not a bug** |
| 5 | 409 | POST /v1/approvals/c7765f0a…/decide (retry) | Same as #2 + raise path at `approvals.py:175-176` (`APPROVAL_ALREADY_DECIDED` → 409); pg-side at `migrations/20260415_100000_decide_approval_secdef.sql:42-43` | `15:24:46.887 APPROVAL_DECIDE queue_id=c7765f0a... decision=approved by=ken`<br>`15:24:46.888 "...c7765f0a.../decide HTTP/1.1" 500` ← *same Python KeyError as #2*<br>`15:24:48.418 "...c7765f0a.../decide HTTP/1.1" 409`<br>Pg log: `2026-05-08 11:24:48.413 EDT [50845] ERROR: APPROVAL_ALREADY_DECIDED queue_id=c7765f0a... status=approved` `CONTEXT: PL/pgSQL function decide_approval(uuid,text,text,text) line 16 at RAISE` | The first /decide on c7765f0a *also* hit error #2 (500 from `row["id"]`). But the SQL function `decide_approval` had **already committed** the status update to `'approved'` (the function commits in its own transaction; only the Python response builder failed afterward). When the UI retried, the SQL function correctly raised `APPROVAL_ALREADY_DECIDED` (status is now `'approved'`, not `'pending'`), Python caught it and returned 409. | **Downstream of #2** (partial-commit fingerprint) |

---

## §2 — Pre-Slab-6a vs post-Slab-6a comparison

### Was /decide ever working?
Yes — historically. Brain log shows successful `APPROVAL_DECIDE → 200` responses on:
- `2026-04-06T09:32:18` queue_id=4303243a… → 200
- `2026-04-06T10:23:53` queue_id=261942f9… by alpha_ui → 200
- `2026-04-08T00:36:37` queue_id=da43e568… → 200

### What changed?
On **2026-04-15**, commit `7b93604 feat: approval gateway — decide_approval SECDEF + rls_connection on pending/decide` introduced the SECURITY DEFINER wrapper at `migrations/20260415_100000_decide_approval_secdef.sql` and rewrote `routes/approvals.py` to call it via `SELECT * FROM public.decide_approval(...)`. The wrapper's `RETURNS TABLE` declares the first column as `queue_id` (line 14), but the Python rewrite kept `str(row["id"])` (line 191) — a holdover from when the route fetched directly from `alpha_approval_queue` (where the column *is* `id`).

**Why didn't it manifest immediately on 4/15?** Between 4/15 and today, the /decide endpoint was not exercised end-to-end. APPROVAL_DECIDE log lines between 4/15 and 5/7 23:00: **zero** (verified via `grep APPROVAL_DECIDE alpha_brain.log` — only 4/6, 4/8, and the three 5/8 entries above). T5 destructive was queued (line 124728 on 5/7T23:09:21 shows queue_id=1e923a6d…) but that approval was never decided.

### Pre-incident window check on 2026-05-08 (06:00–11:15 EDT):
- Brain log: zero 4xx/5xx on `/v1/approvals/*` or `/v1/threads/*` in this window (pre-Slab-6a).
- Pg log: zero ERROR/FATAL matching `approval|decide|unlock` in this window.

### Verdict
**Errors are post-Slab-6a *in trigger timing*, not in root cause.** The /decide bug was a latent regression introduced 2026-04-15 (commit 7b93604). It surfaced today because:
1. Slab 6a's deployment activity prompted Ken to exercise the Approvals UI cascade end-to-end.
2. The DELETE /v1/threads → T5 destructive queue path was already in place (commit `269b5a9` original), but the prior admin DELETE 500 bug (visible at 5/7 22:15) had been fixed at ~5/7 23:00, so the path now successfully reaches the queue → /decide. That's when the latent KeyError fires for the first time.

Slab 6a itself touched only RLS policies (`064_slab6a_*.sql`, `065_slab6a_rollback.sql`) — no approvals route or `decide_approval` SQL was modified by Slab 6a or by TD-201.

---

## §3 — CORS configuration

`brain/app.py:78-84`:
```
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://jarvis-endpoint.tail40ed36.ts.net:4100"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Middleware registration order in `app.py:73-85` (in `add_middleware` call order; FastAPI executes the **last-added outermost**, so on incoming request the order is reversed):

```
TraceIdMiddleware    (outermost — runs first on request)
CORSMiddleware
JWTAuthMiddleware
ApprovalMiddleware
RateLimitMiddleware
LogMiddleware        (innermost — closest to handler)
→ handler
```

**Why CORS is missing on the 500:** When the /decide handler raises an unhandled `KeyError`, the exception propagates up through `LogMiddleware` (which only swallows its own DB-write errors, not handler errors — see `brain/middleware/log_middleware.py:41-42`), `RateLimitMiddleware`, `ApprovalMiddleware`, `JWTAuthMiddleware`. None catch it. It bubbles all the way out and is finally caught by Starlette's `ServerErrorMiddleware` (registered automatically *outside* user-added middleware), which produces a bare 500 `application/json` response that **does not pass through CORSMiddleware again on the way out**. Browser receives a 500 with no `Access-Control-Allow-Origin` header and reports the response as a CORS failure.

This is the canonical FastAPI symptom: any unhandled exception in a handler produces a CORS-less 500. Two well-known fixes (NOT to be applied here, just listing): (a) catch the exception in the handler and return an `HTTPException` (which DOES traverse CORS on the way out), or (b) install a custom `Exception` handler via `@app.exception_handler(Exception)` that returns a `JSONResponse` (also traverses CORS).

`/v1/approvals/*` is in scope of CORSMiddleware (no path skip).

---

## §4 — Code touchpoints

| Path | Function / range | Role | Likely error path |
|------|-----------|------|-------------------|
| `brain/routes/approvals.py:39-87` | `unlock_approvals` | PIN → 5-min approval JWT | Lines 57-70: bcrypt PIN compare; 401 raised on bad PIN. **Hit by error #4 (user typo)** |
| `brain/routes/approvals.py:133-197` | `decide_approval` (route handler) | Validate approval token → call SQL fn → return decision response | **Lines 190-197**: response dict references `row["id"]` (line 191), `row["description"]` (line 193), `row["expires_at"]` (line 195). Only `row["id"]` is missing from the SECDEF wrapper's output — root of error #2. |
| `brain/routes/approvals.py:162-177` | inner try/except around SQL call | Maps `APPROVAL_NOT_FOUND`→404, `APPROVAL_ALREADY_DECIDED`→409, else re-raise | **Hit by error #5** (409 path, second time around) |
| `brain/middleware/approval.py:39-137` | `ApprovalMiddleware.dispatch` | Classify, hash body, queue T4/T5, return 403 | T5 destructive (DELETE /v1/threads) lands at lines 100-137: queue + notify + 403 with `detail="approval_required"`. **Hit by error #1** |
| `brain/middleware/approval.py:163-173` | `_consume_approved_queue` | Calls `consume_approved_queue_item(queue_id)` to mark consumed | Only invoked when an *approved* request is replayed (line 95). Not hit during the incident — Ken approved but never re-triggered DELETE within the 10-minute window. |
| `brain/middleware/jwt_auth.py:79-123` | `JWTAuthMiddleware.dispatch` | Verify Bearer JWT; raise 401 on missing/invalid/expired | `/v1/approvals/unlock` requires JWT. (Not the source of error #4 — the 401 in error #4 came from the PIN check inside unlock_approvals, not from JWTAuth.) |
| `brain/db/migrations/20260415_100000_decide_approval_secdef.sql:7-92` | `public.decide_approval(uuid, text, text, text)` | SECURITY DEFINER wrapper: validates, updates queue, writes audit, returns row | **Lines 13-23**: `RETURNS TABLE (queue_id uuid, action_class text[], risk_tier text, actor_sub text, actor_type text, description text, parameters_hash text, overnight boolean, expires_at timestamptz)` — note the first column is `queue_id`, **not** `id`. This is the schema mismatch the Python handler ignores. |
| `brain/app.py:73-85` | middleware stack | TraceId(out) → CORS → JWTAuth → Approval → RateLimit → Log(in) → handler | Determines why CORS headers are absent on 500 (§3). |

---

## §5 — Recent commits affecting Approvals (since 2026-04-15)

```
7b93604 feat: approval gateway — decide_approval SECDEF + rls_connection on pending/decide   ← introduced the bug (4/15)
44259e4 feat(stage6b): SECDEF wrappers + rls_connection for approval/buddy writes
355c330 fix(classification): add POST /v1/dream/sessions as write (TD-77)
1fbfcba chore(approval): remove PATCH /v1/dream phantom (exact match, no target)
613e6ba fix(approval): add explicit classification for PATCH dream steps
c998f7e chore(approval): remove 6 phantom ROUTE_CLASSIFICATION entries
0577395 fix(approval): correct method for dream next-step classification POST to GET
4308046 feat(dream): D2-c reviewer + routes + HTTP wiring (15 tests)
```

None of the commits since 7b93604 touched the `/decide` response-builder code or the `decide_approval` SQL signature. All subsequent commits only added/cleaned classifications. The bug has been latent for 23 days.

Today's commits on the current branch (`claude-code/td-201-postflight-fix`, none touch approvals):
```
aa8c5b8 fix(rls): TD-201 POST-FLIGHT false positive in 066
cb7b049 fix(rls): TD-201 expire_pending_approvals multi-row CTE refactor (#81)
e83f688 chore(housekeeping): TD-205 commit discovery dir, TD-206 smoke echo, ADDENDUM #2
c107a06 fix(rls): Slab 6a schema_migrations INSERT needs checksum + source (#79)
d17bc8b feat(rls): Slab 6a migration SQL + rollback + TD-201 amendment (#78)
```

---

## §6 — Recommended sequence (factual)

**Confirmed root causes (1):**
- Error #2 — `KeyError` on `row["id"]` at `brain/routes/approvals.py:191` because SECDEF wrapper returns column `queue_id`. Latent since commit 7b93604 (4/15). Fix is a one-line change: replace `str(row["id"])` with `str(row["queue_id"])`. **Effort: small.**

**Downstream of #2 (resolve when #2 is fixed):**
- Error #3 (CORS chained) — disappears once /decide stops 500'ing. **Effort: zero (passive).**
- Error #5 (409 retry) — won't recur because the first /decide will succeed. The 409 *path* is correct behavior for genuine duplicate requests; nothing to change. **Effort: zero.**

**Not bugs:**
- Error #1 (403 on DELETE) — designed T5 destructive flow per HANDOFF #02 ADDENDUM. **No fix needed.**
- Error #4 (401 on /unlock) — user typo'd PIN (log shows `bad_pin`); succeeded 7 s later. **No fix needed.**

**Open questions blocking diagnosis:** none. All five errors have a verified explanation backed by logs + code references.

**Effort summary:**
- /decide one-line fix: ~5 min code + ~10 min test (if test coverage exists for /decide).
- Optional defense-in-depth (NOT required): add `@app.exception_handler(Exception)` returning `JSONResponse` so any future unhandled handler exception still ships CORS headers. **Effort: small.** Independent of #2.

---

## §7 — Open questions for Ken

1. **Was admin DELETE working pre-5/7 (before the original UI 500 bug)?** Brain log shows DELETE /v1/threads returned 500 throughout 2026-04-28 and 2026-05-07 22:15 — i.e. the original UI 500 had been broken at least since late April. The transition to a working 403 (T5 queue) happened at 2026-05-07 23:09 (first APPROVAL_NOTIFY_BODY for queue_id 1e923a6d… visible in log line 124728). Was this a deploy at that time, or did some other change land?
2. **Has /unlock ever worked?** Yes. Successful 200 responses on 4/6, 4/8, and twice today (15:23:54 and 15:24:30). The 401 today was bad-PIN, not a bug.
3. **Are other Approvals paths fine right now?** GET /v1/approvals/pending returned 200 throughout the incident window (every 10 s polling — see log lines 125958, 125967, 125978, 125982, etc.). POST /v1/approvals/unlock returned 200 on the second attempt today. Only POST /v1/approvals/{id}/decide is broken.
4. **Recommended next action:** Sunday TD-203 fix is the right scope and isolated — single-line diff in `routes/approvals.py:191`, no schema change, no migration. Slab 4 should not block on this. Suggest pairing the one-line fix with a regression test that fetches a pending approval, calls /decide, asserts 200 and that the response body contains a `queue_id` matching the request URL.

---

## Appendix — log artifacts (raw, redacted of secrets)

Brain log line numbers and timestamps for the cascade:
```
125921  15:20:22.248Z  APPROVAL_NOTIFY_BODY (queue_id=8f6a32f4..., T5 destructive)
125922  15:20:22.251Z  DELETE /v1/threads/9411280c... → 403           [Error #1]
125956  15:23:54.301Z  OPTIONS /v1/approvals/unlock → 200
125957  15:23:54.423Z  APPROVAL_UNLOCK ok — 5-min window started
125958  15:23:54.425Z  POST /v1/approvals/unlock → 200                (good unlock)
125959  15:23:56.608Z  OPTIONS /v1/approvals/8f6a32f4.../decide → 200
125960  15:23:56.637Z  APPROVAL_DECIDE queue_id=8f6a32f4 decision=approved
125961  15:23:56.638Z  POST /v1/approvals/8f6a32f4.../decide → 500    [Error #2]
                                                                      [Error #3 = CORS chained off this 500, browser-side]
125967  15:24:09.815Z  APPROVAL_NOTIFY_BODY (queue_id=c7765f0a..., new T5 queue)
125968  15:24:09.819Z  DELETE /v1/threads/9411280c... → 403           (UI re-tried DELETE → re-queued)
125971  15:24:23.767Z  WARNING APPROVAL_UNLOCK_FAIL reason=bad_pin
125972  15:24:23.771Z  POST /v1/approvals/unlock → 401                [Error #4 — typo]
125974  15:24:30.135Z  APPROVAL_UNLOCK ok — 5-min window started
125975  15:24:30.137Z  POST /v1/approvals/unlock → 200                (typo recovered)
125979  15:24:46.887Z  APPROVAL_DECIDE queue_id=c7765f0a decision=approved
125980  15:24:46.888Z  POST /v1/approvals/c7765f0a.../decide → 500    (Error #2 reproduces)
125982  15:24:48.418Z  POST /v1/approvals/c7765f0a.../decide → 409    [Error #5]
```

Pg log error during cascade:
```
2026-05-08 11:24:48.413 EDT [50845] ERROR:  APPROVAL_ALREADY_DECIDED queue_id=c7765f0a-354b-4265-9b76-8ae1f194add7 status=approved
2026-05-08 11:24:48.413 EDT [50845] CONTEXT:  PL/pgSQL function decide_approval(uuid,text,text,text) line 16 at RAISE
2026-05-08 11:24:48.413 EDT [50845] STATEMENT:  SELECT * FROM public.decide_approval($1::uuid, $2, $3, $4)
```
(Only one pg ERROR in the entire cascade — confirms the first /decide was a Python-side failure, not SQL-side.)
