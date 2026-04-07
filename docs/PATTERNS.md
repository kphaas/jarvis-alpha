# JARVIS Alpha — Engineering Patterns & Gotchas

Reference for anyone writing code against jarvis-alpha. Read before your first PR.
Updated: April 6, 2026

---

## 1. asyncpg + Postgres

### JSONB columns → always `json.dumps()`

asyncpg expects a **string** for JSONB columns, not a Python dict.

```python
# WRONG — raises DataError: expected str, got dict
await conn.execute(
    "INSERT INTO my_table (payload) VALUES ($1)",
    {"key": "value"},
)

# RIGHT
import json
await conn.execute(
    "INSERT INTO my_table (payload) VALUES ($1)",
    json.dumps({"key": "value"}),
)
```

### TEXT[] columns → pass a Python list

asyncpg handles `list → text[]` automatically. Do NOT comma-join.

```python
# WRONG — inserts a single string "read,write"
await conn.execute(
    "INSERT INTO my_table (action_class) VALUES ($1)",
    "read,write",
)

# RIGHT — inserts array ['read', 'write']
await conn.execute(
    "INSERT INTO my_table (action_class) VALUES ($1)",
    ["read", "write"],
)
```

### Always verify columns before writing INSERTs

Run `\d tablename` on Brain before writing any INSERT statement.
Tables have CHECK constraints, NOT NULLs, and FK references that
will cause silent 500s if violated.

```bash
/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -U jarvisbrain -d jarvis_alpha -c "\d alpha_approval_queue"
```

### Unique constraint violations → handle gracefully

Partial unique indexes (like `idx_approval_pending_dedup`) will throw
`asyncpg.exceptions.UniqueViolationError`. Always catch and handle
instead of letting it bubble as a 500.

```python
from asyncpg.exceptions import UniqueViolationError

try:
    await conn.execute("INSERT ...")
except UniqueViolationError:
    # Return existing row instead of failing
    existing = await conn.fetchval("SELECT id FROM ... WHERE ...")
```

### UUID columns

Postgres UUID columns accept Python `uuid.UUID` or string UUIDs,
but NOT prefixed strings like `"apq_abc123"`. If you want a prefix,
store as TEXT instead.

---

## 2. FastAPI Middleware

### BaseHTTPMiddleware cannot replace the request body

`BaseHTTPMiddleware.call_next()` uses its own internal `receive`
callable. If you consume the body with `await request.receive()` or
`await request.body()`, then call `call_next()`, the route handler
will hang forever waiting for body data.

```python
# WRONG — route handler hangs
async def dispatch(self, request, call_next):
    body = await request.body()  # consumes the stream
    response = await call_next(request)  # handler never gets body
    return response

# RIGHT — only read body when you won't call call_next
async def dispatch(self, request, call_next):
    tier = classify(request)
    if tier in ("T1", "T2", "T3"):
        return await call_next(request)  # pass through untouched
    # T4/T5: safe to read body because we return JSON, not call_next
    body = await request.body()
    return JSONResponse(status_code=403, content={...})
```

### Middleware stack order matters (LIFO)

Starlette adds middleware in LIFO order — last added runs first.

```python
app.add_middleware(RateLimitMiddleware)    # runs 4th
app.add_middleware(ApprovalMiddleware)     # runs 3rd
app.add_middleware(RLSMiddleware)          # runs 2nd
app.add_middleware(AuthMiddleware)         # runs 1st
app.add_middleware(CORSMiddleware)         # runs before Auth
```

Execution order: **CORS → Auth → RLS → Approval → RateLimit → handler**

---

## 3. macOS / LaunchAgent

### Always unload LaunchAgent before killing processes

If you `kill -9` a process managed by a LaunchAgent, macOS will
immediately respawn it. Then your new process can't bind the port.

```bash
# WRONG — old process respawns before new one starts
kill -9 $(lsof -ti :8186)
bash start.sh

# RIGHT — stop respawning first
launchctl unload ~/Library/LaunchAgents/com.jarvis.alpha.brain.plist
sleep 1
lsof -ti :8186 | xargs kill -9 2>/dev/null
sleep 2
launchctl load ~/Library/LaunchAgents/com.jarvis.alpha.brain.plist
```

### Always purge `__pycache__` after .py edits

Python caches bytecode in `__pycache__/` dirs. After editing `.py`
files (especially via git pull), stale bytecode can cause the old
code to run even with the new source on disk.

```bash
find ~/jarvis-alpha/brain -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
```

The `jarvisalpha_pull.sh` script does this automatically now.

### macOS Keychain fails in headless sessions

`security` commands return error -25308 when no GUI session exists.
Never use Keychain for secrets in LaunchAgent services.

All secrets go in `~/jarvis/.secrets` (chmod 600), loaded via
`get_secret()` from `jarvis_common.secrets`.

---

## 4. Secrets & Config

### Secret file locations differ by node

| Node | Path |
|---|---|
| Brain | `~/jarvis/.secrets` |
| Gateway | `~/jarvis/.secrets` |
| Endpoint | `~/jarvis/.secrets` |
| Sandbox | `~/.secrets` (home dir — NOT `~/jarvis/.secrets`) |

### Never hardcode anything

All secrets via `get_secret()`. All IPs/hostnames via `node_addresses.py`.
No hardcoded IPs, hostnames, tokens, certs, or keys in source.

---

## 5. Inter-Node Communication

### httpx fails against Tailscale TLS

Python httpx has TLS handshake issues with Tailscale certs on
modern Python. Established workaround: `curl` subprocess +
`asyncio.to_thread`.

```python
import asyncio
import subprocess

async def call_node(url, payload):
    def _curl():
        result = subprocess.run(
            ["curl", "-sk", "-X", "POST", url,
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload)],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout
    return await asyncio.to_thread(_curl)
```

### Gateway is sole internet egress

Brain NEVER calls external APIs directly. All cloud calls route
through Gateway. This includes future Pushover notifications.

```
Brain → Gateway → Pushover API
Brain → Gateway → Claude API
Brain → Gateway → Perplexity API
```

---

## 6. Route Classification (Approval Gateway)

### Every new route MUST be classified

Unclassified routes default to T5 (deny by default). The UI will
show 403 errors for any unclassified route.

Add new routes to `brain/middleware/approval_classes.py`
`ROUTE_CLASSIFICATION` dict:

```python
ROUTE_CLASSIFICATION = {
    "GET /v1/my/new/route": ["read"],           # T1
    "POST /v1/my/new/route": ["write"],          # T2
    "DELETE /v1/my/thing/{id}": ["destructive"],  # T5
}
```

### Startup audit catches gaps

Brain logs `ROUTE_AUDIT` on every startup. If any routes are
unclassified, you'll see a WARNING with the list.

```bash
grep "ROUTE_AUDIT" ~/jarvis-alpha/logs/alpha_brain.log | tail -1
```

### Approval routes must not be T4/T5

The approve/deny endpoints themselves cannot require approval —
that creates an infinite loop. They use `approval_decide` → T2.

---

## 7. Deploy & Git

### Commit flow

```bash
# Air only
bash ~/jarvis-alpha/scripts/jarvisalpha_commit.sh "message"
# Auto: lint, build UI, push, pull Sandbox
# Manual: pull Brain/Gateway/Endpoint
```

### Pull = auto restart on Brain

```bash
# On Brain/Gateway/Endpoint
bash ~/jarvis-alpha/scripts/jarvisalpha_pull.sh
# Auto: pull, purge __pycache__, restart LaunchAgent, health check
```

### YAML — never patch, always rewrite

Never use `sed` or `cat >>` to modify YAML files. Always rewrite
the full file with a heredoc when structure changes.

### Command blocks — node label above, no comments inside

```
▶ BRAIN —
command here
```

Never put `#` comments inside terminal command blocks.

---

## 8. Testing

### Check for stale processes before testing

```bash
lsof -i :8186  # Brain
lsof -i :8282  # Gateway
lsof -i :4100  # Endpoint UI
```

### Smoke test after every deploy

```bash
curl -sk https://jarvis-brain.tail40ed36.ts.net:8186/health | python3 -m json.tool
```

### Clean test data between runs

Approval queue dedup index prevents duplicate pending requests.
Clear between test runs:

```bash
/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -U jarvisbrain -d jarvis_alpha \
  -c "DELETE FROM alpha_approval_audit; DELETE FROM alpha_approval_queue;"
```

---

## 9. Buddy Events

### Event types (CHECK constraint)

Only these values are valid: `'alert'`, `'reminder'`, `'suggestion'`, `'system'`

### Required columns

```sql
INSERT INTO alpha_buddy_events
    (event_type, title, body, priority, source, payload)
VALUES ('alert', $1, $2, $3, 'my_service', $4)
```

- `priority`: 1 (normal), 2 (high)
- `source`: identifier for the subsystem (e.g. `'approval_gateway'`, `'token_rotation'`)
- `payload`: JSONB — must use `json.dumps()` (see Pattern #1)

---

## 10. Common Debugging

### Import errors after pull

Usually stale `__pycache__`. Purge and restart:

```bash
find ~/jarvis-alpha/brain -type d -name __pycache__ -exec rm -rf {} +
```

### 500 on INSERT

90% of the time: column mismatch. Run `\d tablename` and compare
your INSERT columns to the actual schema.

### Route returns 403 unexpectedly

Check if the route is classified:

```bash
grep "my/route" ~/jarvis-alpha/brain/middleware/approval_classes.py
```

If missing, add it and check `ROUTE_AUDIT` on next restart.

### Empty response from curl

Usually a 500 with empty body. Add `-o /dev/null -w "%{http_code}"`
to see the status code, then check error logs:

```bash
tail -20 ~/jarvis-alpha/logs/alpha_brain_error.log
tail -20 ~/jarvis-alpha/logs/alpha_brain.log | grep ERROR
```

---

*Updated after Approval Gateway Phase 2 session — April 6, 2026*

---

## 11. Cursor Discipline

### str_replace can be a no-op — always verify with git diff

Cursor's str_replace tool returns success when the file content is already in the target state. The replace happens, but it changes nothing. This is dangerous: verification gates downstream of the edit will pass (because the file IS in the target state — it just was already that way), and you proceed thinking your edit landed when it didn't.

This bit us on 2026-04-07 when an F-137 fix was applied to a file that already contained the fix from an earlier commit. All five verification gates passed. The file was correct. But git status was clean — no edit had occurred. We only noticed during deploy investigation 30 minutes later.

**Rule:** After EVERY str_replace, run `git diff path/to/file`. If diff is empty, STOP and investigate before proceeding. Either:

1. The file was already in the target state (good — but you need to know this, because it changes what "deploy" means)
2. The str_replace silently failed (bad — fix the prompt and retry)

```bash
# After every str_replace
git diff path/to/edited/file

# If empty, do not proceed. Investigate first.
```

### Verify file writes with size + line count + grep

Cursor sometimes writes verification phrases as literal file content. After every file create or write, run all three:

```bash
ls -la path/to/file        # exists, reasonable size
wc -l path/to/file         # line count matches expectation
grep "expected_string" path/to/file  # critical content present
```

### YAML files — rewrite, never patch

Never use sed, `cat >>`, or incremental str_replace on YAML files when the structure is changing. Always rewrite the full file with a heredoc. YAML is whitespace-sensitive and partial edits silently corrupt the document.

### Cursor prompts must be scoped to repo root

Every Cursor prompt MUST start with: "IMPORTANT: The repo is at /Users/swetagurnani/REPO_NAME/ — all file paths must use ~/REPO_NAME/ as the root." Without this, Cursor sometimes operates against the wrong working directory.

### Verification commands belong AFTER the prompt body, not as file content

End every Cursor prompt with: "Run each command and paste the raw terminal output directly. Do not describe or summarize the expected output. Do NOT include the verification instructions as file content — they are for you to run after writing the file."

### Surgical fixes vs delegated edits

- **Single-line fix in a known-good file** → Claude does it directly with str_replace, no Cursor needed.
- **Multi-line, multi-file, or unfamiliar territory** → Cursor prompt with full context.
