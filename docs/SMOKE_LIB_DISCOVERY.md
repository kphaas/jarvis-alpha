# TD-57 Phase 1 discovery — `smoke_lib.sh` inputs

**Scope:** Inventory and conventions from existing `~/jarvis-alpha/scripts/smoke_*.sh` only (no library implementation). Repo root: `~/jarvis-alpha/`.

---

## 1. Existing smoke scripts inventory

### 1.1 Files matching `smoke_*.sh`

| File | Lines (`wc -l`) | psql invocations (see note) | Secrets / env vars read |
|------|-----------------|-----------------------------|-------------------------|
| `~/jarvis-alpha/scripts/smoke_5d1_watchdog_agent.sh` | 109 | **6** per run | `source ~/jarvis/.secrets` → **`ALPHA_DB_DSN_WATCHDOG_AGENT`** (required). Admin uses local **`jarvisbrain`** (no password in script). |
| `~/jarvis-alpha/scripts/smoke_writer_role.sh` | 81 | **7** | **`ALPHA_WRITER_DB_PASSWORD`** parsed from `~/jarvis/.secrets` via `grep`/`cut` (not `source`). |
| `~/jarvis-alpha/scripts/smoke_memory_secdef.sh` | 166 | **12** | **`ALPHA_WRITER_DB_PASSWORD`** from `~/jarvis/.secrets` (grep). |
| `~/jarvis-alpha/scripts/smoke_security_definer.sh` | 137 | **10** | **`ALPHA_WRITER_DB_PASSWORD`** from `~/jarvis/.secrets` (grep). |
| `~/jarvis-alpha/scripts/smoke_buddy_secdef.sh` | 73 | **8** baseline; **+4** if `$USER_ID` set | No secrets file; **no** `ALPHA_*` DSN. Uses peer-style `psql -U … -d …` only. |
| `~/jarvis-alpha/scripts/smoke_task_events_insert.sh` | 79 | **7** on success path | No secrets; admin `psql -U jarvisbrain` only. |

**Invocation count note:** Count is the number of times `psql` is executed in a typical successful run (each `"$PSQL" …`, `"${PSQL_ADMIN[@]}" …`, `run_writer` / `run_admin` call counts as one). `smoke_buddy_secdef.sh` adds two writer + two admin calls in Test 5 when `<known_user_id>` is passed.

### 1.2 `psql` binary path

All six scripts hardcode the same Homebrew PostgreSQL 16 client:

```12:12:~/jarvis-alpha/scripts/smoke_5d1_watchdog_agent.sh
PSQL="/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql"
```

(`smoke_buddy_secdef.sh` omits quotes: `PSQL=/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql`.)

### 1.3 Exact `psql` flag patterns observed

| Pattern | Scripts | Meaning in practice |
|---------|---------|---------------------|
| **`-X`** (`--no-psqlrc`) | `smoke_5d1_watchdog_agent.sh`, `smoke_task_events_insert.sh` | Avoid user/rc side effects. **Not** used in writer_role, memory_secdef, security_definer, buddy_secdef. |
| **`-t`** tuples-only, **`-A`** unaligned | Nearly all queries | Machine-readable single-column / row output. |
| **`-c`** single command | Cleanup `DELETE` in 5d1 (`-c "DELETE …"`), `delete_by_id` in task_events (`-c` + `-v ON_ERROR_STOP=1`) | Non-`-tA` for some admin one-shots. |
| **`-v ON_ERROR_STOP=1`** | `smoke_task_events_insert.sh` `delete_by_id` only | Abort SQL script on first error inside that `-c` invocation. |
| **Connection** | Mixed | See §3. |

**No script passes** `-v ON_ERROR_STOP` **to** `-tAc` **queries** except as above for `-c` deletes.

---

## 2. The three primitives TD-57 names

### 2.1 `psql_capture_uuid` — “capture a UUID from `psql` stdout”

There is **no** shared function today; three **divergent** patterns:

**A — CTE wrapping `INSERT … RETURNING` + `SELECT id::text` (avoids command-tag / extra noise)**

Introduced in commit `99eafa4` on `smoke_task_events_insert.sh` (see §5.1).

```28:35:~/jarvis-alpha/scripts/smoke_task_events_insert.sh
  id=$("$PSQL" -X -U jarvisbrain -d jarvis_alpha -tAc "
    WITH ins AS (
      INSERT INTO alpha_task_events (event_type, graph_id, step_id, message, severity)
      VALUES ('step_retrying', NULL, NULL, '${detail}', '${severity_val}')
      RETURNING id
    )
    SELECT id::text FROM ins;
  ")
```

Then whitespace strip: `id=$(echo "$id" | tr -d '[:space:]')` at lines 40–41.

**B — Raw `SELECT fn_returning_uuid()` or `INSERT … RETURNING` without CTE**

Used when the query is a **single** statement (no `BEGIN/COMMIT` wrapper), e.g.:

```61:71:~/jarvis-alpha/scripts/smoke_security_definer.sh
TEST_ID=$("$PSQL" -U jarvisbrain -d jarvis_alpha -tAc "
  SELECT public.record_buddy_event(
    'system',
    'system',
    'Stage 3 smoke test',
    'Testing SECURITY DEFINER function',
    1,
    'smoke_test',
    '{\"test\": true}'::jsonb
  );
")
```

**C — Multi-statement transaction + pipeline filter (UUID regex)**

`smoke_5d1_watchdog_agent.sh` uses `BEGIN` / `COMMIT` and **pipes** `-tAc` output through `grep -E` + `head -1` (commit `6c3e0e7`):

```53:63:~/jarvis-alpha/scripts/smoke_5d1_watchdog_agent.sh
TEST_ID=$("$PSQL" -X "$ALPHA_DB_DSN_WATCHDOG_AGENT" -tAc "
  BEGIN;
  SELECT set_config('rls.user_id', 'system', true);
  WITH ins AS (
    INSERT INTO alpha_watchdog_events (service_name, node, event_type, error_message, action_taken)
    VALUES ('smoke_5d1_test', 'brain', 'check_error', 'smoke_5d1_watchdog_agent test row', 'none')
    RETURNING id
  )
  SELECT id::text FROM ins;
  COMMIT;
" | grep -E '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$' | head -1)
```

**Variation summary:** **Divergent** — choose CTE-only strip vs regex pipeline vs raw UUID line depending on whether the SQL is multi-statement and whether `-tAc` can emit non-UUID lines.

---

### 2.2 `psql_admin` — “run SQL as admin / superuser-style connection”

**No** single abstraction; patterns:

**A — Explicit argv array (5d1)**

```14:15:~/jarvis-alpha/scripts/smoke_5d1_watchdog_agent.sh
# Admin connection for cleanup (writer cannot DELETE from alpha_watchdog_events by design)
PSQL_ADMIN=("$PSQL" -X -U jarvisbrain -d jarvis_alpha)
```

Used as `"${PSQL_ADMIN[@]}" -tAc "…"` or `"${PSQL_ADMIN[@]}" -c "…"`.

**B — Inline `-U jarvisbrain -d jarvis_alpha`**

Most smokes (writer_role, memory_secdef, security_definer, task_events).

**C — Helper `run_admin` (buddy smoke)**

```23:24:~/jarvis-alpha/scripts/smoke_buddy_secdef.sh
run_writer() { "$PSQL" -U "$WRITER_ROLE" -d "$DB" -tAc "$1"; }
run_admin()  { "$PSQL" -U "$ADMIN_ROLE"  -d "$DB" -tAc "$1"; }
```

Here “admin” is **`jarvisbrain`**, not a URI DSN.

**D — DSN-based “writer” vs local admin**

`smoke_5d1_watchdog_agent.sh` uses **`ALPHA_DB_DSN_WATCHDOG_AGENT`** for `jarvis_alpha_writer` and **`PSQL_ADMIN`** for `jarvisbrain` cleanup — two different connection styles in one file.

**Variation summary:** **Divergent** — admin is always `jarvisbrain` + database `jarvis_alpha` in these scripts, but invocation shape (array vs inline vs function) and presence of **`-X`** differ.

---

### 2.3 `assert_row_count` — “expect N rows affected / returned”

**No** shared helper; patterns:

**A — `DELETE … RETURNING` + `SELECT count(*)::text` + string compare `"1"`**

```72:83:~/jarvis-alpha/scripts/smoke_5d1_watchdog_agent.sh
DELETE_COUNT=$("${PSQL_ADMIN[@]}" -tAc "
  WITH del AS (
    DELETE FROM alpha_watchdog_events WHERE id = '$TEST_ID'::uuid
    RETURNING id
  )
  SELECT count(*)::text FROM del;
")
DELETE_COUNT=$(echo "$DELETE_COUNT" | tr -d '[:space:]')
if [[ "$DELETE_COUNT" != "1" ]]; then
  echo "❌ DELETE affected $DELETE_COUNT rows (expected 1)" >&2
  exit 1
fi
```

**B — Post-`INSERT` verification with `SELECT count(*)::text`**

```43:48:~/jarvis-alpha/scripts/smoke_task_events_insert.sh
  cnt=$("$PSQL" -X -U jarvisbrain -d jarvis_alpha -tAc \
    "SELECT count(*)::text FROM alpha_task_events WHERE id = '${id}'::uuid;")
  if [[ "$cnt" != "1" ]]; then
    echo "❌ Confirm failed: expected 1 row, got ${cnt}" >&2
    return 1
  fi
```

**C — Semantic equivalence (not literal row count)**

`smoke_buddy_secdef.sh` compares `cardinality(list)` to `count(DISTINCT user_id)` — same “assert” *idea*, different SQL.

**Variation summary:** **Divergent** — numeric compare after `tr -d '[:space:]'` is the common theme for literal counts; buddy uses cross-query consistency checks.

---

## 3. DSN / role conventions

### 3.1 DSN env vars used **by smokes**

| Variable | Scripts | Role implied |
|----------|---------|----------------|
| **`ALPHA_DB_DSN_WATCHDOG_AGENT`** | `smoke_5d1_watchdog_agent.sh` only | Writer pool for watchdog agent (`current_user` checked = `jarvis_alpha_writer`). |
| *(none — URI not from env)* | All other smokes | N/A |

**`ALPHA_DB_DSN`, `ALPHA_DB_DSN_WRITER`, `ALPHA_DB_DSN_BUDDY`, `JARVIS_ALPHA_DB_DSN`** appear in **application** code and docs but **not** in any `smoke_*.sh` in this repo.

### 3.2 Writer vs admin switching

| Script | Writer path | Admin path |
|--------|-------------|------------|
| `smoke_5d1_watchdog_agent.sh` | `"$PSQL" -X "$ALPHA_DB_DSN_WATCHDOG_AGENT" -tAc …` | `"${PSQL_ADMIN[@]}"` = `-X -U jarvisbrain -d jarvis_alpha` |
| `smoke_writer_role.sh` | `PGPASSWORD` + `-h localhost -U jarvis_alpha_writer` | `-U jarvisbrain` (no `-h`) |
| `smoke_memory_secdef.sh` / `smoke_security_definer.sh` | Same as writer_role for writer tests | `-U jarvisbrain` for catalog/metadata |
| `smoke_buddy_secdef.sh` | `run_writer` → `-U jarvis_alpha_writer` | `run_admin` → `-U jarvisbrain` |
| `smoke_task_events_insert.sh` | N/A (all `jarvisbrain`) | N/A |

### 3.3 Peer auth vs password auth (from script evidence only)

| Connection style | Mechanism |
|------------------|-----------|
| `-U jarvisbrain -d jarvis_alpha` **without** `-h` | Local default (socket); **no** `PGPASSWORD` in script → treated as **non-password** in-script (typically peer/trust on Brain; not verified from this repo). |
| `-h localhost -U jarvis_alpha_writer` | **`PGPASSWORD`** from **`ALPHA_WRITER_DB_PASSWORD`** → **password** auth over TCP. |
| `"$PSQL" -X "$ALPHA_DB_DSN_WATCHDOG_AGENT"` | **URI** passed as psql’s “dbname” positional argument; password may be **inside the URI** (not in repo). Handoff doc states **peer auth, same DSN as WRITER** for this secret (`~/jarvis-alpha/docs/handoffs/HANDOFF_2026-04-12_01.md`). |
| `smoke_buddy_secdef.sh` writer/admin | No `-h`, no `PGPASSWORD` → same peer-style assumption as `jarvisbrain` local tests. |

**Confirming `pg_hba.conf` or live auth method** was **not** done in this discovery (Brain-only runtime).

---

## 4. Output / logging conventions

### 4.1 PASS / FAIL signaling

| Style | Scripts |
|-------|---------|
| **Echo + exit** | Most: `echo "OK: …"`, `echo "❌ …" >&2`, `exit 1` / `exit 0`. |
| **Structured pass/fail helpers** | `smoke_buddy_secdef.sh` only: `pass()` / `fail()` with `printf '  PASS  %s\n'` / `'  FAIL  %s\n'`, aggregate `failures` flag. |
| **Manual “Expected:” lines** | writer_role, memory_secdef, security_definer — human compares echoed output to comment. |

### 4.2 Exit codes

- **`0`** — success (`exit 0` explicit in 5d1 and task_events; buddy ends `exit 0` when `failures==0`).
- **`1`** — failure (hostname guard, assertion failure, RLS negative test wrong outcome, buddy `failures!=0`).
- **`return 1`** inside `insert_verify_delete` would propagate only if called with `set -e` and not in conditional — `smoke_task_events_insert.sh` calls `insert_verify_delete` at top level with `set -e`, so failure exits the script non-zero.

### 4.3 Structured output (JSON)

- **No JSON** from smokes themselves — plain `echo` / `printf` only.
- Some queries **return** JSON/JSONB **from PostgreSQL** (e.g. `run_buddy_memory_maintenance`) as **text** in `-tAc` output, not wrapped as JSON by the shell.

---

## 5. Three `psql` surprises (session 04-12) — commits `99eafa4`, `6c3e0e7`, `b868f4e`

Handoff cross-reference: `~/jarvis-alpha/docs/handoffs/HANDOFF_2026-04-12_01.md` (“Smoke Script Hardening”).

### 5.1 Commit `99eafa4` — “smoke-cte” (`fix(smoke): wrap task_events INSERT in CTE + add -X to all psql calls`)

| Item | Detail |
|------|--------|
| **psql behavior** | With `INSERT … RETURNING` as the **sole** `-c`/`-tAc` body, client output can include **command tags** (e.g. `INSERT 0 1`) mixed with the RETURNING row, polluting capture of a bare UUID. |
| **Fix pattern** | Wrap in `WITH ins AS (INSERT … RETURNING id) SELECT id::text FROM ins` so the selected row is the stable `-tAc` payload; add **`-X`** on all `psql` invocations in that script. |
| **Library-repeatable?** | Yes — a **`psql_capture_uuid`** helper can standardize **CTE + `SELECT id::text`** for INSERT paths and always pass **`-X`**. |

### 5.2 Commit `6c3e0e7` — `fix(smoke-5d1): filter psql multi-statement output through UUID regex`

| Item | Detail |
|------|--------|
| **psql behavior** | A **multi-statement** string (`BEGIN;` … `COMMIT;`) produces **concatenated** tuples-only output (e.g. multiple lines or glued tokens), so `tr -d '[:space:]'` on the whole blob is **not** a reliable UUID extractor. |
| **Fix pattern** | Pipe `-tAc` output through `grep -E '^[a-f0-9]{8}-…$' \| head -1` to extract a **single** UUID line. |
| **Library-repeatable?** | Yes — optional **regex filter** (or “single-statement-only” API) when transactions cannot be avoided. |

### 5.3 Commit `b868f4e` — `fix(smoke-5d1): use admin for DELETE + row-count assertion`

| Item | Detail |
|------|--------|
| **psql behavior** | Under **RLS**, `DELETE` with the **writer** connection can **match zero rows** without raising an error — silent no-op if there is **no DELETE policy** for that role. |
| **Fix pattern** | Run **`DELETE` via `PSQL_ADMIN` (`jarvisbrain`)** and assert **`count(*) = 1`** from `DELETE … RETURNING` via a `WITH del AS (DELETE … RETURNING id) SELECT count(*)::text FROM del`. |
| **Library-repeatable?** | Yes — **`psql_admin` + `assert_row_count`** (or single **`assert_delete_affected`**) encodes the pattern. |

---

## 6. Sourcing mechanics

### 6.1 Does `source` work from `~/jarvis-alpha/scripts/`?

Tested on the discovery host (not necessarily Brain):

```text
source from scripts cwd: exit=0
double source: exit=0
FOO=2
```

(`cd ~/jarvis-alpha/scripts && bash -c 'source /dev/null; …'` — bash has no problem with `source` when cwd is `scripts/`.)

**Caveat:** Existing **`smoke_*.sh` are executable scripts**, not libraries. Sourcing a smoke file would **run** top-level code (hostname checks, tests) — **not** recommended. A future `smoke_lib.sh` should contain **only** function defs + guarded init if intended to be sourced.

### 6.2 What breaks if `smoke_lib.sh` is sourced twice?

Typical bash behavior (no `smoke_lib.sh` in repo yet — **predictions**):

- **Function definitions** — redefined silently (last definition wins).
- **`set -e` / `set -u` / `set -o pipefail`** — if the lib sets shell options, re-sourcing can **re-apply** them; usually harmless unless a future version **toggles** options off.
- **`readonly`** — second source fails if the lib uses `readonly` for the same name.
- **`set -a` (allexport)** — if used in the lib, could change export behavior for the rest of the script unless paired with `set +a`.

### 6.3 ShellCheck on current smokes

ShellCheck was installed via Homebrew and run on all six `smoke_*.sh` files on **2026-04-12**. **Baseline:** [Appendix A — Shellcheck Baseline (2026-04-12)](#appendix-a--shellcheck-baseline-2026-04-12).

**Manual note:** `smoke_buddy_secdef.sh` uses `set -uo pipefail` **without** `-e` — intentional so test blocks don’t abort early; a shared lib should not assume all consumers use `set -e`.

---

## 7. Open questions for Air Claude

1. **Single vs multiple UUID capture APIs** — Need both **CTE** (task_events) and **regex pipeline** (5d1 transaction) behind one primitive, or two explicit entry points?
2. **`-X` policy** — Should the library **always** pass `-X` for parity with hardened smokes, or follow the split (older smokes never use `-X`)?
3. **`PSQL` path** — Centralize Homebrew path vs `command -v psql` vs env override **`PSQL` / `PGSQL`**?
4. **Admin connection identity** — Only `jarvisbrain@jarvis_alpha` local, or also URI-based admin for future smokes?
5. **`smoke_buddy_secdef.sh` optional `$USER_ID`** — Test 5 path changes invocation count and assertions; library may need “optional test sections” outside strict primitives.
6. **Human-driven smokes** (writer_role, memory_secdef, security_definer) — Heavy reliance on **eyes** vs automated assert; `smoke_lib` may not replace these without a separate “compare to golden” layer.
7. **Secrets loading** — Prefer `source ~/jarvis/.secrets` + named vars vs grep one key (`ALPHA_WRITER_DB_PASSWORD`) — two patterns exist.
8. **Hostname guard** — Five scripts require `jarvis-brain`; buddy smoke does **not**. Should the library enforce host, or leave to callers?

---

## 8. Smokes that are unusual vs a minimal lib

| Script | Unusual aspect |
|--------|----------------|
| `smoke_buddy_secdef.sh` | No Brain hostname check; `set -u` without `-e`; pass/fail `printf` API; cross-query cardinality vs count. |
| `smoke_writer_role.sh` / `smoke_memory_secdef.sh` / `smoke_security_definer.sh` | Many tests are **informational** (print + “Expected:” comment), not strict assertions. |
| `smoke_5d1_watchdog_agent.sh` | Only smoke using **`ALPHA_DB_DSN_WATCHDOG_AGENT`** + RLS `set_config` + writer/admin split + negative test with `set +e` / exit code inspection. |

---

*Discovery generated for TD-57 — Phase 1 only; no code changes in `~/jarvis-alpha/scripts/` beyond this doc.*

## Appendix A — Shellcheck Baseline (2026-04-12)

### A.1 Tooling

| Item | Value |
|------|-------|
| **shellcheck version** | `ShellCheck - shell script analysis tool` / **version 0.11.0** (from `shellcheck --version`; installed with `brew install shellcheck` on 2026-04-12). |
| **Exact command** | `shellcheck <FILE>` — **no additional flags**. Defaults: Shell dialect inferred from shebang (`#!/usr/bin/env bash` → bash); minimum severity includes style/info/warning/error per `shellcheck --help` (`-S` not set); color auto; `.shellcheckrc` honored unless `--norc`. |
| **Flags reviewed** (`shellcheck --help`) | Not used for this baseline: `-a`/`--check-sourced`, `-x`/`--external-sources`, `-P`/`--source-path`, `-e`/`--exclude`, `-o`/`--enable`, `-S`/`--severity`, `-f`/`--format`, `-s`/`--shell`, `--norc`, `--rcfile`. |

**Severity counts** below use JSON output `shellcheck -f json1 <FILE>` and aggregate `.comments[].level` (`error` / `warning` / `info` / `style`). Exit codes below are from `shellcheck <FILE>` immediately after diagnostics (captured with `bash -c '…; echo EXIT_CODE=$?'` so a non-zero ShellCheck result does not abort the shell).

### A.2 Per-script results

#### `~/jarvis-alpha/scripts/smoke_5d1_watchdog_agent.sh`

| Severity | Count |
|----------|------:|
| error | 0 |
| warning | 1 |
| info | 0 |
| style | 0 |
| **Total** | **1** |

**Exit code:** `1`

```text

In /Users/swetagurnani/jarvis-alpha/scripts/smoke_5d1_watchdog_agent.sh line 19:
source ~/jarvis/.secrets
       ^---------------^ SC1090 (warning): ShellCheck can't follow non-constant source. Use a directive to specify location.

For more information:
  https://www.shellcheck.net/wiki/SC1090 -- ShellCheck can't follow non-const...
```

#### `~/jarvis-alpha/scripts/smoke_buddy_secdef.sh`

| Severity | Count |
|----------|------:|
| error | 0 |
| warning | 0 |
| info | 6 |
| style | 0 |
| **Total** | **6** |

**Exit code:** `1`

```text

In /Users/swetagurnani/jarvis-alpha/scripts/smoke_buddy_secdef.sh line 28:
[[ "$out" == "true|$ADMIN_ROLE" ]] && pass "$out" || fail "got: $out"
                                   ^-- SC2015 (info): Note that A && B || C is not if-then-else. C may run when A is true.


In /Users/swetagurnani/jarvis-alpha/scripts/smoke_buddy_secdef.sh line 32:
[[ "$out" == "true|$ADMIN_ROLE" ]] && pass "$out" || fail "got: $out"
                                   ^-- SC2015 (info): Note that A && B || C is not if-then-else. C may run when A is true.


In /Users/swetagurnani/jarvis-alpha/scripts/smoke_buddy_secdef.sh line 36:
[[ "$out" == "true|true" ]] && pass "$out" || fail "got: $out"
                            ^-- SC2015 (info): Note that A && B || C is not if-then-else. C may run when A is true.


In /Users/swetagurnani/jarvis-alpha/scripts/smoke_buddy_secdef.sh line 41:
[[ "$wrapper_count" == "$baseline_count" && "$wrapper_count" -ge 1 ]] && pass "wrapper=$wrapper_count baseline=$baseline_count" || fail "wrapper=$wrapper_count baseline=$baseline_count"
                                                                      ^-- SC2015 (info): Note that A && B || C is not if-then-else. C may run when A is true.


In /Users/swetagurnani/jarvis-alpha/scripts/smoke_buddy_secdef.sh line 54:
    [[ "$subset_ok" == 1 ]] && pass "rows=$wrapper_n, all in baseline" || fail "wrapper rows not a subset of baseline"
                            ^-- SC2015 (info): Note that A && B || C is not if-then-else. C may run when A is true.


In /Users/swetagurnani/jarvis-alpha/scripts/smoke_buddy_secdef.sh line 64:
[[ "$out" == "0" ]] && pass "writer sees 0 rows (RLS enforced)" || fail "writer sees $out rows — FORCE RLS regressed"
                    ^-- SC2015 (info): Note that A && B || C is not if-then-else. C may run when A is true.

For more information:
  https://www.shellcheck.net/wiki/SC2015 -- Note that A && B || C is not if-t...
```

#### `~/jarvis-alpha/scripts/smoke_memory_secdef.sh`

| Severity | Count |
|----------|------:|
| error | 0 |
| warning | 0 |
| info | 0 |
| style | 0 |
| **Total** | **0** |

**Exit code:** `0`

```text

```

*(ShellCheck emitted no diagnostic lines on stdout or stderr.)*

#### `~/jarvis-alpha/scripts/smoke_security_definer.sh`

| Severity | Count |
|----------|------:|
| error | 0 |
| warning | 0 |
| info | 0 |
| style | 0 |
| **Total** | **0** |

**Exit code:** `0`

```text

```

*(ShellCheck emitted no diagnostic lines on stdout or stderr.)*

#### `~/jarvis-alpha/scripts/smoke_task_events_insert.sh`

| Severity | Count |
|----------|------:|
| error | 0 |
| warning | 0 |
| info | 0 |
| style | 0 |
| **Total** | **0** |

**Exit code:** `0`

```text

```

*(ShellCheck emitted no diagnostic lines on stdout or stderr.)*

#### `~/jarvis-alpha/scripts/smoke_writer_role.sh`

| Severity | Count |
|----------|------:|
| error | 0 |
| warning | 0 |
| info | 0 |
| style | 0 |
| **Total** | **0** |

**Exit code:** `0`

```text

```

*(ShellCheck emitted no diagnostic lines on stdout or stderr.)*

### A.3 Cross-cutting patterns

| Pattern | ShellCheck rule | Scripts affected | Notes for `smoke_lib.sh` |
|---------|-----------------|------------------|--------------------------|
| `source` with **non-literal** path (e.g. tilde / variable) | **SC1090** (warning) | `smoke_5d1_watchdog_agent.sh` only | No rule ID appears in more than one file in this baseline, but any lib that does `source "$VAR"` or `source ~/…` without a `# shellcheck source=…` directive will hit the same class of warning. Optional mitigation: `# shellcheck source=path/to/file` (constant path) or `-x` + `-P SCRIPTDIR` when checking callers (not used here). |
| `A && B \|\| C` used as pass/fail | **SC2015** (info) | `smoke_buddy_secdef.sh` only (6×) | If shared helpers use the same idiom for “assert and message,” expect **SC2015** unless rewritten as explicit `if`/`else`. |

**Themes (not duplicate rule IDs):** Dynamic **`source`** and **`&& … \|\|`** control flow are the two categories surfaced in this run; four scripts are completely clean under default `shellcheck` flags.

### A.4 Design hints for `smoke_lib.sh` (from findings only; no fixes applied)

- **SC1090:** A library that sources secrets or optional config from a path built at runtime will trigger the same warning unless ShellCheck directives or a dedicated `shellcheck` invocation with `-x` / `-P` is adopted in CI/docs.
- **SC2015:** Pass/fail helpers should prefer **`if cond; then …; else …; fi`** (or explicit `if !`) over `[[ … ]] && pass … || fail …` if avoiding this info-level finding matters for CI gates.
- **Clean baselines:** `smoke_memory_secdef.sh`, `smoke_security_definer.sh`, `smoke_task_events_insert.sh`, and `smoke_writer_role.sh` show that strict quoting + straightforward flow already satisfy default ShellCheck with no suppressions.

---

*Appendix A: baseline only — no edits to `~/jarvis-alpha/scripts/smoke_*.sh`.*
