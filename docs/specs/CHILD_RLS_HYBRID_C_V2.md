# Child RLS — Hybrid C v2

**Status:** Spec locked, pending implementation
**Reviewers:** Perplexity sonar-pro (round 1 complete)
**Supersedes:** None — first formal child RLS spec for jarvis-alpha
**Date:** 2026-04-07

---

## 1. Purpose

Enforce content access controls for child profiles (Ryleigh age 8, Sloane age 5) at the PostgreSQL row level. App-layer enforcement alone is insufficient — a single bug must not be enough to expose adult content to a child profile.

This spec is the database-layer enforcement design. It complements (does not replace) app-layer content filtering.

---

## 2. Design Guarantees

These properties MUST hold after implementation:

- A child profile cannot SELECT a row with `content_tier > profile.max_tier`, regardless of app-layer behavior.
- A child profile cannot INSERT a row with `content_tier > profile.max_tier`.
- A child profile cannot enter a workspace they do not own and are not in `shared_with_profiles`.
- A child profile authenticated via Voice/Avatar surface cannot reach dashboard-only endpoints.
- A background service with no profile context cannot perform raw INSERTs to sensitive tables — it must go through a SECURITY DEFINER function.
- A request with NULL or malformed `jarvis.profile_id` or `jarvis.max_tier` session variables fails closed (sees nothing).
- HNSW vector similarity search cannot return rows above a child profile's max_tier, even as candidates that get filtered later.
- Any single bug in app code, ORM layer, or middleware cannot cause exposure — two independent failures are required.

---

## 3. Threat Model

**In scope:**
- Bug in app code that forgets to filter by profile_id
- Prompt injection causing an agent to bypass app-layer filters
- Misclassified row inserted under an adult session, later read by a child
- Shared workspaces (Family Vault) where two profiles legitimately access the same container
- Cached credentials from earlier adult session reused by a later child request
- HNSW candidate generation including adult rows that get filtered post-rank
- Background service writes that bypass user context entirely

**Out of scope (handled elsewhere):**
- Network-layer authentication (handled by JWT middleware)
- Surface-level routing (handled by FastAPI middleware)
- Content classification accuracy (handled by app-layer classifier — separate spec)
- Audit log analysis for prompt injection detection (separate spec)

---

## 4. Profile Model

### 4.1 Schema
```sql
CREATE TABLE alpha_profiles (
    profile_id        TEXT PRIMARY KEY,
    display_name      TEXT NOT NULL,
    max_tier          SMALLINT NOT NULL REFERENCES alpha_content_tiers(tier_id),
    allowed_surfaces  TEXT[] NOT NULL,
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_profiles_max_tier ON alpha_profiles (max_tier);
```

### 4.2 Initial Seed
```sql
INSERT INTO alpha_profiles (profile_id, display_name, max_tier, allowed_surfaces) VALUES
  ('ken',     'Ken',     4, ARRAY['dashboard','voice','avatar','api','agent']),
  ('ryleigh', 'Ryleigh', 1, ARRAY['voice','avatar']),
  ('sloane',  'Sloane',  1, ARRAY['voice','avatar']);
```

Notes:
- `max_tier=4` = sensitive_adult (full access)
- `max_tier=1` = kids (kids-tier and below)
- Children have NO dashboard access at the surface level

---

## 5. Content Tier Model

### 5.1 Lookup Table
```sql
CREATE TABLE alpha_content_tiers (
    tier_id   SMALLINT PRIMARY KEY,
    tier_name TEXT UNIQUE NOT NULL,
    description TEXT
);

INSERT INTO alpha_content_tiers VALUES
  (0, 'public',          'No restrictions, viewable by anyone'),
  (1, 'kids',            'Age-appropriate for ages 5+'),
  (2, 'teen',            'Age-appropriate for ages 13+'),
  (3, 'adult',           'Adult content, default for adult-authored writes'),
  (4, 'sensitive_adult', 'Highly sensitive — requires explicit elevation');
```

### 5.2 Tier Storage on Content Tables

Every content-bearing row gets a SMALLINT `content_tier` column with a foreign key to `alpha_content_tiers`. Stored as SMALLINT, not TEXT — direct integer comparison in policies, no function inlining concerns.
```sql
ALTER TABLE alpha_chat_messages
  ADD COLUMN content_tier SMALLINT NOT NULL DEFAULT 3
  REFERENCES alpha_content_tiers(tier_id);

CREATE INDEX idx_chat_messages_tier ON alpha_chat_messages (content_tier);
```

Default = 3 (adult). Adult-authored writes default-classify as adult. Promotion to public/kids/teen requires explicit classification.

---

## 6. Workspace Ownership

### 6.1 Schema Changes
```sql
ALTER TABLE alpha_workspaces
  ADD COLUMN owner_profile_id TEXT NOT NULL REFERENCES alpha_profiles(profile_id),
  ADD COLUMN shared_with_profiles TEXT[] NOT NULL DEFAULT '{}';

CREATE INDEX idx_workspaces_owner ON alpha_workspaces (owner_profile_id);
CREATE INDEX idx_workspaces_shared ON alpha_workspaces USING GIN (shared_with_profiles);
```

### 6.2 Visibility Rule

A workspace is accessible to a profile if:
profile_id = owner_profile_id
OR profile_id = ANY(shared_with_profiles)

No per-profile per-workspace tier overrides. Tier is enforced independently at the row level. If a workspace contains content too sensitive for one of its members, that content stays hidden — the workspace itself does not change.

---

## 7. Partitioned Memory — HNSW Hard Boundary

### 7.1 Why Partitioning

HNSW indexes generate candidates from the index BEFORE the WHERE clause filters. RLS-as-WHERE is therefore not a security boundary for vector search — adult rows in the candidate pool can dominate, leaving children with empty result sets at best, and creating side-channel inference at worst.

Solution: partition `alpha_conversation_memory` by `content_tier`. Each partition gets its own HNSW index. Queries use partition pruning so only allowed partitions are touched.

### 7.2 Schema
```sql
CREATE TABLE alpha_conversation_memory (
    id              BIGSERIAL,
    workspace_id    INTEGER NOT NULL,
    profile_id      TEXT NOT NULL,
    content_tier    SMALLINT NOT NULL REFERENCES alpha_content_tiers(tier_id),
    memory_type     TEXT NOT NULL,
    content         TEXT NOT NULL,
    embedding       VECTOR(768),
    created_at      TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id, content_tier)
) PARTITION BY LIST (content_tier);

CREATE TABLE alpha_conversation_memory_public  PARTITION OF alpha_conversation_memory FOR VALUES IN (0);
CREATE TABLE alpha_conversation_memory_kids    PARTITION OF alpha_conversation_memory FOR VALUES IN (1);
CREATE TABLE alpha_conversation_memory_teen    PARTITION OF alpha_conversation_memory FOR VALUES IN (2);
CREATE TABLE alpha_conversation_memory_adult   PARTITION OF alpha_conversation_memory FOR VALUES IN (3);
CREATE TABLE alpha_conversation_memory_sensitive PARTITION OF alpha_conversation_memory FOR VALUES IN (4);

CREATE INDEX idx_mem_public_hnsw   ON alpha_conversation_memory_public   USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_mem_kids_hnsw     ON alpha_conversation_memory_kids     USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_mem_teen_hnsw     ON alpha_conversation_memory_teen     USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_mem_adult_hnsw    ON alpha_conversation_memory_adult    USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_mem_sensitive_hnsw ON alpha_conversation_memory_sensitive USING hnsw (embedding vector_cosine_ops);
```

### 7.3 Query Pattern

App code constructs vector search with explicit tier bound:
```sql
SELECT * FROM alpha_conversation_memory
WHERE content_tier <= current_setting('jarvis.max_tier')::smallint
  AND workspace_id = ANY(...)
ORDER BY embedding <=> $1
LIMIT 10;
```

The planner uses partition pruning on `content_tier` first, then runs HNSW only on allowed partitions. RLS still enforces independently as a second check.

---

## 8. SECURITY DEFINER Function Pattern (System-Wide Standard)

### 8.1 Principle

**No background service writes raw SQL to sensitive tables.** All background writes go through narrow SECURITY DEFINER functions that validate inputs, set context internally, and expose only the specific operation needed.

This applies to: Buddy agent, Watchdog, Executor, Telemetry exporter, Forge, and any future autonomous service.

### 8.2 Service Roles
```sql
CREATE ROLE jarvis_alpha_buddy NOLOGIN;
CREATE ROLE jarvis_alpha_watchdog NOLOGIN;
CREATE ROLE jarvis_alpha_executor NOLOGIN;
CREATE ROLE jarvis_alpha_telemetry NOLOGIN;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM jarvis_alpha_buddy;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM jarvis_alpha_watchdog;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM jarvis_alpha_executor;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM jarvis_alpha_telemetry;
```

Each background service authenticates as its own role. None can perform raw table writes.

### 8.3 Function Pattern
```sql
CREATE OR REPLACE FUNCTION promote_memory(
    p_source_id BIGINT,
    p_target_tier SMALLINT
) RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_source RECORD;
    v_new_id BIGINT;
BEGIN
    IF current_user != 'jarvis_alpha_buddy' THEN
        RAISE EXCEPTION 'promote_memory may only be called by buddy role';
    END IF;

    SELECT * INTO v_source FROM alpha_conversation_memory WHERE id = p_source_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'source row % not found', p_source_id;
    END IF;

    IF p_target_tier > v_source.content_tier THEN
        RAISE EXCEPTION 'cannot promote to higher tier than source';
    END IF;

    INSERT INTO alpha_conversation_memory (
        workspace_id, profile_id, content_tier, memory_type, content, embedding
    ) VALUES (
        v_source.workspace_id, v_source.profile_id, p_target_tier,
        'semantic', v_source.content, v_source.embedding
    ) RETURNING id INTO v_new_id;

    RETURN v_new_id;
END;
$$;

REVOKE ALL ON FUNCTION promote_memory FROM PUBLIC;
GRANT EXECUTE ON FUNCTION promote_memory TO jarvis_alpha_buddy;
```

### 8.4 Functions Required for Initial Rollout

| Function | Service | Purpose |
|---|---|---|
| promote_memory | buddy | Episodic → semantic promotion |
| evict_working_memory | buddy | Delete expired working memory |
| record_telemetry_batch | telemetry | Bulk insert events |
| record_watchdog_event | watchdog | State change events |
| record_step_result | executor | TaskGraph step completion |

---

## 9. RLS Policies

### 9.1 Force RLS
```sql
ALTER TABLE alpha_workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_workspaces FORCE ROW LEVEL SECURITY;

ALTER TABLE alpha_conversation_memory ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_conversation_memory FORCE ROW LEVEL SECURITY;

ALTER TABLE alpha_chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_chat_messages FORCE ROW LEVEL SECURITY;
```

`FORCE` ensures the policy applies even to the table owner role. Without it, owner role bypasses policies silently.

### 9.2 Fail-Closed Helper
```sql
CREATE OR REPLACE FUNCTION current_profile_id() RETURNS TEXT
LANGUAGE plpgsql STABLE AS $$
BEGIN
    RETURN current_setting('jarvis.profile_id', true);
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION current_max_tier() RETURNS SMALLINT
LANGUAGE plpgsql STABLE AS $$
BEGIN
    RETURN current_setting('jarvis.max_tier', true)::smallint;
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END;
$$;
```

NULL returns from these functions cause policies to deny by default — `NULL <= anything` is NULL, not TRUE.

### 9.3 Workspace Policy
```sql
CREATE POLICY workspace_access ON alpha_workspaces
    FOR ALL
    USING (
        current_profile_id() IS NOT NULL
        AND (
            owner_profile_id = current_profile_id()
            OR current_profile_id() = ANY(shared_with_profiles)
        )
    )
    WITH CHECK (
        current_profile_id() IS NOT NULL
        AND owner_profile_id = current_profile_id()
    );
```

Reads: owner or shared. Writes: owner only.

### 9.4 Conversation Memory Policy
```sql
CREATE POLICY memory_isolation ON alpha_conversation_memory
    FOR ALL
    USING (
        current_profile_id() IS NOT NULL
        AND current_max_tier() IS NOT NULL
        AND content_tier <= current_max_tier()
        AND workspace_id IN (
            SELECT id FROM alpha_workspaces
            WHERE owner_profile_id = current_profile_id()
               OR current_profile_id() = ANY(shared_with_profiles)
        )
    )
    WITH CHECK (
        current_profile_id() IS NOT NULL
        AND current_max_tier() IS NOT NULL
        AND content_tier <= current_max_tier()
        AND workspace_id IN (
            SELECT id FROM alpha_workspaces
            WHERE owner_profile_id = current_profile_id()
        )
    );
```

Two independent checks: workspace AND tier. Both must pass.

---

## 10. Session Context Propagation

### 10.1 Per-Request Setup

Every request handler sets four session variables:
```sql
SET LOCAL jarvis.profile_id = 'ryleigh';
SET LOCAL jarvis.max_tier   = '1';
SET LOCAL jarvis.surface    = 'voice';
SET LOCAL jarvis.trace_id   = '...';
```

Wrapped in `conn.transaction()` per the asyncpg RLS pattern from Session 03.

### 10.2 Async Boundary Propagation

Python `contextvars` carries the auth context across `await` boundaries:
```python
from contextvars import ContextVar

profile_ctx: ContextVar[ProfileContext] = ContextVar('profile_ctx')

@dataclass(frozen=True)
class ProfileContext:
    profile_id: str
    max_tier: int
    surface: str
    trace_id: str
```

TaskGraph step launches inherit the parent's `ProfileContext` via explicit envelope:
```python
async def run_step(step, ctx: ProfileContext):
    token = profile_ctx.set(ctx)
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await set_profile_context(conn, ctx)
                await step.execute()
    finally:
        profile_ctx.reset(token)
```

Background services (Buddy, Watchdog) do NOT inherit user context — they use their own service role and SECURITY DEFINER functions per Section 8.

---

## 11. Migration Plan

### 11.1 Live-Safe Steps

1. Create `alpha_content_tiers` lookup table — no impact
2. Create `alpha_profiles` table + seed Ken/Ryleigh/Sloane — no impact
3. Add `content_tier`, `owner_profile_id`, `shared_with_profiles` columns to existing tables with defaults — fast metadata-only operation in PG16
4. Backfill `owner_profile_id = 'ken'` on all existing workspaces — single UPDATE
5. Backfill `content_tier = 3` on all existing rows — single UPDATE per table
6. Create new partitioned `alpha_conversation_memory_v2` alongside existing
7. Dual-write window — app writes to both, reads from old
8. Backfill copy from old → new
9. Cutover reads to new
10. Drop old `alpha_conversation_memory`
11. Rename `_v2` to `alpha_conversation_memory`
12. ENABLE + FORCE RLS, create policies — last step, atomic flip

Steps 1–5 are reversible. Steps 6–11 are the risk window. Step 12 is the security flip.

### 11.2 Rollback Points

After step 5: drop new columns, no data loss.
After step 9: keep old table, swap reads back.
After step 12: ALTER TABLE NO FORCE ROW LEVEL SECURITY, drop policies.

---

## 12. Test Plan

### 12.1 Negative Space Coverage

For each child profile, verify it CANNOT:

1. SELECT a row with `content_tier > 1` from any table
2. INSERT a row with `content_tier > 1`
3. Access a workspace not owned by it and not in its `shared_with_profiles`
4. Reach a dashboard endpoint via API call (surface check)
5. Get adult-tier rows in HNSW vector search candidates (verify partition pruning in EXPLAIN)
6. Bypass the policy by setting `jarvis.profile_id` to NULL (fail closed)
7. Bypass the policy by setting `jarvis.max_tier` to a higher value than profile.max_tier (app middleware enforces ceiling)
8. Read promoted memory above its tier (SECURITY DEFINER promote_memory enforces cap)
9. Trigger a TaskGraph step that runs as a different profile
10. See denied-row counts in app responses (no side channel)

### 12.2 Test Harness

`tests/security/test_child_rls.py` runs all 10 negative tests against a temporary Postgres schema with seeded fixtures. Required to pass before any merge to main.

---

## 13. Open Questions for Next Round

1. **Denied-read audit:** App-layer count-delta pattern — where does it live? New middleware or per-route?
2. **Surface-as-policy:** Should any RLS policy reference `jarvis.surface` directly, or stay middleware-only?
3. **Family Vault:** When does the Vault module ship, and does it need its own partition scheme?
4. **Promotion path for child-authored content:** If Ryleigh writes something kids-tier, can Ken promote it to teen later? Through what function?
5. **Profile rotation:** When Ryleigh turns 13, max_tier needs to change. Do existing rows get re-tier'd or stay at their original classification?
6. **Vector embedding leakage:** Even with partitioned indexes, two identical strings in different tiers produce identical vectors. Side channel?

---

## 14. References

- PostgreSQL 16 RLS docs: https://www.postgresql.org/docs/16/ddl-rowsecurity.html
- pgvector HNSW planner behavior: https://github.com/pgvector/pgvector/issues/862
- Epic MyChart proxy access model (Section 2 threat model precedent)
- Perplexity sonar-pro review: 2026-04-07 (transcript in handoff)

---

*Spec locked 2026-04-07 — implementation pending cost logging completion*
