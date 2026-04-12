# TD-57 — smoke_lib.sh Design

**Status:** SHIPPED 2026-04-12
**Scope:** v1, strict to 3 primitives from TD-57
**Depends on:** SMOKE_LIB_DISCOVERY.md (incl. Appendix A shellcheck baseline)
**Runtime:** bash 5+ required (pinned via `#!/opt/homebrew/bin/bash` shebang + runtime guard)

---

## 1. Scope

v1 ships exactly three primitives:

| Primitive | Purpose |
|---|---|
| `psql_capture_uuid` | Run psql, extract a single UUID from output, filter psql noise |
| `psql_admin` | Run psql as admin with ON_ERROR_STOP + -X + -tA defaults |
| `assert_row_count` | Assert a COUNT(*) result equals an expected integer |

**Non-goals (logged as TD-58):**
- `load_secrets` helper (source vs grep/cut divergence)
- `run_writer` / `run_admin` wrappers (partial in 2 scripts today)
- Structured JSON output (existing smokes use echo PASS/FAIL)
- Migration of password-auth smokes (smoke_writer_role, smoke_memory_secdef, smoke_security_definer)

---

## 2. Design Principle — Dependency Injection

The library has zero opinion on authentication. Callers construct their own psql command array and pass it in by name (bash nameref). Matches big-tech shell library convention and smoke_5d1's existing `PSQL_ADMIN=(...)` pattern.

Rejected: DSN-only API (forces auth migration), dual-flavor API (doubles surface).

---

## 3. Runtime Requirement — bash 5+

Nameref (`local -n`) requires bash 4.3+. macOS ships bash 3.2.57 at `/bin/bash` for licensing reasons. We pin Homebrew bash 5:

- Shebang on all smoke scripts: `#!/opt/homebrew/bin/bash`
- Runtime guard in smoke_lib.sh asserts `${BASH_VERSINFO[0]} -ge 5`, exits loud on mismatch
- Install on all nodes: `brew install bash`

---

## 4. Interface Contracts

### 4.1 psql_capture_uuid
Run a psql command, return the first UUID from stdout, strip command tags and multi-statement concatenation.

- Input $1: bash array variable name holding psql + flags
- Input $2: SQL string
- Output: UUID to stdout, or empty
- Exit: 0 success, 1 psql failed, 2 no UUID found
- Implementation: `grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -1`
- Solves: b868f4e and 6c3e0e7 psql surprises (command tag leak, multi-statement concat)

### 4.2 psql_admin
Run psql with hardened defaults for admin operations.

- Input $1: SQL string
- Input $2..: optional extra psql flags
- Defaults: `-X -v ON_ERROR_STOP=1 -tA -U jarvisbrain -d jarvis_alpha`
- Output: psql stdout
- Exit: psql exit code
- Rationale: 4 smokes already use `-U jarvisbrain -d jarvis_alpha` for admin. Architectural constant, not parameter.

### 4.3 assert_row_count
Assert a COUNT(*) query returns an expected integer.

- Input $1: bash array variable name
- Input $2: SQL returning a single integer
- Input $3: expected integer
- Input $4: human-readable test name
- Output: `PASS: <name>` or `FAIL: <name> (expected=E got=G)`
- Exit: 0 match, 1 mismatch, 2 psql failed

---

## 5. Sourcing Convention (SC1090 mitigation)

Every caller:

```bash
# shellcheck source=scripts/smoke_lib.sh
source "$(dirname "$0")/smoke_lib.sh"
```

Directive resolves SC1090 at lint time without runtime coupling.

---

## 6. Control Flow Rules (SC2015 mitigation)

All primitives use explicit `if/else`. Never `A && B || C` as assert idiom.

---

## 7. File Layout
scripts/
├── smoke_lib.sh                    # NEW
├── smoke_5d1_watchdog_agent.sh     # MIGRATED
├── smoke_task_events_insert.sh     # MIGRATED
└── (4 others untouched)

---

## 8. Test Plan — Shipped Results

Single-commit delivery. All acceptance criteria met:

- smoke_lib.sh 46 lines, ≤120 budget
- shellcheck clean on lib + both migrated smokes
- 5/5 tests PASS on smoke_5d1_watchdog_agent.sh against Brain Postgres
- 3/3 tests PASS on smoke_task_events_insert.sh against Brain Postgres
- 4 untouched smokes unchanged (shellcheck baseline identical)

---

## 9. Rollback

Single-commit revert:
git revert <commit_sha>

Pre-migration backups as `*.bak_pre_td57` retained until 24h soak complete.

---

## 10. Acceptance Criteria — All Met

- smoke_lib.sh exists with exactly 3 primitives, ≤ 120 lines ✓
- Both migrated smokes pass identically to pre-migration behavior ✓
- shellcheck clean on lib + both migrated smokes ✓
- 4 untouched smokes unchanged ✓
- Zero production code touched ✓

---

## 11. Invocation Lesson Locked

**Never invoke smokes as `bash script.sh`** — this forces system bash 3.2 and bypasses the shebang. Always invoke directly: `./script.sh` or `~/jarvis-alpha/scripts/script.sh`. The runtime version guard caught this during ship — belt-and-suspenders design validated.

Documentation convention for all future smoke invocations in handoffs and runbooks: executable path only, no `bash` prefix.

---

## 12. Out of Scope — TD-58 Logged

- smoke_lib.sh v2: `load_secrets`, `run_writer` / `run_admin` helpers
- Migration of remaining 4 smokes to use lib
- Add shellcheck as CI step in ci.yml
