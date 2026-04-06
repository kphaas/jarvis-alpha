# JARVIS Alpha — Database Contracts

Every table's schema, constraints, and correct INSERT patterns.
Check this BEFORE writing any INSERT/UPDATE statement.

Updated: April 6, 2026 · Database: jarvis_alpha · Brain Postgres 16

---

## Quick Reference

```bash
# Verify any table
/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -U jarvisbrain -d jarvis_alpha -c "\d tablename"
```

---

## 1. alpha_approval_queue

Pending T4/T5 actions awaiting human approval.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| id | uuid | NOT NULL | gen_random_uuid() | PK — use RETURNING id |
| action_class | text[] | NOT NULL | | Python list, NOT comma string |
| risk_tier | text | NOT NULL | | CHECK: T1–T5 |
| actor_sub | text | NOT NULL | | JWT sub claim |
| actor_type | text | NOT NULL | | CHECK: user, service, agent |
| actor_node | text | nullable | | |
| description | text | NOT NULL | | "METHOD /path" |
| parameters_hash | text | NOT NULL | | sha256 of request body |
| parameters_preview | text | nullable | | |
| nonce | text | NOT NULL | | uuid4().hex, UNIQUE |
| notification_sent | boolean | NOT NULL | false | |
| status | text | NOT NULL | 'pending' | CHECK: pending, approved, denied, expired, executed |
| requested_at | timestamptz | NOT NULL | now() | NOT "created_at" |
| decided_by | text | nullable | | |
| decided_at | timestamptz | nullable | | |
| executed_at | timestamptz | nullable | | |
| expires_at | timestamptz | NOT NULL | | Must provide explicitly |
| overnight | boolean | NOT NULL | false | |

**Key indexes:**
- `idx_approval_pending_dedup` — UNIQUE(actor_sub, parameters_hash) WHERE status='pending'
- Catch `UniqueViolationError` on INSERT

**Correct INSERT:**
```python
from asyncpg.exceptions import UniqueViolationError

nonce = uuid4().hex
description = f"{method} {path}"

try:
    async with conn.transaction():
        queue_id = await conn.fetchval(
            """INSERT INTO alpha_approval_queue
               (action_class, risk_tier, actor_sub, actor_type, description,
                parameters_hash, nonce, status, requested_at, expires_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', NOW(),
                       NOW() + INTERVAL '10 minutes')
               RETURNING id""",
            action_classes,   # Python list → text[]
            tier,
            actor_sub,
            actor_type,
            description,
            parameters_hash,
            nonce,
        )
except UniqueViolationError:
    existing = await conn.fetchval(
        "SELECT id FROM alpha_approval_queue WHERE actor_sub=$1 AND parameters_hash=$2 AND status='pending'",
        actor_sub, parameters_hash,
    )
```

**Status transitions:**
- pending → approved (via decide endpoint, sets decided_by + decided_at + new expires_at)
- pending → denied (via decide endpoint, sets decided_by + decided_at)
- approved → executed (via middleware on retry, sets executed_at)
- pending → expired (via cleanup job, not yet built)

---

## 2. alpha_approval_audit

Immutable audit trail. DELETE and UPDATE revoked from jarvis_alpha_app.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| id | uuid | NOT NULL | gen_random_uuid() | PK |
| approval_id | uuid | nullable | | FK → alpha_approval_queue(id) |
| action_class | text[] | NOT NULL | | Python list |
| risk_tier | text | NOT NULL | | |
| actor_sub | text | NOT NULL | | |
| actor_type | text | NOT NULL | | |
| description | text | NOT NULL | | |
| parameters_hash | text | NOT NULL | | |
| nonce | text | NOT NULL | | uuid4().hex |
| decision | text | NOT NULL | | CHECK: approved, denied, expired, auto |
| decided_by | text | nullable | | |
| decided_at | timestamptz | NOT NULL | now() | |
| overnight | boolean | NOT NULL | false | |

**Correct INSERT:**
```python
nonce = uuid4().hex
await conn.execute(
    """INSERT INTO alpha_approval_audit
       (approval_id, action_class, risk_tier, actor_sub, actor_type,
        description, parameters_hash, nonce, decision, decided_by, overnight)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
    queue_uuid,        # uuid from queue RETURNING id
    action_classes,    # Python list
    tier,
    actor_sub,
    actor_type,
    description,
    parameters_hash,
    nonce,
    "auto",            # or "approved" / "denied"
    actor_sub,
    False,
)
```

---

## 3. alpha_buddy_events

Buddy agent event feed — polled by UI.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| id | uuid | NOT NULL | gen_random_uuid() | PK |
| user_id | text | nullable | | |
| event_type | text | NOT NULL | | CHECK: alert, reminder, suggestion, system |
| title | text | NOT NULL | | |
| body | text | nullable | | |
| priority | integer | NOT NULL | 2 | 1=normal, 2=high |
| read | boolean | NOT NULL | false | |
| created_at | timestamptz | NOT NULL | now() | |
| source | text | nullable | | Subsystem identifier |
| payload | jsonb | nullable | | **Must use json.dumps()** |

**Correct INSERT:**
```python
import json
await conn.execute(
    """INSERT INTO alpha_buddy_events
       (event_type, title, body, priority, source, payload)
       VALUES ('alert', $1, $2, $3, $4, $5)""",
    title,
    body,
    2,                              # priority
    "approval_gateway",             # source
    json.dumps({"key": "value"}),   # JSONB — must be string!
)
```

**Common mistake:** Passing a Python dict for payload → `DataError: expected str, got dict`

---

## 4. alpha_conversation_memory

3-tier memory with vector embeddings.

| Column | Type | Key Notes |
|---|---|---|
| id | uuid | PK, gen_random_uuid() |
| user_id | text | NOT NULL |
| memory_type | text | CHECK: working, episodic, semantic |
| content | text | NOT NULL |
| embedding | vector(768) | 768-dim, HNSW index |
| source | text | CHECK: live, thread_extract, overnight, ingest |
| created_at | timestamptz | |
| expires_at | timestamptz | nullable — working=24h, episodic=30d, semantic=permanent |
| score | float | nullable — Buddy scores episodic for promotion |

**RLS:** `alpha_memory_isolation` policy active.

---

## 5. chat_threads

| Column | Type | Key Notes |
|---|---|---|
| id | uuid | PK |
| user_id | text | NOT NULL |
| title | text | default 'New conversation' |
| mode | text | CHECK: realtime, overnight |
| model_used | text | nullable |
| project_id | integer | nullable FK |
| owner_profile | text | FK → alpha_profiles(id) |
| content_rating | text | CHECK: all_ages, age_8_plus, teen, adult |
| archived_at | timestamptz | nullable — soft delete |

**RLS:** `chat_threads_isolation` (user_id) + `child_thread_isolation` (owner_profile)

---

## 6. chat_messages

| Column | Type | Key Notes |
|---|---|---|
| id | uuid | PK |
| thread_id | uuid | FK → chat_threads(id) ON DELETE CASCADE |
| role | text | CHECK: user, assistant, system |
| content | text | NOT NULL |
| model_used | text | nullable |
| council_detail | jsonb | nullable — **use json.dumps()** |
| content_rating | text | CHECK: all_ages, age_8_plus, teen, adult |

**RLS:** Three policies — user isolation, child isolation, child content rating filter.

---

## 7. alpha_task_graphs

TaskGraph DAG — the execution unit.

| Column | Type | Key Notes |
|---|---|---|
| id | uuid | PK |
| user_id | text | NOT NULL |
| title | text | NOT NULL |
| graph_type | text | CHECK: overnight, user_request, agent, maintenance |
| status | text | CHECK: pending, running, completed, failed, stuck, needs_approval, cancelled |
| priority | integer | CHECK: 1–10 |
| user_type | text | CHECK: adult, child |
| content_tier | text | CHECK: unrestricted, filtered, child_safe |
| metadata | jsonb | default '{}' — **use json.dumps()** |
| checkpoint | jsonb | default '{}' — **use json.dumps()** |
| owner_profile | text | FK → alpha_profiles(id) |
| source | text | CHECK: manual, agent |

**Constraint:** `chk_child_content_tier` — child users MUST have content_tier='child_safe'

**RLS:** `task_graph_isolation` + `child_task_isolation` policies active.

---

## 8. alpha_task_steps

| Column | Type | Key Notes |
|---|---|---|
| id | uuid | PK |
| graph_id | uuid | FK → alpha_task_graphs(id) ON DELETE CASCADE |
| step_name | text | NOT NULL |
| step_type | text | CHECK varies |
| status | text | |
| input | jsonb | **use json.dumps()** |
| output | jsonb | **use json.dumps()** |

---

## 9. alpha_profiles

User/child profiles for auth.

| Column | Type | Key Notes |
|---|---|---|
| id | text | PK (e.g. 'ken', 'ryleigh', 'sloane') |
| display_name | text | NOT NULL |
| role | text | CHECK: admin, child |
| child_age | integer | nullable |
| max_rating | text | CHECK: all_ages, age_8_plus, teen, adult |
| pin_hash | text | NOT NULL — bcrypt or PLACEHOLDER |
| active | boolean | default true |

---

## 10. alpha_projects

| Column | Type | Key Notes |
|---|---|---|
| id | integer | PK, serial |
| name | text | NOT NULL |
| project_type | text | CHECK: forge, personal, problem |
| repo_slug | text | nullable |

---

## 11. alpha_node_registry

| Column | Type | Key Notes |
|---|---|---|
| id | integer | PK, serial |
| name | text | NOT NULL, UNIQUE |
| display_name | text | NOT NULL |
| role | text | NOT NULL |
| node_type | text | CHECK: service, storage, dev, network, mobile |
| tailscale_ip | text | nullable |
| health_endpoint | text | nullable |
| is_active | boolean | default true |

---

## Universal Rules

1. **JSONB columns** → always `json.dumps()` before passing to asyncpg
2. **TEXT[] columns** → pass Python list, never comma-joined string
3. **UUID columns** → accept Python uuid.UUID or string UUID, never prefixed strings
4. **CHECK constraints** → violation = 500, not a helpful error. Verify values before INSERT
5. **NOT NULL columns** → omitting = 500. Count your parameters
6. **Always verify** → run `\d tablename` before writing any INSERT

---

*DB Contracts V1 · April 6 2026 · jarvis_alpha on Brain Postgres 16*
