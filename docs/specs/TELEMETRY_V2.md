# Telemetry v2 — Unified Event Pipeline

**Status:** Spec locked, pending implementation
**Reviewers:** Perplexity sonar-pro (round 1 complete)
**Supersedes:** None — first formal telemetry spec for jarvis-alpha
**Date:** 2026-04-07
**Build priority:** P0 — first build target after spec lock

---

## 1. Purpose

One emit_event() primitive, one partitioned event ledger, used by every service for cost logging, latency tracking, agent observability, and approval audit. Cost logging is the first concrete consumer — `alpha_cloud_costs` is empty today because no code writes to it. This spec fixes that gap with a generalized pattern, not a one-off cost table.

---

## 2. Design Guarantees

- One `emit_event()` API used by every service (Brain, Gateway, Endpoint, Forge).
- Non-blocking emit — never adds latency to the request path.
- Billing-class events are never silently dropped.
- Billing events carry idempotency keys so retries are safe.
- Daily reconciliation against provider billing APIs catches local-vs-truth drift.
- Telemetry exporter swap from Postgres to OTel collector is a one-file change.
- Telemetry table is read-isolated by `tenant_project_id` via RLS.
- System background writers cannot read user data through the telemetry table.
- Schema evolution is additive — breaking changes increment `schema_version`.
- Every event is traceable via `trace_id` + `span_id` lineage (Dapper-style).

---

## 3. Why Not the Alternatives

| Alternative | Why rejected |
|---|---|
| Sync INSERT in router.py per cloud call | Blocks request path, tight coupling, every new sink = router code change |
| Async fire-and-forget asyncio.create_task | No batching, write amplification, no backpressure, no priority |
| Separate cost / latency / approval / agent tables | 4× operator tax, no cross-cutting queries, premature optimization at <100k events/day |
| Full OpenTelemetry Collector now | Right answer at multi-language scale, overkill for single-operator 4-node deployment |
| JSONL file + ingester | Reinventing OTel exporter, badly. Two services to maintain. |

**Chosen:** Wide-event envelope, partitioned single table, in-process priority queue, exporter as swappable interface.

---

## 4. Architecture Overview
Service code
↓
emit_event(event_family, event_name, ...)        ← non-blocking, ~5µs
↓
PriorityQueue (asyncio, in-process)
↓ (per family priority class)
TelemetryExporter interface
↓
PostgresExporter (current)  →  alpha_telemetry_events (partitioned by day)
↓
Daily rollup → alpha_telemetry_daily
↓
30-day partition drop

Future swap: PostgresExporter → OtelCollectorExporter, no application code changes.

---

## 5. Event Family Taxonomy

Every event has an `event_family` (broad category) and `event_name` (specific). Family determines drop priority and retention.

| event_family | Examples (event_name) | Drop priority | Retention |
|---|---|---|---|
| billing | cloud_call.completed, cloud_call.failed | NEVER drop | 90 days |
| governance | approval.granted, approval.denied, approval.expired | NEVER drop | 365 days |
| trace | agent.step.started, agent.step.completed, agent.step.failed | Drop under pressure | 30 days |
| ops | service.started, service.stopped, watchdog.restart_triggered | Drop under pressure | 30 days |
| debug | router.local_call, memory.evict, memory.promote | Drop first | 7 days |

Retention is per-family because billing events have legal/audit value while debug events are operational noise.

---

## 6. Schema

### 6.1 Base Table — Partitioned by event_time RANGE
```sql
CREATE TABLE alpha_telemetry_events (
    id                BIGSERIAL,
    event_time        TIMESTAMPTZ NOT NULL,
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Envelope identity
    event_family      TEXT NOT NULL,
    event_name        TEXT NOT NULL,
    schema_version    INTEGER NOT NULL DEFAULT 1,

    -- Service origin
    service           TEXT NOT NULL,
    node              TEXT NOT NULL,

    -- Tenancy / isolation
    tenant_project_id INTEGER NOT NULL,
    user_id           TEXT,
    profile_id        TEXT,

    -- Trace lineage (Dapper-style)
    run_id            UUID,
    trace_id          UUID,
    span_id           UUID,
    parent_span_id    UUID,

    -- Hot dimensions (cloud calls + most events)
    provider          TEXT,
    model             TEXT,
    status            TEXT,
    latency_ms        INTEGER,
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    cost_usd          NUMERIC(12,6),

    -- Idempotency for billing-class events
    dedupe_key        TEXT,
    reconciliation_status TEXT DEFAULT 'pending',

    -- Vendor-specific tail
    payload           JSONB NOT NULL DEFAULT '{}'::jsonb,

    PRIMARY KEY (id, event_time)
) PARTITION BY RANGE (event_time);
```

Notes:
- `event_time` = wall-clock time the event occurred (set by emitter)
- `ingested_at` = DB write time (set by Postgres default)
- Both are kept — clock skew detection, ingest lag visibility
- `tenant_project_id` is the primary RLS isolation column, NOT `profile_id`
- `profile_id` is nullable secondary attribution
- `dedupe_key` is unique per event for billing families, NULL elsewhere

### 6.2 Partition Creation
```sql
CREATE TABLE alpha_telemetry_events_2026_04_07 PARTITION OF alpha_telemetry_events
    FOR VALUES FROM ('2026-04-07') TO ('2026-04-08');
```

A nightly job creates the next 7 days of partitions and drops partitions older than 30 days. Drop is atomic and cheap — no DELETE churn.

### 6.3 Indexes

Create on each partition (or use partition template):
```sql
CREATE INDEX ON alpha_telemetry_events_YYYY_MM_DD (event_time DESC);
CREATE INDEX ON alpha_telemetry_events_YYYY_MM_DD (tenant_project_id, event_time DESC);
CREATE INDEX ON alpha_telemetry_events_YYYY_MM_DD (event_family, event_time DESC);
CREATE INDEX ON alpha_telemetry_events_YYYY_MM_DD (provider, model, event_time DESC)
    WHERE provider IS NOT NULL;
CREATE INDEX ON alpha_telemetry_events_YYYY_MM_DD (run_id, event_time DESC)
    WHERE run_id IS NOT NULL;
CREATE UNIQUE INDEX ON alpha_telemetry_events_YYYY_MM_DD (dedupe_key)
    WHERE dedupe_key IS NOT NULL;
```

The unique index on `dedupe_key` enforces idempotency — duplicate billing event inserts fail at the DB layer.

### 6.4 Daily Rollup Table
```sql
CREATE TABLE alpha_telemetry_daily (
    date              DATE NOT NULL,
    event_family      TEXT NOT NULL,
    event_name        TEXT NOT NULL,
    tenant_project_id INTEGER NOT NULL,
    provider          TEXT,
    model             TEXT,
    event_count       BIGINT NOT NULL,
    total_cost_usd    NUMERIC(12,6),
    avg_latency_ms    INTEGER,
    p95_latency_ms    INTEGER,
    p99_latency_ms    INTEGER,
    error_count       BIGINT,
    PRIMARY KEY (date, event_family, event_name, tenant_project_id, provider, model)
);
```

Populated nightly from raw events before partition drop. Survives raw retention.

---

## 7. RLS — Writer Role Pattern (Telemetry Exception)

### 7.1 Why Writer Role, Not SECURITY DEFINER

Telemetry events are infrastructure observability data, not profile-attributable user content. They follow the **writer role pattern**, not the SECURITY DEFINER pattern used for memory/chat tables.

System-wide rule:
- **Profile-bearing tables** (memory, chat, documents) → SECURITY DEFINER functions
- **System observability tables** (telemetry, watchdog, metrics) → dedicated writer role + role-based RLS

Datadog and Honeycomb don't put RLS on telemetry ingest — they put it on the read path. Same here.

### 7.2 Roles
```sql
CREATE ROLE jarvis_alpha_telemetry_writer NOLOGIN;
GRANT INSERT ON alpha_telemetry_events TO jarvis_alpha_telemetry_writer;
REVOKE SELECT ON alpha_telemetry_events FROM jarvis_alpha_telemetry_writer;
```

Writer role can INSERT but not SELECT. A compromised exporter cannot exfiltrate telemetry data.

### 7.3 RLS Policies
```sql
ALTER TABLE alpha_telemetry_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_telemetry_events FORCE ROW LEVEL SECURITY;

CREATE POLICY telemetry_insert_writer ON alpha_telemetry_events
    FOR INSERT
    WITH CHECK (
        current_setting('jarvis.role', true) = 'system_writer'
    );

CREATE POLICY telemetry_select_by_project ON alpha_telemetry_events
    FOR SELECT
    USING (
        current_setting('jarvis.role', true) = 'system_admin'
        OR tenant_project_id = current_setting('jarvis.project_id', true)::int
    );
```

Reads scoped by project. System admin (Ken from dashboard) sees all. App users see only their project's events.

### 7.4 What This Does NOT Solve

The writer role can insert any `tenant_project_id` value. App-layer must set it correctly. This is acceptable because:
- The exporter is a trusted internal service
- It runs only on Brain, not exposed to user input
- Validation happens in the emit_event() call site

If this becomes a concern, the upgrade is a SECURITY DEFINER function that validates `tenant_project_id` against the calling service's allowed projects.

---

## 8. Emit API

### 8.1 Function Signature
```python
async def emit_event(
    event_family: str,        # 'billing' | 'governance' | 'trace' | 'ops' | 'debug'
    event_name: str,           # e.g. 'cloud_call.completed'
    *,
    tenant_project_id: int,
    schema_version: int = 1,
    user_id: str | None = None,
    profile_id: str | None = None,
    run_id: UUID | None = None,
    trace_id: UUID | None = None,
    span_id: UUID | None = None,
    parent_span_id: UUID | None = None,
    provider: str | None = None,
    model: str | None = None,
    status: str | None = None,
    latency_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: Decimal | None = None,
    dedupe_key: str | None = None,
    payload: dict | None = None,
) -> None:
    """Non-blocking emit. Pushes to in-process priority queue."""
```

### 8.2 Cost Logging Call Site (router.py)

Before:
```python
result = await call_anthropic(prompt, model)
return result
```

After:
```python
start = time.monotonic()
result = await call_anthropic(prompt, model)
elapsed_ms = int((time.monotonic() - start) * 1000)

await emit_event(
    event_family='billing',
    event_name='cloud_call.completed',
    tenant_project_id=ctx.project_id,
    user_id=ctx.user_id,
    profile_id=ctx.profile_id,
    trace_id=ctx.trace_id,
    span_id=uuid4(),
    parent_span_id=ctx.parent_span_id,
    provider='anthropic',
    model=model,
    status='success',
    latency_ms=elapsed_ms,
    input_tokens=result.usage.input_tokens,
    output_tokens=result.usage.output_tokens,
    cost_usd=calc_cost(model, result.usage),
    dedupe_key=f"anthropic:{result.id}",
)
return result
```

One emit per cloud call. Non-blocking. Same pattern for Perplexity, Gemini, Ollama (with cost_usd=0).

---

## 9. Queue + Exporter Architecture

### 9.1 Priority Queue
```python
class TelemetryQueue:
    """In-process bounded priority queue with family-aware shedding."""

    NEVER_DROP = {'billing', 'governance'}
    DROP_FIRST = {'debug'}

    def __init__(self, max_size: int = 10_000):
        self._high   = asyncio.Queue(maxsize=max_size // 2)  # billing, governance
        self._normal = asyncio.Queue(maxsize=max_size // 4)  # trace, ops
        self._low    = asyncio.Queue(maxsize=max_size // 4)  # debug

    async def put(self, event: TelemetryEvent) -> None:
        target = self._classify(event.event_family)
        try:
            target.put_nowait(event)
        except asyncio.QueueFull:
            if event.event_family in self.NEVER_DROP:
                # Block briefly, then escalate to log
                await asyncio.wait_for(target.put(event), timeout=1.0)
            else:
                # Drop and log warning
                logger.warning("telemetry_queue_full",
                               event_family=event.event_family,
                               event_name=event.event_name)
```

### 9.2 Exporter Interface
```python
class TelemetryExporter(ABC):
    """Swappable backend. PostgresExporter today, OtelCollectorExporter tomorrow."""

    @abstractmethod
    async def export_batch(self, events: list[TelemetryEvent]) -> None:
        ...

    @abstractmethod
    async def shutdown(self, timeout: float = 5.0) -> None:
        ...

class PostgresExporter(TelemetryExporter):
    """Bulk INSERT via asyncpg executemany. Trusted writer role."""

    async def export_batch(self, events: list[TelemetryEvent]) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SET LOCAL jarvis.role = 'system_writer'")
                await conn.executemany(INSERT_SQL, [e.to_row() for e in events])
```

### 9.3 Background Exporter Loop
```python
async def exporter_loop(queue: TelemetryQueue, exporter: TelemetryExporter):
    flush_seconds = int(os.getenv('TELEMETRY_FLUSH_SECONDS', '5'))
    flush_batch   = int(os.getenv('TELEMETRY_FLUSH_BATCH', '100'))

    buffer = []
    last_flush = time.monotonic()

    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=flush_seconds)
            buffer.append(event)
        except asyncio.TimeoutError:
            pass

        elapsed = time.monotonic() - last_flush
        if len(buffer) >= flush_batch or (buffer and elapsed >= flush_seconds):
            await exporter.export_batch(buffer)
            buffer.clear()
            last_flush = time.monotonic()
```

### 9.4 Configurable Flush

| Env var | Default | Purpose |
|---|---|---|
| TELEMETRY_FLUSH_SECONDS | 5 | Flush cadence ceiling |
| TELEMETRY_FLUSH_BATCH | 100 | Flush batch size trigger |
| TELEMETRY_QUEUE_MAX | 10000 | In-memory queue capacity |
| TELEMETRY_EXPORTER | postgres | Exporter backend selector |
| TELEMETRY_DROP_DEBUG_OVER_PCT | 80 | Queue fullness % above which debug events drop |

---

## 10. Schema Versioning

### 10.1 Per-Event Pydantic Models
common/jarvis_common/telemetry/schemas/
├── init.py
├── billing/
│   ├── cloud_call_completed_v1.py
│   ├── cloud_call_failed_v1.py
│   └── cloud_call_completed_v2.py    # additive evolution
├── governance/
│   ├── approval_granted_v1.py
│   └── approval_denied_v1.py
├── trace/
│   ├── agent_step_started_v1.py
│   └── agent_step_completed_v1.py
└── ops/
├── service_started_v1.py
└── watchdog_restart_v1.py

Each schema is a Pydantic model. Adding a field = bump schema_version. Removing or changing a field = new file with incremented version.

### 10.2 Validation

emit_event() looks up the model by `(event_name, schema_version)` and validates the payload before queueing. Invalid events log a warning and drop — never a silent malformed write.

---

## 11. Daily Reconciliation

### 11.1 Why

Local emit is operational cache. Provider billing API is source of truth. Daily reconciliation closes the gap and catches:
- Lost events (queue overflow, crash before flush)
- Cost calculation drift (model price changes)
- Vendor-side adjustments (refunds, retries)

### 11.2 Mechanism

Nightly job per provider:
1. Fetch yesterday's usage from provider API (Anthropic, Google, Perplexity)
2. SUM local events for same date + provider + model
3. Compute delta
4. If delta > 5% or > $1: log `governance` event `cost.reconciliation.drift`
5. Update `alpha_telemetry_daily` with reconciled values
6. Mark raw events `reconciliation_status = 'reconciled'`

### 11.3 Failure Mode

Provider API down = reconciliation skipped, retry tomorrow. Local data is still queryable. No cascading failure.

---

## 12. Migration Plan

### 12.1 Live-Safe Steps

1. Create `alpha_content_tiers` (skip if exists from RLS spec)
2. Create writer role + grants
3. Create base table + first 7 days of partitions
4. Create RLS policies (FORCE RLS)
5. Deploy `jarvis_common.telemetry` package on Brain
6. Add background exporter LaunchAgent OR start in Brain lifespan
7. Add ONE emit_event call in router.py for Anthropic completion
8. Verify rows landing in Postgres
9. Add emit_event for Perplexity, Gemini, Ollama
10. Add agent step events from executor
11. Add governance events from approval gateway
12. Wire daily rollup job (pg_cron or LaunchAgent)
13. Wire reconciliation jobs per provider

Steps 1-7 are the minimum viable cost logging. Everything after is incremental.

### 12.2 Rollback Points

After step 4: drop table and role, no impact.
After step 8: comment out the one emit call, no data loss.
After step 13: full system live.

---

## 13. Test Plan

### 13.1 Coverage

1. emit_event is non-blocking (microsecond latency)
2. Billing events never dropped under queue pressure (load test 100k events)
3. Debug events dropped first when queue >80% full
4. Duplicate dedupe_key fails at DB unique constraint
5. Schema version mismatch logs warning and drops
6. Exporter graceful shutdown drains queue within 5s
7. Partition creation/drop runs nightly without errors
8. Reconciliation detects injected drift (test fixture)
9. RLS prevents cross-project read leakage
10. Writer role cannot SELECT from telemetry table

### 13.2 Test Harness

`tests/telemetry/test_emit_pipeline.py` and `tests/security/test_telemetry_rls.py`. Required to pass before any cloud call site is instrumented.

---

## 14. Open Questions for Next Round

1. **pg_cron vs LaunchAgent for nightly jobs:** Brain runs LaunchAgents already. Is pg_cron worth the install for partition management + rollup, or run as Python LaunchAgent?
2. **OTel collector graduation criteria:** What event volume / signal complexity triggers the swap from PostgresExporter to OtelCollectorExporter? Document the trigger.
3. **Forge integration:** Forge runs on Sandbox, not Brain. Does it emit directly to Brain Postgres, or to a local SQLite buffer that Brain pulls? Network reliability concern.
4. **Approval gateway dependency:** Approval decisions are governance-class events. Should approval gateway emit via this pipeline or have its own audit log? If shared, this spec must ship before approval gateway full wiring.
5. **Reconciliation API rate limits:** Anthropic billing API rate limits — daily query is fine, but what if we need hourly reconciliation later?
6. **Trace ID generation:** Where does trace_id originate? Edge middleware on Brain? Per-request UUID at the API gateway? Needs explicit owner.

---

## 15. References

- Google Dapper paper: https://research.google/pubs/dapper-a-large-scale-distributed-systems-tracing-infrastructure/
- OpenTelemetry signals: https://opentelemetry.io/docs/concepts/signals/
- Honeycomb structured events: https://docs.honeycomb.io/get-started/start-building/application/structured-events
- Stripe idempotency design: https://stripe.com/blog/idempotency
- Netflix Atlas telemetry: http://techblog.netflix.com/2014/12/introducing-atlas-netflixs-primary.html
- PostgreSQL partitioning: https://www.postgresql.org/docs/16/ddl-partitioning.html
- Perplexity sonar-pro review: 2026-04-07 (transcript in handoff)

---

*Spec locked 2026-04-07 — Cost Logging is the first build target*
