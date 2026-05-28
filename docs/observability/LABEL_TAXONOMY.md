# Loki Label Taxonomy

**Status:** Draft v1 — designed for fleet-wide adoption, currently implemented on Brain only with known defects (see `docs/audit/GAP_ANALYSIS_v2.md` AUDIT-6)
**Related:** ADR-0002 (state native, compute containerized), GAP_ANALYSIS_v2 AUDIT-6 / AUDIT-8
**Migration target:** jarvis-standards repo once schema stable for 2+ sessions without changes

## 1. Purpose

Define the Loki label schema for jarvis-alpha logs. Labels are the contract between log producers (Python services via `jarvis_common.logging_config`), shippers (Fluentbit), and consumers (Grafana queries, alerts, ops runbooks). Changes to this schema break dashboards and alert rules — design for stability.

## 2. Design principles

1. **Low cardinality.** Each unique label combination is a Loki stream. High-cardinality labels (request IDs, user IDs, trace IDs) explode stream count and degrade ingest/query performance.
2. **Static facts → labels.** Things that identify WHERE/WHO a log came from belong as labels: `node`, `service`, `level`.
3. **Dynamic facts → log body.** Things that vary per-event belong in the JSON message body: `request_id`, `user_id`, `trace_id`, `status_code`, `duration_ms`. Body fields are still queryable via LogQL JSON parsing.
4. **JSON parsed before label extraction.** Python emits structured JSON to stdout; launchd captures to file; Fluentbit tails the file. Fluentbit **must** parse the JSON before applying `label_keys`. Without parsing, fields are unreachable from label expressions and Loki auto-assigns `service_name=unknown_service`.
5. **Default values explicit.** When a label cannot be determined, the producer should set it to a deliberate sentinel (`unknown`) rather than leaving it absent.

## 3. Label schema

### Required labels (every log line)

| Label | Values | Cardinality | Purpose |
|---|---|---|---|
| `node` | `brain` \| `gateway` \| `endpoint` \| `sandbox` | 4 | Physical node origin |
| `service` | see §4 Service Inventory | ~20 fleet-wide | Which process/agent emitted the log |
| `level` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL` | 5 | Log severity (Python logging level names) |

Maximum projected stream cardinality: 4 × 20 × 5 = **400 streams fleet-wide.** Well within Loki's healthy operating envelope (recommended <10K streams).

### Explicitly NOT labels (keep in JSON body)

| Field | Why not a label |
|---|---|
| `trace_id` | Unbounded — one per request |
| `request_id` | Unbounded |
| `user_id` | Unbounded + PII surface |
| `child_id` | Unbounded + PII (Ryleigh/Sloane RLS context) |
| `task_graph_id` | Unbounded |
| `dream_session_id` | Unbounded |
| `http_method`, `http_path`, `http_status` | Moderate cardinality — use as body fields for query filtering |
| `module`, `function`, `line` | High cardinality at scale |

These remain in the JSON body and are queryable via LogQL JSON parsing (e.g. `{node="brain"} | json | trace_id="abc..."`) without entering the index.

## 4. Service inventory

Target `service` values per node, sourced from `com.jarvis.alpha.*` LaunchAgent names + known nginx/non-jarvis processes.

### Brain (14 services, 9 currently tailed by Fluentbit)

| `service` label value | LaunchAgent | Currently shipped? |
|---|---|---|
| `brain_app` | com.jarvis.alpha.brain | ✅ yes |
| `brain_buddy` | com.jarvis.alpha.buddy | ✅ yes |
| `brain_executor` | com.jarvis.alpha.executor | ✅ yes |
| `brain_watchdog` | com.jarvis.alpha.watchdog | ✅ yes |
| `brain_power_sampler` | com.jarvis.alpha.power.brain | ✅ yes |
| `brain_temporal_server` | com.jarvis.alpha.temporal.server | ❌ untailed |
| `brain_temporal_ui` | com.jarvis.alpha.temporal.ui | ❌ untailed |
| `brain_temporal_worker` | com.jarvis.alpha.temporal.worker | ❌ untailed |
| `brain_pg_backup` | com.jarvis.alpha.pg_backup | ❌ untailed |
| `brain_rotate_buddy` | com.jarvis.alpha.rotate.buddy | ❌ untailed |
| `brain_rotate_service` | com.jarvis.alpha.rotate.brain_service | ❌ untailed |
| `brain_school_email` | com.jarvis.alpha.school-email | ❌ untailed |
| `brain_fluentbit` | com.jarvis.alpha.fluentbit | ❌ self-untailed |
| `brain_loki` | com.jarvis.alpha.loki | ❌ untailed |

### Gateway (1 service, no shipper)

| `service` label value | LaunchAgent | Currently shipped? |
|---|---|---|
| `gateway_app` | com.jarvis.alpha.gateway | ❌ no Fluentbit on Gateway |

### Endpoint (3 services, Fluentbit running, coverage unconfirmed)

| `service` label value | LaunchAgent | Currently shipped? |
|---|---|---|
| `endpoint_nginx` | nginx (Homebrew, not a `com.jarvis.alpha.*` agent) | ⚠️ unconfirmed |
| `endpoint_power_sampler` | com.jarvis.alpha.power.endpoint | ⚠️ unconfirmed |
| `endpoint_rotate` | com.jarvis.alpha.rotate.endpoint | ⚠️ unconfirmed |

### Sandbox (2 services, no shipper)

| `service` label value | LaunchAgent | Currently shipped? |
|---|---|---|
| `sandbox_restore_drill` | com.jarvis.alpha.restore_drill | ❌ no Fluentbit on Sandbox |
| `sandbox_watchdog` | com.jarvis.alpha.watchdog.sandbox | ❌ no Fluentbit on Sandbox |

## 5. Naming convention

**Pattern:** `<node>_<role>` — snake_case, node-prefixed.

**Rationale:**
- Self-documenting (no ambiguity about which node's `app` is which)
- Predictable for autocomplete in Grafana
- Survives label-aggregation queries (`sum by (service)` keeps services distinct even when node is dropped)

**Current emit-vs-target drift:**
The current Python codebase emits values via `get_logger(service)` calls. Observed example: `alpha_brain_access` (sourced from `common/jarvis_common/logging_config.py` callers). This uses an `alpha_` prefix rather than the proposed node-prefix pattern.

**Migration approach:**
- Phase 4c (this session): fix the Fluentbit JSON parser. Labels populate with whatever Python emits today (`alpha_*` pattern). Don't rename Python emit values.
- Future session: audit all `get_logger()` call sites, propose renaming to `<node>_<role>` pattern in a single PR if drift is significant.
- This document's §4 inventory describes the **target** values, not necessarily what's emitted today.

## 6. Current vs target state

| Aspect | Current | Target | Closes |
|---|---|---|---|
| Label `node` | ✅ `brain`, `endpoint` | + `gateway`, `sandbox` | Session 3 fleet extension |
| Label `service` (in Loki) | ❌ all `unknown_service` | Per inventory in §4 | Phase 4c parser fix |
| Label `level` | ❌ Loki shows `detected_level=unknown` | `DEBUG`...`CRITICAL` | Phase 4c parser fix |
| Stream count per node | 1 | ~20 | Phase 4c parser fix |
| JSON parsing in Fluentbit | ❌ missing parser stage | ✅ `json_log` parser | Phase 4c |
| Brain tail coverage | 9 of 14 services | All 14 | Phase 4c-extended or Session 3 |
| Endpoint Fluentbit config | Unaudited | Audited + matches Brain pattern | Session 3 |
| Gateway shipper | Absent | Fluentbit installed + configured | Session 3 |
| Sandbox shipper | Absent | Fluentbit installed + configured | Session 3 |

## 7. Migration path — Phase 4c implementation

Phase 4c is the parser-fix PR. Descriptive steps — the PR refines:

1. Edit `~/jarvis-alpha/fluent-bit/fluent-bit.yaml.template` (the source template that `jarvisalpha_pull.sh` renders):
   - Add a `parsers:` block defining `json_log` (format: `json`, `time_key: ts`, `time_format: %Y-%m-%dT%H:%M:%S.%f%z`)
   - Add `parser: json_log` to each `tail` input
2. Render via `jarvisalpha_pull.sh` on Brain → reload Fluentbit (LaunchAgent restart)
3. Verify within 2 minutes:
   - `curl http://127.0.0.1:3100/loki/api/v1/label/service/values` returns multiple values, not `["unknown_service"]`
   - `curl http://127.0.0.1:3100/loki/api/v1/label/level/values` returns `["INFO", "WARNING", "ERROR", ...]`
4. Update Loki "Brain" Grafana board panels to use `{node="brain", service="brain_app"}` etc. (out of scope for Phase 4c PR; tracked separately)

**Validation criterion:** Loki stream count per node jumps from 1 to ≥10 (the actually-tailed services × levels). Materially less = parser misconfigured or Python emit values don't match label_key expressions.

**Rollback:** revert the YAML change + restart Fluentbit. Pipeline returns to current `unknown_service` state — no data loss, just label regression.

## 8. Anti-patterns

❌ **Don't add labels to "make queries easier."** Queries can use LogQL JSON parsing on body fields. Adding a label is a permanent cardinality decision.

❌ **Don't use timestamp components as labels** (date, hour, weekday). Use Loki's native time range filters.

❌ **Don't label external request fields** (user agent, client IP, host header). These are observed values, not infrastructure facts, and have unbounded cardinality.

❌ **Don't promote a body field to label retroactively** without considering historical cardinality. Once a label exists, all historical streams are indexed.

❌ **Don't ship logs without a node label.** Multi-node mesh + unknown origin = unworkable on-call.

❌ **Don't use `service=brain` or `service=gateway`** when you mean `service=brain_app`. The `node` label already says which node — `service` should disambiguate which process on that node.

## 9. Known gaps (snapshot 2026-05-28)

| Gap | Detail | Tracking |
|---|---|---|
| Brain Fluentbit: missing JSON parser | Root cause of `service_name=unknown_service` | AUDIT-6 Phase 4c |
| Brain: 5 untailed services | temporal trio, pg_backup, rotate pair, school-email, self-logs (fluentbit + loki) | AUDIT-6 extended / Session 3 |
| Endpoint Fluentbit config | Running but config not yet inspected — coverage unverified | AUDIT-6 / Session 3 |
| Gateway shipper | No Fluentbit at all | AUDIT-6 / Session 3 |
| Sandbox shipper | No Fluentbit at all | AUDIT-6 / Session 3 |
| Python emit-value drift | Current `alpha_*` pattern may not match target `<node>_<role>` | Future session |
| Should `env` label exist? | Single-env today; defer until dev/prod split emerges | Open question |

## 10. Future considerations

- **Module extensions:** when jarvis-financial / jarvis-family / jarvis-council come online, extend `service` inventory with `<module>_<role>` pattern (e.g. `financial_trader`, `council_synthesizer`). Each module owns its naming.
- **Multi-env:** if dev vs prod separation emerges, add `env` label — keep cardinality ≤2 values.
- **Cross-node trace correlation:** if needed, expose `trace_id` as Loki structured metadata (via Fluentbit parser's `structured_metadata_keys`), NOT as a label. Preserves query power without cardinality blow-up.
- **Migration to jarvis-standards:** once this schema is stable for 2+ sessions without changes, move this document to jarvis-standards as the canonical taxonomy. Update GAP_v2 and any consumers.
- **Grafana dashboard regeneration:** post-Phase 4c, all panels using `{job="..."}` or `{service_name="unknown_service"}` need rewriting to `{service="..."}` patterns. Track as separate work.
