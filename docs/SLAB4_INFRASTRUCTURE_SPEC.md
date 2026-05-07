# SLAB 4 — Infrastructure Consolidation Spec

**Locked:** May 1, 2026
**Predecessor:** SLAB3_POLICY_TEMPLATE.md (defines the policy shapes this slab supports)
**Successor:** Slab 5 (uses the helpers built here to fix TD-181 and Apr 27 Lock 8)

## What Slab 4 is

The infrastructure layer that makes Slab 5 (bug fixes) and Slab 6 (atomic deploy) possible. **No production policies change here.** This slab builds the typed wrapper, SECDEF function fleet, listener rebuild, and Q6 enforcement layers.

## Locked decisions

- **Q8 (A'):** Typed wrapper as frozen dataclass `RLSContext` + `set_rls_context()` function
- **Q9 (A):** Dedicated long-lived listener connection with exponential-backoff reconnect, with TD-189 caveat
- **Q10 (A):** `record_<event>()` for writes, `<verb>_<noun>()` for queries
- **Q11 (A'):** 3-file split — `rls.py` (identity+GUCs), `rls_writers.py` (SECDEF wrappers), `rls_helpers.py` (utilities)

## TDs closed by this slab

| TD | Title | Closed how |
|---|---|---|
| TD-94 | Watchdog SIGTERM / stale executor | Listener rebuild with dedicated connection |
| TD-182 | Three private GUC helpers bypass rls_connection() | Consolidate into `set_rls_context()` with service-context param |

## TDs Slab 4 deliberately does NOT close

| TD | Why deferred |
|---|---|
| TD-181 | Bug fix — Slab 5 uses Slab 4's typed wrapper to fix the call site |
| TD-189 (NEW) | Outbox+poll for at-least-once semantics — Slab 7+ scope |

---

## File structure (Q11-A' — split day one)
brain/db/
rls.py            ~200 lines after Slab 4
Identity + GUC management
- RLSContext dataclass
- set_rls_context(conn, ctx)
- rls_connection() async context manager
- LISTEN/NOTIFY listener task
rls_writers.py    ~200 lines after Slab 4
SECDEF wrappers - all DB writes by background agents
- record_buddy_event()
- record_watchdog_event()
- record_approval_event()
- record_executor_event()
- record_dream_session_event()
(Python helpers that call the matching SQL SECDEF function)
rls_helpers.py    ~100 lines after Slab 4
Non-SECDEF utilities
- rating_ceiling_check (Python helper for SQL function)
- GUC introspection helpers (debug only)

`tests/db/` mirrors this structure: `test_rls.py`, `test_rls_writers.py`, `test_rls_helpers.py`.

---

## RLSContext dataclass (Q8-A')

```python
# brain/db/rls.py

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

Role = Literal['platform_admin', 'user', 'child']
MaxRating = Literal['all_ages', 'age_8_plus', 'teen', 'adult']

@dataclass(frozen=True, slots=True)
class RLSContext:
    """Immutable RLS context derived from a validated JWT.

    Frozen + slots:
      - frozen: prevents accidental mutation after construction
      - slots: minimal memory footprint (no __dict__)

    Future fields (e.g., tenant_id, audit_session_id) added with defaults
    do not break call sites.
    """
    user_id: UUID
    role: Role
    max_rating: MaxRating
    workspace_id: UUID

    @classmethod
    def from_jwt_claims(cls, claims: dict) -> 'RLSContext':
        """Construct from validated JWT claim dict."""
        return cls(
            user_id=UUID(claims['sub']),
            role=claims['role'],
            max_rating=claims['max_rating'],
            workspace_id=UUID(claims['workspace_id']),
        )
```

### Validation strategy

Mypy enforces `Role` and `MaxRating` literals at PR time. JWT claims are validated upstream (auth middleware) so RLSContext does not re-validate. If a malformed claim reaches `from_jwt_claims`, KeyError or ValueError raises naturally - **fail-closed by exception, not by silently writing bad GUCs**.

---

## set_rls_context() (Q8-A' + Q11-A' co-located)

```python
# brain/db/rls.py

import asyncpg

async def set_rls_context(
    conn: asyncpg.Connection,
    ctx: RLSContext,
) -> None:
    """Set rls.* GUCs for the duration of the current transaction.

    REQUIRES the connection to be inside an active transaction.
    set_config(name, value, true) is transaction-local; called outside
    a transaction, the GUCs are invisible to subsequent queries.

    Raises:
        asyncpg.InvalidTransactionStateError: if no active transaction
        asyncpg.PostgresError: any GUC write failure
    """
    if conn.is_in_transaction() is False:
        raise asyncpg.InvalidTransactionStateError(
            "set_rls_context() must be called inside a transaction"
        )

    await conn.execute(
        "SELECT "
        "set_config('rls.user_id', $1::text, true), "
        "set_config('rls.role', $2, true), "
        "set_config('rls.max_rating', $3, true), "
        "set_config('rls.workspace_id', $4::text, true)",
        str(ctx.user_id),
        ctx.role,
        ctx.max_rating,
        str(ctx.workspace_id),
    )
```

### Why a single SELECT instead of four

Atomic. One round trip. If any set_config fails, none take effect (transaction semantics). Fewer log lines for pgAudit.

### Transaction-local enforcement

`set_config(..., true)` is the locked pattern from memory: transaction-scoped. Calling outside a transaction silently fails - GUCs disappear before queries see them. The `is_in_transaction()` precondition makes this audible.

---

## TD-182 consolidation: rls_connection() with service context

The three private bypassers (`activity_db`, `_bind_executor_rls`, `_rls_dev`) are replaced by a single canonical entry point with a service-context parameter:

```python
# brain/db/rls.py

from contextlib import asynccontextmanager
from typing import Literal, Optional, AsyncIterator

ServiceContext = Literal['request', 'executor', 'buddy', 'watchdog', 'dev']

@asynccontextmanager
async def rls_connection(
    pool: asyncpg.Pool,
    ctx: Optional[RLSContext] = None,
    service: ServiceContext = 'request',
) -> AsyncIterator[asyncpg.Connection]:
    """Acquire a connection with RLS context applied.

    For 'request' service: ctx is required, sets rls.* from JWT
    For 'executor'/'buddy'/'watchdog': ctx is None, agent runs via SECDEF
    For 'dev': ctx is None, no GUCs set (test-only, requires DB role to bypass)
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            if service == 'request':
                if ctx is None:
                    raise ValueError("RLSContext required for 'request' service")
                await set_rls_context(conn, ctx)
            elif service in ('executor', 'buddy', 'watchdog'):
                # No GUCs set on this connection - agents call SECDEF functions
                # which set their own rls.* on entry
                pass
            elif service == 'dev':
                # Test-only path. DB role must have BYPASSRLS or test schema.
                pass
            yield conn
```

### Why this absorbs TD-182

The three bypassers existed because callers needed different setup paths. `service=` parameter makes those paths first-class and audited. Anyone reading the codebase sees one canonical helper, not three private ones.

---

## SECDEF function fleet (Q10-A)

### Template

```sql
-- brain/db/migrations/<timestamp>_slab4_secdef_fleet.sql

CREATE OR REPLACE FUNCTION record_buddy_event(
    p_event_type TEXT,
    p_payload JSONB,
    p_user_id UUID DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
SET lock_timeout = '5s'
AS $$
DECLARE
    v_id UUID;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    PERFORM set_config('rls.calling_agent', 'buddy', true);

    INSERT INTO alpha_buddy_events (event_type, payload, user_id)
    VALUES (p_event_type, p_payload, p_user_id)
    RETURNING id INTO v_id;

    RETURN v_id;
EXCEPTION
    WHEN sqlstate '23503' OR sqlstate '23505' OR sqlstate '23514' THEN
        -- FK / unique / check violations: re-raise so caller sees the bug
        RAISE;
    WHEN OTHERS THEN
        RAISE WARNING 'record_buddy_event failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
        RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION record_buddy_event(TEXT, JSONB, UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION record_buddy_event(TEXT, JSONB, UUID) TO jarvis_alpha_writer;
```

### Functions to ship in Slab 4

| Function | Replaces |
|---|---|
| record_buddy_event | direct INSERT into alpha_buddy_events from Buddy agent |
| record_watchdog_event | direct INSERT into alpha_watchdog_events from Watchdog |
| record_approval_event | direct INSERT into alpha_approval_audit from approval flow |
| record_executor_event | direct INSERT into alpha_task_events from Executor |
| record_dream_session_event | direct INSERT into alpha_dream_steps from Dream Mode workflow |

### Python wrappers

```python
# brain/db/rls_writers.py

import asyncpg
from typing import Optional
from uuid import UUID

async def record_buddy_event(
    pool: asyncpg.Pool,
    event_type: str,
    payload: dict,
    user_id: Optional[UUID] = None,
) -> Optional[UUID]:
    """Record a Buddy lifecycle event via SECDEF.

    Returns:
        UUID of the inserted row, or None on retryable error.
    Raises:
        asyncpg.IntegrityConstraintViolationError on bug-class errors.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await conn.fetchval(
                "SELECT record_buddy_event($1, $2, $3)",
                event_type, payload, user_id,
            )
```

Same shape for the other 4 functions. Python signature mirrors SQL signature.

---

## rating_ceiling_check() (Slab 3 dependency)

Used by RESTRICTIVE child overlays in Shape A and A-FK tables.

```sql
-- brain/db/migrations/<timestamp>_slab4_secdef_fleet.sql

CREATE OR REPLACE FUNCTION rating_ceiling_check(
    content_rating TEXT,
    user_max_rating TEXT
)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT CASE user_max_rating
        WHEN 'adult' THEN content_rating IN ('all_ages','age_8_plus','teen','adult')
        WHEN 'teen' THEN content_rating IN ('all_ages','age_8_plus','teen')
        WHEN 'age_8_plus' THEN content_rating IN ('all_ages','age_8_plus')
        WHEN 'all_ages' THEN content_rating = 'all_ages'
        ELSE FALSE  -- unknown / unset rating: deny
    END
$$;

REVOKE ALL ON FUNCTION rating_ceiling_check(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION rating_ceiling_check(TEXT, TEXT) TO PUBLIC;
```

### Notes
- IMMUTABLE + PARALLEL SAFE: query planner can cache + parallelize
- Not SECDEF: it is a pure function, no DML, safe to run as caller
- Default-deny on unknown ratings (fail-closed)

---

## LISTEN/NOTIFY rebuild (Q9-A + TD-94 fold-in)

### Architecture
                          Brain Postgres
                               |
                            NOTIFY graph_submitted
                               |
                      +--------+--------+
                      |                 |
          dedicated listener      asyncpg pool
          (rls.py)                (request path)
                      |
              on payload received,
              dispatch into pool
              via task queue

### Listener implementation

```python
# brain/db/rls.py

import asyncio
import asyncpg
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

class GraphListener:
    """Dedicated long-lived LISTEN/NOTIFY connection.

    NOT in the asyncpg pool - LISTEN sessions have unbounded lifespan
    and would defeat pool semantics.

    On disconnect: exponential backoff reconnect (1s -> 2s -> ... -> 60s),
    re-LISTEN on every reconnect.
    """

    def __init__(self, dsn: str, channel: str, on_notify: Callable[[str], Awaitable[None]]):
        self._dsn = dsn
        self._channel = channel
        self._on_notify = on_notify
        self._conn: asyncpg.Connection | None = None
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"listener:{self._channel}")

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._conn:
            await self._conn.close()

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stopping:
            try:
                self._conn = await asyncpg.connect(self._dsn)
                await self._conn.add_listener(self._channel, self._handle)
                logger.info(f"listener connected channel={self._channel}")
                backoff = 1.0  # reset on successful connect

                # Block until connection drops or task cancelled
                while not self._stopping:
                    await asyncio.sleep(30)
                    # Heartbeat: confirm connection is alive
                    try:
                        await self._conn.execute("SELECT 1")
                    except Exception:
                        logger.warning(f"listener heartbeat failed channel={self._channel}")
                        break

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"listener error channel={self._channel}: {e}")

            if self._stopping:
                return

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    def _handle(self, conn, pid, channel, payload):
        # asyncpg handler is sync; schedule async work
        asyncio.create_task(self._dispatch(payload), name=f"dispatch:{channel}")

    async def _dispatch(self, payload: str) -> None:
        try:
            await self._on_notify(payload)
        except Exception as e:
            logger.error(f"dispatch failed channel={self._channel}: {e}")
```

### TD-189 caveat (important)

The listener pattern above handles connection lifecycle but **does NOT solve missed-message semantics during reconnect windows**. Postgres NOTIFY is fire-and-forget: messages emitted while no listener is connected are lost forever.

For at-least-once delivery, an outbox+poll pattern is required: writers INSERT into an outbox table, listener uses NOTIFY only as a wakeup signal, poll catches up on missed messages.

**Captured as TD-189 (P3, Slab 7+).** Out of Slab 4 scope.

---

## Q6 Layer 1 - CI invariant check

```python
# tests/db/test_rls_invariant.py

import pytest

@pytest.mark.asyncio
async def test_every_rls_table_has_permissive_policy(test_pool):
    """Q6 invariant: RLS-enabled table without PERMISSIVE policy returns
    zero rows for ALL queries (including admin) - silent fail-closed bug.
    This test fails the PR if the invariant breaks.
    """
    async with test_pool.acquire() as conn:
        rls_tables = await conn.fetch("""
            SELECT c.relname AS table_name
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
              AND (c.relrowsecurity = true OR c.relforcerowsecurity = true)
            ORDER BY c.relname
        """)

        violations = []
        for row in rls_tables:
            t = row['table_name']
            n = await conn.fetchval(
                "SELECT count(*) FROM pg_policies "
                "WHERE schemaname='public' AND tablename=$1 AND permissive='PERMISSIVE'",
                t,
            )
            if n == 0:
                violations.append(t)

        assert not violations, (
            f"RLS tables with no PERMISSIVE policy "
            f"(silent fail-closed): {violations}"
        )
```

---

## Q6 Layer 2 - DB event trigger

```sql
-- brain/db/migrations/<timestamp>_slab4_invariant_trigger.sql

CREATE OR REPLACE FUNCTION enforce_permissive_policy_on_force_rls()
RETURNS event_trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    obj RECORD;
    n INT;
BEGIN
    FOR obj IN
        SELECT * FROM pg_event_trigger_ddl_commands()
        WHERE command_tag = 'ALTER TABLE'
    LOOP
        IF EXISTS (
            SELECT 1 FROM pg_class
            WHERE oid = obj.objid AND relforcerowsecurity = true
        ) THEN
            SELECT count(*) INTO n
            FROM pg_policies
            WHERE schemaname = obj.schema_name
              AND tablename = (obj.object_identity::regclass)::text
              AND permissive = 'PERMISSIVE';
            IF n = 0 THEN
                RAISE EXCEPTION
                    'Cannot FORCE RLS on % - no PERMISSIVE policy exists',
                    obj.object_identity;
            END IF;
        END IF;
    END LOOP;
END;
$$;

CREATE EVENT TRIGGER enforce_permissive_policy
    ON ddl_command_end
    WHEN TAG IN ('ALTER TABLE')
    EXECUTE FUNCTION enforce_permissive_policy_on_force_rls();
```

Layer 2 is the runtime safety net. CI catches PRs; trigger catches emergency hotfixes that bypass CI.

---

## Implementation sequencing (suggested order for Cursor work)

1. **Day 1 morning** - File scaffolding: create `rls_writers.py` and `rls_helpers.py` empty with proper docstrings; existing `rls.py` stays unchanged
2. **Day 1 afternoon** - RLSContext dataclass + set_rls_context() + tests
3. **Day 2 morning** - SECDEF SQL migration for record_<event>() fleet + Python wrappers in rls_writers.py
4. **Day 2 afternoon** - rating_ceiling_check() SQL function + helper in rls_helpers.py
5. **Day 3 morning** - rls_connection() service-context refactor (TD-182 consolidation)
6. **Day 3 afternoon** - GraphListener implementation in rls.py
7. **Day 4** - Q6 Layer 1 CI test + Q6 Layer 2 event trigger + integration tests
8. **Day 5** - 24-hour soak; if green, Slab 5 unblocked

Cursor work begins next session, not in this spec session.

---

## Cross-references

- `~/jarvis-alpha/docs/PATTERNS.md` - pgAudit + SQLSTATE conventions (Slab 1)
- `~/jarvis-alpha/docs/SLAB2_DEPLOY_PLAN.md` - GUC namespace migration (shipped)
- `~/jarvis-alpha/docs/SLAB3_POLICY_TEMPLATE.md` - Shape A / A-FK / B templates (shipped)
- Slab 5 spec (pending): TD-181 + Apr 27 Lock 8 fixes using helpers from this slab
- Slab 6 spec (pending re-cut): atomic policy deploy with sub-slabs 6a / 6b / 6c

---

## ADDENDUM — 2026-05-07 — TD-197 Watchdog SECDEF Wrapper

**Origin:** RLS audit 2026-05-07 surfaced two non-canonical watchdog policies
(`qual=true`, `with_check=true`) and over-broad `arwd` grants. Deferred from
Slab 6a because canonical fix is part of Slab 4 SECDEF fleet.

### TD-197 — Watchdog read+write policies + over-broad grants

| Field | Value |
|---|---|
| Priority | P1 |
| Owner | Slab 4 (this spec) + Slab 7c (REVOKE) |
| Risk today | Defense-in-depth gap. No active exploit; no HTTP route reads watchdog. |
| Pre-flight | Confirmed: watchdog process has zero `rls.role` set calls. SECDEF is the only clean path. |

### New SECDEF function — `record_watchdog_event()`

Adds to the existing SECDEF fleet (`record_*` writers).

```sql
CREATE OR REPLACE FUNCTION record_watchdog_event(
  p_trace_id    UUID,
  p_event_type  TEXT,
  p_payload     JSONB
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  -- xact-local elevation; never leaks past statement
  PERFORM set_config('rls.role', 'platform_admin', true);

  INSERT INTO alpha_watchdog_events (trace_id, event_type, payload)
  VALUES (p_trace_id, p_event_type, p_payload);
END;
$$;

REVOKE ALL ON FUNCTION record_watchdog_event(UUID, TEXT, JSONB) FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION record_watchdog_event(UUID, TEXT, JSONB)
       TO jarvis_alpha_app, jarvis_alpha_writer;
```

### Policy changes shipped with this function

| Policy | New shape |
|---|---|
| `watchdog_events_read` | Shape B — `(current_setting('rls.role') = 'platform_admin')` |
| `watchdog_events_system_write` | DROP — superseded by SECDEF function path |

### Watchdog process refactor

| Location | Change |
|---|---|
| `brain/agents/watchdog.py` (or equivalent) | Replace raw `INSERT INTO alpha_watchdog_events` with `SELECT record_watchdog_event($1, $2, $3)` |
| Watchdog connection setup | No `rls.role` set needed — SECDEF function handles it internally |

### Slab 7c interaction

After Slab 4 ships:
- Slab 7c REVOKE INSERT/UPDATE/DELETE on `alpha_watchdog_events` from
  `jarvis_alpha_app` and `jarvis_alpha_writer`
- SELECT remains revoked (Shape B policy enforces admin-only read at policy
  layer, but DML grant is the second lock)
- Net: only path to write watchdog events is `record_watchdog_event()`

### Big-tech alignment

This pattern matches AWS CloudTrail, GCP Audit Logs, Stripe internal events,
Datadog audit log: **never grant raw DML to app roles on telemetry tables;
gate writes through a defined function with elevated privileges.**

### Acceptance criteria

- [ ] `record_watchdog_event()` deployed and EXECUTE granted to app + writer
- [ ] Watchdog process refactored to call function
- [ ] `watchdog_events_read` policy = Shape B
- [ ] `watchdog_events_system_write` policy DROPPED
- [ ] Smoke case added: non-admin role cannot SELECT from `alpha_watchdog_events`
- [ ] Smoke case added: non-admin role cannot INSERT directly into `alpha_watchdog_events` (raw DML blocked at function-only path post-7c)
- [ ] Watchdog `launchctl list` shows process healthy 24h post-deploy
