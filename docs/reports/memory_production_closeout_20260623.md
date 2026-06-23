# Memory Production Closeout - 2026-06-23

## Verdict

| Area | State | Evidence |
|---|---:|---|
| Overall memory readiness | GREEN | `scripts/check_memory_production_readiness.py` on Brain returned `production_ready=true`, `status=pass`, `p0=0`, `p1=0`, `p2=0`. |
| Memory SLO monitor | GREEN | `scripts/check_memory_observability.py --dry-run --no-alert` on Brain returned `status=pass`, `violations=[]`, `should_alert=false`. |
| Temporal graph E2E | PASS | Reviewed-write create/archive path executed for one node and one edge; graph audit rows increased to 26. |
| Graph operator UX data | PASS | Ken principal now has 7 active non-sensitive graph nodes and 5 active non-sensitive graph edges for Helm graph rendering. |
| Helm graph browser smoke | PASS | Helm Memory > Graph renders the seeded `ken` graph, supports node selection, shows relationship history, and exposes `Queue archive`. |
| Backup/restore evidence | PASS | Latest restore drill log on Sandbox reports `status=pass`, `table_count=110`, `fail_reasons=[]`. |

## Scope

Closed the final memory gaps for:

- Live temporal graph E2E through reviewed-write proposal, approval, execute, archive, and audit.
- Non-sensitive graph seed data so Helm can render a useful web graph instead of an empty graph.
- Production closeout evidence: deployment, readiness, SLO, access review, audit-log sample, and restore-drill sample.

Out of scope:

- Additional Helm visual polish beyond already-merged graph v2 controls.
- Importing or embedding Obsidian. Helm remains the product-owned operator UI; the graph is Helm-native.

## Deployment Evidence

| Item | Value |
|---|---|
| Alpha PR | `#525` |
| Merge commit | `a1d13bd18dd0f1f8cf271d77f28ef9b71f24059a` |
| Deploy target | Brain `~/jarvis-alpha` |
| Deploy command | `scripts/jarvisalpha_pull.sh` |
| Migration applied | `20260623_153600_memory_graph_valid_window_guard.sql` |
| Migration checksum | `ca989c43a30a4ecb8f4969643d32b956ce8160c3242c5080a484a221a793d352` |
| Migration applied at | `2026-06-23 16:05:20.214128-04` |
| Migration execution time | `51 ms` |
| Brain test gate | `1556 passed, 6 skipped` |

Post-deploy note: the migration runner emitted transaction wrapper warnings because the runner already wraps migration execution. The migration applied and post-deploy checks passed.

## Live Graph E2E Evidence

| Check | Value |
|---|---|
| Principal | Ken principal `17eaebb1-d614-5558-bf31-df498d7a61b6` |
| Active nodes after E2E | `7` |
| Active edges after E2E | `5` |
| Total graph nodes | `12` |
| Total graph edges | `7` |
| Open graph proposals | `0` |
| Stale graph proposals | `0` |
| Graph audit rows | `26` |
| Checked at | `2026-06-23T16:07:15.996228-04:00` |

Reviewed-write archive path executed:

| Object | Object ID | Proposal ID | Approval queue ID | Result |
|---|---|---|---|---|
| Edge | `8ca8242d-d1bd-4757-98ac-4f5b85a7b42d` | `baf00ccc-e14d-412a-bab5-5d8602ffff69` | `d4302e9b-7e3f-4a0e-8d00-822ef17f29f0` | Archived and audited |
| Node | `a05295a4-ff08-406e-af37-c8cbbf51b3bb` | `c2bb01cf-f7f1-4365-9854-874ea06aa105` | `2fe7dd82-ce97-459b-8d64-b857e0447870` | Archived and audited |

Audit actor and source:

- `actor=codex-memory-closeout`
- `source_surface=codex_closeout`

## Graph Seed Data

Non-sensitive active nodes:

| Type | Label |
|---|---|
| person | Ken |
| project | AT-0 Memory |
| project | Helm Memory tab |
| project | Alpha Brain |
| project | Temporal graph management |
| task | Backup and restore drill |
| task | Archive E2E peer 2026-06-23 |

Non-sensitive active edges:

| Source | Relationship | Target |
|---|---|---|
| Ken | `works_on` | AT-0 Memory |
| Helm Memory tab | `belongs_to` | AT-0 Memory |
| Temporal graph management | `belongs_to` | AT-0 Memory |
| Backup and restore drill | `belongs_to` | AT-0 Memory |
| Alpha Brain | `related_to` | AT-0 Memory |

## Helm Browser Smoke Evidence

Live Helm URL:

```text
https://jarvis-endpoint.tail40ed36.ts.net:4300/memory?memoryTab=graph
```

Browser verification:

| Step | Result |
|---|---|
| Open Memory tab directly | PASS - page title `jarvis-helm`; Memory tab selected. |
| Graph tab visible | PASS - `Graph 7` selected. |
| All-users filter | Expected empty detail state; aggregate counters still show graph health. |
| Select principal `ken` | PASS - graph controls, clusters, nodes, edges, and minimap render. |
| Active node counter | `7` |
| Active edge counter | `5` |
| Audit row counter | `26` |
| Visible clusters | `Project`, `Task / Operator`, `Person` |
| Click node `person Ken` | PASS - selected-object panel opens. |
| Relationship history | PASS - shows `works on` relationship to `AT-0 Memory`. |
| Operator action | PASS - selected panel exposes `Queue archive`. |

Note: the archive execution path was already validated through Alpha reviewed-write proposal, approval, execute, and audit. Browser smoke stopped before pressing `Queue archive` to avoid archiving the seeded operator graph rows.

## Production Readiness Evidence

Brain command:

```bash
cd ~/jarvis-alpha
.venv/bin/python scripts/check_memory_production_readiness.py
```

Result summary:

| Field | Value |
|---|---|
| `production_ready` | `true` |
| `status` | `pass` |
| `rag` | `green` |
| `failures` | `[]` |
| `gap_summary` | `{p0: 0, p1: 0, p2: 0}` |
| `next_actions` | `[]` |
| `missing_tables` | `[]` |
| `force_rls_missing` | `[]` |
| `graph_functions_missing` | `[]` |
| `graph_app_execute_missing` | `[]` |
| `graph_writer_execute_missing` | `[]` |
| `graph_public_execute_grants` | `[]` |
| `graph_audit_rows` | `26` |
| `graph_open_proposals` | `0` |
| `graph_stale_proposals` | `0` |
| `restore_drill_events_30d` | `20` |

Important verification note: this script must run on Brain or with Brain's production DSN. Running it against Air's local/default DB is not valid production evidence.

## SLO Sign-Off

Brain command:

```bash
cd ~/jarvis-alpha
.venv/bin/python scripts/check_memory_observability.py --dry-run --no-alert
```

Result summary:

| Field | Value |
|---|---|
| `status` | `pass` |
| `rag` | `green` |
| `violations` | `[]` |
| `should_alert` | `false` |
| `pending_review` | `0` |
| `review_required_24h` | `0` |
| `dream_reviewed_writes_open` | `0` |
| `stale_dream_reviewed_writes` | `0` |
| `dream_approval_mismatch_count` | `0` |
| `dream_executed_without_ledger` | `0` |
| `graph_open_proposals` | `0` |
| `graph_stale_proposals` | `0` |
| `graph_approval_mismatch_count` | `0` |
| `graph_executed_without_audit` | `0` |
| `unread_memory_buddy_events` | `7` of max `500` |
| `high_priority_buddy_events` | `1` of max `10` |

Threshold definitions:

| RAG | Definition |
|---|---|
| GREEN | No fail or warn threshold is breached. |
| YELLOW | Only warn thresholds are breached; operator action is needed, but integrity checks are clean. |
| RED | At least one fail threshold is breached or the monitor errors. |

## Access Review Evidence

| Check | Result |
|---|---|
| Memory graph tables exist | PASS |
| FORCE RLS enabled on memory governance tables | PASS |
| FORCE RLS enabled on graph tables | PASS |
| App EXECUTE grants on graph operator functions | PASS |
| Writer EXECUTE grants on graph operator functions | PASS |
| Public EXECUTE grants on graph operator functions | PASS - none found |

Graph tables with RLS and FORCE RLS:

| Table | RLS | FORCE RLS |
|---|---:|---:|
| `alpha_memory_graph_audit` | `true` | `true` |
| `alpha_memory_graph_edges` | `true` | `true` |
| `alpha_memory_graph_nodes` | `true` | `true` |
| `alpha_memory_graph_proposals` | `true` | `true` |

Operator functions with app/writer EXECUTE:

- `public.propose_memory_graph_write(uuid,text,text,jsonb,text,text,text)`
- `public.execute_memory_graph_proposal(uuid,uuid,text)`
- `public.list_memory_graph_current(uuid,timestamp with time zone,integer)`
- `public.list_memory_graph_history(uuid,uuid,integer)`
- `public.list_memory_graph_proposals(uuid,text,integer)`
- `public.memory_graph_health()`

P2 hardening note: `public.enforce_memory_graph_valid_window()` is a trigger helper and inherits default `PUBLIC EXECUTE`. It is not part of the operator API surface. Consider revoking public execute in a future security-hardening pass.

## Audit Evidence

Graph audit rows for `actor=codex-memory-closeout`:

| Action | Object type | Rows | Latest |
|---|---|---:|---|
| `create_node` | node | `8` | `2026-06-23 16:07:15.938802-04` |
| `create_edge` | edge | `6` | `2026-06-23 16:07:15.938802-04` |
| `archive_node` | node | `1` | `2026-06-23 16:07:15.938802-04` |
| `archive_edge` | edge | `1` | `2026-06-23 16:07:15.938802-04` |

Approval audit rows for `decided_by=codex-memory-closeout`:

| Decision | Rows | Latest |
|---|---:|---|
| `approved` | `16` | `2026-06-23 16:07:15.938802-04` |
| `auto` | `16` | `2026-06-23 16:07:15.938802-04` |

## Backup And Restore Evidence

Latest backup/restore Buddy evidence:

| Source | Event type | Latest | Rows |
|---|---|---|---:|
| `pg_backup_alpha` | `system` | `2026-06-23 02:30:11.600392-04` | `40` |
| `pg_backup_alpha` | `alert` | `2026-06-05 12:36:36.339714-04` | `2` |
| `restore_drill_alpha` | `system` | `2026-06-23 15:24:18.568870-04` | `12` |
| `restore_drill_alpha` | `alert` | `2026-06-23 15:04:33.832834-04` | `8` |

Latest restore drill file:

| Field | Value |
|---|---|
| File | `/Users/jarvissand/jarvis/logs/restore_drill_2026-06-23_192357.json` |
| `run_id` | `2026-06-23_192357` |
| `host` | `jarvis-sandbox` |
| `status` | `pass` |
| `source_dump` | `jarvis_alpha_2026-06-23_063005.dump.gpg` |
| `table_count` | `110` |
| `minimum_table_count` | `105` |
| `restore_err_count` | `2` |
| `pgaudit_err_count` | `2` |
| `fail_reasons` | `[]` |

## Remaining Work

| Priority | Item | Owner | Target | Status |
|---|---|---|---|---|
| P0 | None | Codex | 2026-06-23 | Closed |
| P1 | None | Codex | 2026-06-23 | Closed |
| P2 | Browser visual smoke of Helm graph rendering after deploy | Codex | 2026-06-23 | Closed |
| P2 | Revoke default PUBLIC EXECUTE on graph trigger helper | Codex | TBD | Optional hardening |
| P2 | Add richer graph clustering/timeline UX beyond v2 controls | Codex | TBD | Product polish |

## Sign-Off

Memory is production-green for the implemented scope:

- Explicit semantic memory management.
- Dream reviewed-write control lane.
- Buddy event noise suppression and retention.
- Temporal graph reviewed-write governance.
- Helm-native memory manager and graph controls.
- Backup/restore, access review, audit evidence, and SLO monitor.
