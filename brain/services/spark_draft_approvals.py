"""Approval queue helpers for Spark draft proposals."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

import asyncpg

from brain.services.spark_imessage_drafts import SparkDraftProposal

SPARK_DRAFT_APPROVAL_ACTION_CLASSES = (
    "spark_draft_handoff",
    "imessage_send",
    "security_write",
)
SPARK_DRAFT_APPROVAL_TIER = "T4"


async def enqueue_spark_draft_approval(
    conn: asyncpg.Connection,
    *,
    proposal: SparkDraftProposal,
    actor_sub: str,
    actor_type: str,
    nonce: str,
) -> UUID:
    """Queue a Spark draft approval without storing draft text."""

    parameters_hash = spark_draft_parameters_hash(proposal)
    description = spark_draft_approval_description(proposal)
    try:
        queue_id = await conn.fetchval(
            """
            SELECT public.enqueue_approval_request(
                $1::text[], $2, $3, $4, $5, $6, $7
            )
            """,
            list(SPARK_DRAFT_APPROVAL_ACTION_CLASSES),
            SPARK_DRAFT_APPROVAL_TIER,
            actor_sub,
            actor_type,
            description,
            parameters_hash,
            nonce,
        )
    except asyncpg.UniqueViolationError:
        existing_id = await conn.fetchval(
            """
            SELECT id
            FROM public.alpha_approval_queue
            WHERE actor_sub = $1
              AND parameters_hash = $2
              AND status = 'pending'
            LIMIT 1
            """,
            actor_sub,
            parameters_hash,
        )
        if existing_id is None:
            raise
        return existing_id

    if queue_id is None:
        raise RuntimeError("enqueue_approval_request returned no queue id")
    return queue_id


def spark_draft_parameters_hash(proposal: SparkDraftProposal) -> str:
    payload = proposal.to_payload()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def spark_draft_approval_description(proposal: SparkDraftProposal) -> str:
    payload = proposal.to_payload()
    context_count = int(payload["context_messages_read"])
    sent_count = int(payload["principal_sent_messages"])
    runtime_count = int(payload["runtime_context_messages"])
    return (
        "Spark iMessage approved-send request "
        f"({context_count} context, {sent_count} sent, {runtime_count} runtime)"
    )
