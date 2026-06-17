# Spark Approved-Send Gate Security Review - 2026-06-17

Status: pass with one operational note
Owner: Ken
Scope: `/v1/spark/drafts/imessage/outbox/{outbox_id}/send`

## Findings

| Area | Result |
|---|---|
| Default draft posture | `can_send=false`, `requires_human_approval=true` |
| Send endpoint scopes | Requires `spark.draft` and `imessage.send` |
| Outbox lookup | Sends only from persisted outbox via `get_spark_outbox_item_for_send` |
| Approval gate | Rejects unless approval status is `approved` |
| Tamper check | Rejects when outbox `approval_parameters_hash` differs from approval row hash |
| Target binding | Resolves chat GUID only from approved iMessage source records and matching target hash |
| Plaintext storage | Draft text is app-encrypted; metadata lists do not return ciphertext or plaintext |
| SQL decrypt helpers | None present in `public` schema |
| Event trail | Records `sending`, `sent`, and `send_failed` in append-only outbox events |
| Approval consumption | Approval is consumed only after a successful send event |
| Tests | `tests/services/test_spark_outbox_send.py`, `tests/services/test_spark_outbox.py`, `tests/test_spark_drafts_route.py`, `tests/test_spark_outbox_schema.py`, `tests/test_spark_outbox_send_schema.py` |

## Operational Note

- Live metadata currently shows 4 historical `send_failed` outbox attempts and 2 `pending_approval` outbox items. This review did not send an iMessage.
- The gate is safe to keep disabled for autonomous sending. Human-approved send resume should still require an operator review of the pending item and the approval queue state before any live send.
