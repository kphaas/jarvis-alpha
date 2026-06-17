# Spark Restore Drill Evidence - 2026-06-17

Status: pass, Spark-scoped metadata drill
Owner: Ken
Runner: Codex on Air, live checks against Brain
Scope: Spark outbox restore surface and personality approval repo state

## Evidence

| Check | Result |
|---|---|
| Brain Alpha HEAD | `b419afa` |
| Brain personality HEAD | `a6c6c18` |
| Latest Alpha backup | `2026-06-17T06:30:05Z`, status `ok`, 3 DBs, 15,256,931 bytes |
| Spark outbox rows | 6 |
| Spark outbox event rows | 14 |
| Spark outbox status counts | `send_failed=4`, `pending_approval=2` |
| Spark outbox event counts | `created=6`, `sending=4`, `send_failed=4` |
| Outbox RLS | `alpha_spark_outbox` and `alpha_spark_outbox_events` both `ENABLE` + `FORCE` |
| Outbox event immutability | `trg_alpha_spark_outbox_events_immutable` enabled |
| Outbox SECDEF helpers | `create_spark_outbox_item`, `list_spark_outbox_items`, `get_spark_outbox_item_for_send`, `record_spark_outbox_event` all SECURITY DEFINER |
| SQL decrypt helper count | 0 |

## Notes

- This was a Spark-scoped production-readiness drill, not the full `restore_drill_alpha.sh` Unraid-to-ephemeral-Postgres disaster-recovery drill.
- No raw iMessage bodies or plaintext draft text were queried or recorded.
- The current live outbox has no `sent` rows from this hardening pass; failed historical attempts remain auditable as `send_failed` events.
- Full Alpha restore drills remain covered by `scripts/restore_drill_alpha.sh`; this note records Spark-specific backup/restore evidence for the parent-minor context hardening pass.
