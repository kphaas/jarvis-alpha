"""
chat.py — OpenAI-compatible streaming chat endpoint + thread management.

Routes:
  POST /v1/chat/completions   streaming SSE ask (main UI endpoint)
  GET  /v1/threads            list threads for current user
  PATCH /v1/threads/{id}      rename thread title
  DELETE /v1/threads/{id}     soft-delete (archive) thread
  POST /v1/threads/{id}/escalate  promote to overnight TaskGraph
"""

import json
import re
import time
import asyncio
import httpx
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID, uuid4, uuid5, NAMESPACE_DNS
from typing import AsyncGenerator, Literal
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from brain.core.config import OLLAMA_URL
from brain.core.models import EMBED_MODEL, LOCAL_CHAT
from brain.db.pool import get_pool
from brain.db.rls import rls_connection
from brain.memory.memory import MemoryService
from brain.memory.semantic_commands import (
    MemoryFactValidationError,
    memory_save_response_text,
    parse_memory_command,
)
from brain.middleware.scopes import check_scopes
from brain.routing.router import route
from brain.services.at0_self_model import build_at0_self_model, is_at0_self_query
from brain.services.internet_scout.chat_adapter import (
    InternetChatContext,
    build_chat_internet_context,
)
from brain.services.internet_scout.models import Sensitivity
from brain.services.internet_scout.repository import InternetScoutRepository
from brain.services.internet_scout.web_suggestion import (
    WebSuggestion,
    WebSuggestionConfidence,
    WebSuggestionMode,
    suggest_web_for_chat,
)
from jarvis_common.logging_config import get_logger

router = APIRouter(tags=["chat"])
logger = get_logger("alpha_brain")

MAX_PERSONAL_THREADS = 30
MAX_PROJECT_THREADS = 15
THREAD_CAP_RETENTION_DAYS = 30
THREAD_CAP_ACTIVE_FILTER = (
    "archived_at IS NULL "
    f"AND (pinned = TRUE OR updated_at >= now() - INTERVAL '{THREAD_CAP_RETENTION_DAYS} days')"
)
InternetMode = Literal["none", "web_search", "deep_research"]
AskResponseSurface = Literal["chat", "voice", "avatar"]
AskPersonalityId = Literal[
    "loyal_sidekick",
    "playful_buddy",
    "calm_operator",
    "brave_droid",
    "sleepy_soft",
    "sarcastic_witty",
]
BEACON_INSUFFICIENT_MODEL = "beacon/insufficient-evidence"
MEMORY_COMMAND_MODEL = "alpha/memory-command"
BEACON_INTERNET_AUTHORITY_RULE = "\n".join(
    [
        "Authority rule for internet-enabled answers:",
        "- Treat accepted Alpha Beacon evidence as the source of truth for "
        "current/public web claims.",
        "- This includes official-source, URL, citation, release, pricing, "
        "legal, medical, market, schedule, and other time-sensitive claims.",
        "- Use memory only for stable personal preferences or local context.",
        "- Do not use memory to override, replace, or contradict Beacon evidence.",
        "- If memory conflicts with Beacon, follow Beacon and ignore the "
        "conflicting memory.",
    ]
)
WEB_SUGGESTION_BOUNDARY_RULE = "\n".join(
    [
        "Smart Web Suggestion boundary:",
        "- Alpha suggested web research for this turn, but Beacon internet "
        "search has not run yet.",
        "- Do not claim that Alpha Beacon verified the answer, crawled the "
        "web, or used internet evidence.",
        "- For schedules, scores, fixtures, kickoff times, opponents, live "
        "status, current rankings, rosters, or future event dates, do not answer "
        "from memory or local model knowledge. Say Beacon/web verification is "
        "needed.",
        "- If answering from memory or local model knowledge, label the answer "
        "as unverified and invite the user to enable the suggested web mode.",
    ]
)


# ── Pydantic models ────────────────────────────────────────────────────────────


class WebSuggestionAcceptance(BaseModel):
    suggested_mode: WebSuggestionMode
    reason: str | None = Field(default=None, max_length=120)
    confidence: WebSuggestionConfidence | None = None
    source: str = Field(default="alpha_smart_web_suggestion", max_length=120)
    requires_confirmation: bool = True


class CompletionRequest(BaseModel):
    messages: list[dict]
    model: str = Field(
        default="auto", description="auto|local|claude|gemini|perplexity|council"
    )
    council_models: list[str] = Field(
        default=[], description="models for council mode e.g. ['claude','gemini']"
    )
    thread_id: str | None = None
    project_id: int | None = None
    stream: bool = True
    show_council: bool = False
    internet_mode: InternetMode = Field(
        default="none", description="none|web_search|deep_research"
    )
    response_surface: AskResponseSurface = Field(
        default="chat", description="chat|voice|avatar"
    )
    personality_id: AskPersonalityId | None = Field(
        default=None,
        description="Bounded AT-0 personality style selected by Helm.",
    )
    web_suggestion_acceptance: WebSuggestionAcceptance | None = Field(
        default=None,
        description="Client confirmation that a prior Smart Web Suggestion was accepted.",
    )


class ThreadPatch(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class EscalateRequest(BaseModel):
    reason: str | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────


def _user_id(request: Request) -> str:
    return getattr(request.state, "user_id", "anon")


def _is_child_actor(request: Request) -> bool:
    role = str(getattr(request.state, "role", "") or "").lower()
    child_age = getattr(request.state, "child_age", None)
    return role in {"child", "minor"} or child_age is not None


def _internet_sensitivity(request: Request) -> Sensitivity:
    return "minor" if _is_child_actor(request) else "normal"


def _build_enriched_prompt(
    *,
    memory_context: str,
    internet_context: str | None,
    web_suggestion_context: str | None = None,
    at0_self_context: str | None = None,
    response_surface: AskResponseSurface | None = None,
    personality_id: AskPersonalityId | None = None,
    user_msg: str,
) -> str:
    response_style_context = _response_style_prompt(
        response_surface=response_surface,
        personality_id=personality_id,
    )
    if (
        not memory_context
        and not internet_context
        and not web_suggestion_context
        and not at0_self_context
        and not response_style_context
    ):
        return user_msg

    parts: list[str] = []
    if internet_context:
        parts.append(BEACON_INTERNET_AUTHORITY_RULE)
        parts.append(
            "Internet context from Alpha Beacon "
            "(authoritative for current/public web claims):\n"
            f"{internet_context}"
        )
        if memory_context:
            parts.append(
                "Context from memory "
                "(secondary; must not override Beacon evidence):\n"
                f"{memory_context}"
            )
    elif web_suggestion_context:
        parts.append(WEB_SUGGESTION_BOUNDARY_RULE)
        parts.append(web_suggestion_context)
        if memory_context:
            parts.append(
                "Context from memory "
                "(unverified for current/public web claims):\n"
                f"{memory_context}"
            )
    elif memory_context:
        parts.append(f"Context from memory:\n{memory_context}")
    if at0_self_context:
        parts.append(at0_self_context)
    if response_style_context:
        parts.append(response_style_context)
    parts.append(f"User: {user_msg}")
    return "\n\n".join(parts)


def _web_suggestion_prompt_context(suggestion: WebSuggestion | None) -> str | None:
    if not suggestion:
        return None
    return "\n".join(
        [
            "Suggested web action:",
            f"- Mode: {suggestion.mode}",
            f"- Reason: {suggestion.reason}",
            f"- Requires user confirmation: {suggestion.requires_confirmation}",
        ]
    )


PERSONALITY_STYLE_PROMPTS: dict[AskPersonalityId, str] = {
    "loyal_sidekick": (
        "Loyal Sidekick: warm, steady, and useful. Treat Ken like the person "
        "you are working alongside; no stiff system-status wording."
    ),
    "playful_buddy": (
        "Playful Buddy: bright and lightly playful, but still concise. Use a "
        "little human warmth without turning the answer into a bit."
    ),
    "calm_operator": (
        "Calm Operator: quiet, direct, and operational. Lead with the answer, "
        "then the one detail that matters."
    ),
    "brave_droid": (
        "Brave Droid: upbeat and mission-ready. Keep confidence high without "
        "sounding mechanical."
    ),
    "sleepy_soft": (
        "Sleepy Soft: gentle, slower, and cozy. Short sentences, no pressure."
    ),
    "sarcastic_witty": (
        "Sarcastic Witty: dry and quick, but never dismissive. One light aside "
        "is enough."
    ),
}


def _response_style_prompt(
    *,
    response_surface: AskResponseSurface | None,
    personality_id: AskPersonalityId | None,
) -> str | None:
    surface = response_surface or "chat"
    style = PERSONALITY_STYLE_PROMPTS.get(personality_id) if personality_id else None
    if not style and surface == "chat":
        return None

    lines = [
        "AT-0 interaction style:",
        "- Ken may call you Otto, Auto, AT-0, or JARVIS. Treat those as valid "
        "references in casual use; do not correct him. Prefer AT-0, Otto, or "
        "Auto in user-facing replies; treat JARVIS as the private infrastructure "
        "name unless Ken asks about that system.",
        "- Convert ISO timestamps, dates, and weather observation times into "
        "natural spoken language. Do not read raw values like 2026-06-18T17:00 "
        "unless Ken asks for the exact machine timestamp.",
        "- For weather and quick current-status answers, do not start with "
        "'According to'. Start with the answer, then cite the source after the "
        "useful part if a citation is needed.",
    ]
    if surface == "voice":
        lines.append(
            "- Surface: Voice. Use one or two short spoken paragraphs. No markdown "
            "headings unless Ken explicitly asks for a structured list."
        )
    elif surface == "avatar":
        lines.append(
            "- Surface: Avatar. Keep it brief and spoken; the avatar is the UI, "
            "so do not narrate interface sections."
        )
    else:
        lines.append(
            "- Surface: Chat. Keep the answer scannable, but avoid robotic preambles."
        )
    if style:
        lines.append(f"- Personality: {style}")
    return "\n".join(lines)


def _should_short_circuit_internet_response(
    internet_context: InternetChatContext | None,
) -> bool:
    if not internet_context:
        return False
    return (
        internet_context.source_quality.status == "insufficient"
        or internet_context.source_quality.accepted_citation_count <= 0
        or internet_context.citation_count <= 0
    )


def _insufficient_beacon_response(context: InternetChatContext) -> str:
    if context.source_quality.official_source_required:
        return (
            "Beacon did not find an accepted official source for this request, "
            "so I cannot answer it as verified."
        )
    return (
        "Beacon did not find acceptable trusted internet evidence for this request, "
        "so I cannot answer it as verified."
    )


def _internet_sse_metadata(
    *,
    context: InternetChatContext,
    thread_id: str,
) -> dict[str, object]:
    payload = _internet_message_metadata(context)
    payload["thread_id"] = thread_id
    payload["done"] = False
    return payload


def _internet_message_metadata(
    context: InternetChatContext,
) -> dict[str, object]:
    return {
        "internet_mode": context.mode,
        "internet_request_id": str(context.request_id),
        "internet_selected_tool": context.selected_tool.value,
        "internet_citation_count": context.citation_count,
        "internet_source_quality_status": context.source_quality.status,
        "internet_accepted_citation_count": (
            context.source_quality.accepted_citation_count
        ),
        "internet_rejected_citation_count": (
            context.source_quality.rejected_citation_count
        ),
        "internet_official_source_count": context.source_quality.official_source_count,
        "internet_verified_claim_count": context.source_quality.verified_claim_count,
        "internet_unsupported_claim_count": (
            context.source_quality.unsupported_claim_count
        ),
        "internet_prompt_injection_rejection_count": (
            context.source_quality.prompt_injection_rejection_count
        ),
        "internet_official_source_required": (
            context.source_quality.official_source_required
        ),
        **_internet_research_metadata(context),
        **_internet_synthesis_metadata(context),
        **_internet_memory_boundary_metadata(context),
        **_internet_research_report_metadata(context),
        "raw_web_content_is_untrusted": context.raw_web_content_is_untrusted,
        "citations": _redacted_internet_citations(context),
    }


def _internet_research_metadata(
    context: InternetChatContext,
) -> dict[str, object]:
    plan = context.research_plan
    return {
        "internet_research_plan_id": plan.plan_id,
        "internet_research_intent": plan.intent,
        "internet_research_search_count": len(plan.searches),
        "internet_research_subquestion_count": len(plan.subquestions),
        "internet_research_search_budget": plan.max_searches,
        "internet_research_provider_strategy": plan.provider_strategy,
        "internet_research_search_providers": plan.search_providers,
        "internet_research_max_extracts": plan.max_extracts,
        "internet_research_authority_required": plan.authority_required,
        "internet_research_freshness_required": plan.freshness_required,
        "internet_research_primary_source_required": plan.primary_source_required,
        "internet_research_expected_source_types": plan.expected_source_types,
        "internet_research_query_purposes": [query.purpose for query in plan.searches],
        "internet_research_required_query_purposes": [
            query.purpose for query in plan.searches if query.required
        ],
        "internet_research_stop_criteria": plan.stop_criteria.model_dump(mode="json"),
    }


def _internet_synthesis_metadata(
    context: InternetChatContext,
) -> dict[str, object]:
    synthesis = context.synthesis
    return {
        "internet_synthesis_answerable": synthesis.answerable,
        "internet_synthesis_status": synthesis.status,
        "internet_synthesis_citation_count": synthesis.citation_count,
        "internet_synthesis_minimum_citations_met": synthesis.minimum_citations_met,
        "internet_synthesis_required_behavior": synthesis.required_behavior,
    }


def _internet_memory_boundary_metadata(
    context: InternetChatContext,
) -> dict[str, object]:
    boundary = context.memory_boundary
    return {
        "internet_memory_context_priority": boundary.memory_context_priority,
        "internet_automatic_memory_write_allowed": (
            boundary.automatic_memory_write_allowed
        ),
        "internet_memory_promotion_review_required": (
            boundary.promotion_review_required
        ),
        "internet_memory_promotion_route": boundary.promotion_route,
    }


def _internet_research_report_metadata(
    context: InternetChatContext,
) -> dict[str, object]:
    report = context.research_report
    return {
        "internet_research_report_plan_id": report.plan_id,
        "internet_research_report_source_quality_status": report.source_quality_status,
        "internet_research_report_answerability": report.answerability,
        "internet_research_report_cited_source_count": report.cited_source_count,
        "internet_research_report_accepted_citation_count": (
            report.accepted_citation_count
        ),
        "internet_research_report_rejected_citation_count": (
            report.rejected_citation_count
        ),
        "internet_research_report_verified_claim_count": report.verified_claim_count,
        "internet_research_report_unsupported_claim_count": (
            report.unsupported_claim_count
        ),
        "internet_research_report_independent_source_count": (
            report.independent_source_count
        ),
        "internet_research_report_source_diversity_score": (
            report.source_diversity_score
        ),
        "internet_research_report_planned_query_count": report.planned_query_count,
        "internet_research_report_contradiction_count": report.contradiction_count,
        "internet_research_report_contradictions": report.contradictions,
        "internet_research_report_source_hosts": report.source_hosts,
        "internet_research_report_required_source_hosts": (
            report.required_source_hosts
        ),
        "internet_research_report_expected_source_types": report.expected_source_types,
        "internet_research_report_subquestion_count": report.subquestion_count,
        "internet_research_report_coverage_warnings": report.coverage_warnings,
        "internet_research_report_source_rankings": [
            ranking.model_dump(mode="json") for ranking in report.source_rankings[:10]
        ],
    }


def _web_suggestion_message_metadata(
    suggestion: WebSuggestion | None,
) -> dict[str, object] | None:
    return suggestion.to_metadata() if suggestion else None


def _web_suggestion_sse_metadata(
    *,
    suggestion: WebSuggestion,
    thread_id: str,
) -> dict[str, object]:
    payload = suggestion.to_metadata()
    payload["thread_id"] = thread_id
    payload["done"] = False
    return payload


def _web_suggestion_acceptance_metadata(
    *,
    acceptance: WebSuggestionAcceptance,
    requested_mode: InternetMode,
    thread_id: str,
) -> dict[str, object]:
    return {
        "accepted": True,
        "source": acceptance.source,
        "suggested_mode": acceptance.suggested_mode,
        "requested_mode": requested_mode,
        "reason": acceptance.reason,
        "confidence": acceptance.confidence,
        "requires_confirmation": acceptance.requires_confirmation,
        "thread_id": thread_id,
    }


def _redacted_internet_citations(
    context: InternetChatContext,
) -> list[dict[str, object]]:
    citations: list[dict[str, object]] = []
    for citation in context.citations[:10]:
        source_url = citation.source_url
        if not source_url:
            continue
        payload: dict[str, object] = {"source_url": source_url}
        if citation.host:
            payload["host"] = citation.host
        if citation.content_hash:
            payload["content_hash"] = citation.content_hash
        if citation.claim:
            payload["claim"] = citation.claim
        payload["confidence"] = citation.confidence
        payload["source_quality"] = citation.source_quality
        if citation.source_rank is not None:
            payload["source_rank"] = citation.source_rank
        if citation.source_score:
            payload["source_score"] = citation.source_score
        if citation.quality_reasons:
            payload["quality_reasons"] = citation.quality_reasons
        citations.append(payload)
    return citations


def _decode_json_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, dict):
            return {str(key): item for key, item in decoded.items()}
    return {}


def _chat_message_from_row(row: Mapping[str, object]) -> dict[str, object]:
    payload = dict(row)
    internet_metadata = _decode_json_object(payload.pop("internet_metadata", None))
    for key in (
        "internet_mode",
        "internet_request_id",
        "internet_selected_tool",
        "internet_citation_count",
        "internet_source_quality_status",
        "internet_accepted_citation_count",
        "internet_rejected_citation_count",
        "internet_official_source_count",
        "internet_verified_claim_count",
        "internet_unsupported_claim_count",
        "internet_prompt_injection_rejection_count",
        "internet_official_source_required",
        "internet_research_plan_id",
        "internet_research_intent",
        "internet_research_search_count",
        "internet_research_subquestion_count",
        "internet_research_search_budget",
        "internet_research_provider_strategy",
        "internet_research_search_providers",
        "internet_research_max_extracts",
        "internet_research_authority_required",
        "internet_research_freshness_required",
        "internet_research_primary_source_required",
        "internet_research_expected_source_types",
        "internet_research_query_purposes",
        "internet_research_required_query_purposes",
        "internet_research_stop_criteria",
        "internet_synthesis_answerable",
        "internet_synthesis_status",
        "internet_synthesis_citation_count",
        "internet_synthesis_minimum_citations_met",
        "internet_synthesis_required_behavior",
        "internet_memory_context_priority",
        "internet_automatic_memory_write_allowed",
        "internet_memory_promotion_review_required",
        "internet_memory_promotion_route",
        "internet_research_report_plan_id",
        "internet_research_report_source_quality_status",
        "internet_research_report_answerability",
        "internet_research_report_cited_source_count",
        "internet_research_report_accepted_citation_count",
        "internet_research_report_rejected_citation_count",
        "internet_research_report_verified_claim_count",
        "internet_research_report_unsupported_claim_count",
        "internet_research_report_independent_source_count",
        "internet_research_report_source_diversity_score",
        "internet_research_report_planned_query_count",
        "internet_research_report_contradiction_count",
        "internet_research_report_contradictions",
        "internet_research_report_source_hosts",
        "internet_research_report_required_source_hosts",
        "internet_research_report_expected_source_types",
        "internet_research_report_subquestion_count",
        "internet_research_report_coverage_warnings",
        "internet_research_report_source_rankings",
        "raw_web_content_is_untrusted",
        "citations",
        "web_suggestion_mode",
        "web_suggestion_reason",
        "web_suggestion_confidence",
        "web_suggestion_query",
        "web_suggestion_requires_confirmation",
        "web_suggestion_source",
    ):
        if key in internet_metadata:
            payload[key] = internet_metadata[key]
    return payload


async def _embed(text: str) -> list[float]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text},
            )
            r.raise_for_status()
            return r.json()["embedding"]
    except Exception:
        return []


async def _get_or_create_thread(
    request: Request,
    user_id: str,
    thread_id: str | None,
    project_id: int | None,
) -> str:
    async with rls_connection(request) as conn:
        if thread_id:
            row = await conn.fetchrow(
                "SELECT id FROM chat_threads WHERE id=$1 AND user_id=$2 AND archived_at IS NULL",
                UUID(thread_id),
                user_id,
            )
            if row:
                return str(row["id"])

        if project_id:
            count = await conn.fetchval(
                f"""SELECT COUNT(*) FROM chat_threads
                   WHERE user_id=$1 AND project_id=$2 AND {THREAD_CAP_ACTIVE_FILTER}""",
                user_id,
                project_id,
            )
            if count >= MAX_PROJECT_THREADS:
                raise HTTPException(
                    409,
                    detail=f"thread_limit: Max {MAX_PROJECT_THREADS} threads per project",
                )
        else:
            count = await conn.fetchval(
                f"""SELECT COUNT(*) FROM chat_threads
                   WHERE user_id=$1 AND project_id IS NULL AND {THREAD_CAP_ACTIVE_FILTER}""",
                user_id,
            )
            if count >= MAX_PERSONAL_THREADS:
                raise HTTPException(
                    409,
                    detail=f"thread_limit: Max {MAX_PERSONAL_THREADS} personal threads",
                )

        new_id = uuid4()
        await conn.execute(
            """INSERT INTO chat_threads (id, user_id, project_id)
               VALUES ($1, $2, $3)""",
            new_id,
            user_id,
            project_id,
        )
        return str(new_id)


async def _save_message(
    request: Request,
    thread_id: str,
    user_id: str,
    role: str,
    content: str,
    model_used: str | None = None,
    council_detail: dict | None = None,
    memory_injected: bool = False,
    latency_ms: int | None = None,
    internet_metadata: dict[str, object] | None = None,
) -> None:
    async with rls_connection(request) as conn:
        await conn.execute(
            """INSERT INTO chat_messages
               (thread_id, role, content, model_used, council_detail, memory_injected, latency_ms, internet_metadata)
               VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8::jsonb)""",
            UUID(thread_id),
            role,
            content,
            model_used,
            json.dumps(council_detail) if council_detail else None,
            memory_injected,
            latency_ms,
            json.dumps(internet_metadata) if internet_metadata else None,
        )
        await conn.execute(
            "UPDATE chat_threads SET updated_at=now(), model_used=$1 WHERE id=$2",
            model_used,
            UUID(thread_id),
        )


async def _record_web_suggestion_acceptance(
    *,
    request: Request,
    context: InternetChatContext,
    acceptance: WebSuggestionAcceptance,
    requested_mode: InternetMode,
    thread_id: str,
) -> None:
    metadata = _web_suggestion_acceptance_metadata(
        acceptance=acceptance,
        requested_mode=requested_mode,
        thread_id=thread_id,
    )
    try:
        async with rls_connection(request) as conn:
            await InternetScoutRepository(conn).record_tool_event(
                request_id=context.request_id,
                tool=context.selected_tool.value,
                event_type="chat_web_suggestion_acceptance",
                status="succeeded",
                metadata=metadata,
            )
    except Exception:
        logger.warning(
            "BEACON_CHAT_WEB_SUGGESTION_ACCEPTANCE_EVENT_FAIL",
            extra={
                "event": "BEACON_CHAT_WEB_SUGGESTION_ACCEPTANCE_EVENT_FAIL",
                "request_id": str(context.request_id),
            },
        )
        return

    logger.info(
        "BEACON_CHAT_WEB_SUGGESTION_ACCEPTED",
        extra={
            "event": "BEACON_CHAT_WEB_SUGGESTION_ACCEPTED",
            "request_id": str(context.request_id),
            "suggested_mode": acceptance.suggested_mode,
            "requested_mode": requested_mode,
            "reason": acceptance.reason,
            "confidence": acceptance.confidence,
        },
    )


async def _auto_name_thread(
    request: Request,
    thread_id: str,
    user_id: str,
    first_prompt: str,
) -> None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": LOCAL_CHAT,
                    "prompt": (
                        f"Generate a 3-5 word title for a conversation that starts with: "
                        f'"{first_prompt[:200]}". '
                        "Reply with ONLY the title. No quotes, no punctuation at end."
                    ),
                    "stream": False,
                },
            )
            title = r.json().get("response", "").strip()[:80]
            if title:
                async with rls_connection(request) as conn:
                    await conn.execute(
                        "UPDATE chat_threads SET title=$1, updated_at=now() WHERE id=$2",
                        title,
                        UUID(thread_id),
                    )
    except Exception:
        pass


# ── SSE streaming ──────────────────────────────────────────────────────────────

JARVIS_SYSTEM_PROMPT = (
    "You are AT-0, Ken's private AI companion in Helm, backed by the JARVIS/Alpha "
    "self-hosted infrastructure owned by Kenneth Haas. The system runs on three "
    "core nodes: Brain (Mac Studio M2 Ultra, orchestrator), Gateway (Mac Mini, "
    "internet egress), and Endpoint (Mac Mini M1, UI). You are not a cloud "
    "service; you are a private, self-hosted system. Use AT-0 as your "
    "user-facing name. Otto and Auto are accepted casual pronunciations or "
    "spellings. JARVIS is the infrastructure and legacy backend identity; do "
    "not introduce yourself as JARVIS unless Ken specifically asks about JARVIS. "
    "Always answer as AT-0. Be direct, concise, and technically precise, "
    "but use a natural spoken voice when the user is in Ask or Voice mode. "
    "Sound like a capable operator talking to Ken: calm, specific, lightly warm, "
    "and comfortable using contractions. Avoid robotic preambles, excessive section "
    "labels, and compliance-style phrasing unless the topic truly needs it. "
    "Do not say things like 'functioning within normal parameters', 'please note', "
    "or 'as a private AI assistant' in everyday voice answers. "
    "If Ken calls you Otto, Auto, AT-0, or JARVIS, accept the name as yours and "
    "do not correct him in casual conversation. "
    "When citing weather, dates, or observed timestamps, say them naturally for "
    "a human listener instead of reading raw ISO timestamps. "
    "For voice-friendly answers, prefer one to three short paragraphs, name the "
    "answer first, and put caveats after the useful part. "
    "When memory context is provided, use it for stable personal context. "
    "When Alpha Beacon internet context is provided, treat accepted Beacon evidence "
    "as authoritative for current/public web claims. For date-specific sports, "
    "events, schedules, scores, news, prices, releases, and other current or "
    "future public facts, do not rely on local model memory. If Beacon internet "
    "context is not provided, say the answer needs Beacon/web verification "
    "instead of guessing."
)


def _runtime_context_prompt() -> str:
    now = datetime.now().astimezone()
    hour = now.strftime("%I").lstrip("0") or "0"
    minute = now.strftime("%M")
    meridiem = now.strftime("%p")
    timestamp = (
        f"{now.strftime('%A, %B')} {now.day}, {now.year} "
        f"at {hour}:{minute} {meridiem} {now.tzname() or ''}".strip()
    )
    return (
        f"Runtime context: current local time is {timestamp}. "
        "Use this only to phrase dates and times naturally when relevant."
    )


def _polish_model_response(text: str, response_surface: AskResponseSurface) -> str:
    if response_surface not in {"voice", "avatar"}:
        return text

    polished = text.strip()
    if not polished:
        return polished

    replacements = [
        (
            r"(?i)\baccording to Open-Meteo,\s*which is a reliable source for current weather conditions,\s*",
            "Open-Meteo has it as ",
        ),
        (r"(?i)\baccording to Open-Meteo,\s*", "Open-Meteo has it as "),
        (
            r"(?i),?\s*which is a reliable source for current weather conditions",
            "",
        ),
        (
            r"(?i)\bfeeling like ([0-9]+)\s*F\b",
            r"feeling like \1 degrees",
        ),
    ]
    for pattern, replacement in replacements:
        polished = re.sub(pattern, replacement, polished)

    sentence_removals = [
        r"(?is)(^|(?<=[.!?])\s+)Please note that\b.*?(?:[.!?](?:\s+|$)|$)",
        r"(?is)(^|(?<=[.!?])\s+)Keep in mind that\b.*?(?:[.!?](?:\s+|$)|$)",
        r"(?is)(^|(?<=[.!?])\s+)Now,\s+about the weather\b.*?(?:[.!?](?:\s+|$)|$)",
        r"(?is)(^|(?<=[.!?])\s+)First,\s+let'?s check on your voice test\b.*?(?:[.!?](?:\s+|$)|$)",
    ]
    for pattern in sentence_removals:
        polished = re.sub(pattern, " ", polished)

    polished = re.sub(
        r"(?i)\bEverything sounds clear and crisp to me\.\s*You're good to go!",
        "Mic sounds clear.",
        polished,
    )
    polished = re.sub(r"\s+\[Cited source:\s*([0-9]+)\]", r" [\1]", polished)
    polished = re.sub(r"(?is)\s+Please note that\b.*$", "", polished)
    polished = re.sub(r"(?is)\s+Keep in mind that\b.*$", "", polished)
    polished = re.sub(r"\s{2,}", " ", polished).strip()
    return polished or text.strip()


async def _stream_single(
    prompt: str,
    mode: str,
    thread_id: str,
    model_label: str,
    response_surface: AskResponseSurface = "chat",
) -> AsyncGenerator[str, None]:
    """Stream tokens from router → SSE events."""
    jarvis_prompt = f"{JARVIS_SYSTEM_PROMPT}\n\n{_runtime_context_prompt()}\n\n{prompt}"
    result = await route(jarvis_prompt, mode)
    text = _polish_model_response(result.get("result", ""), response_surface)
    model_used = result.get("mode", mode)

    words = text.split(" ")
    for i, word in enumerate(words):
        chunk = word + (" " if i < len(words) - 1 else "")
        event = json.dumps(
            {
                "delta": chunk,
                "model": model_used,
                "thread_id": thread_id,
                "done": False,
            }
        )
        yield f"data: {event}\n\n"
        await asyncio.sleep(0.01)

    yield f"data: {json.dumps({'delta': '', 'model': model_used, 'thread_id': thread_id, 'done': True})}\n\n"
    yield "data: [DONE]\n\n"


async def _stream_deterministic_response(
    *,
    text: str,
    model_label: str,
    thread_id: str,
) -> AsyncGenerator[str, None]:
    words = text.split(" ")
    for i, word in enumerate(words):
        chunk = word + (" " if i < len(words) - 1 else "")
        yield f"data: {json.dumps({'delta': chunk, 'model': model_label, 'thread_id': thread_id, 'done': False})}\n\n"
        await asyncio.sleep(0.01)

    yield f"data: {json.dumps({'delta': '', 'model': model_label, 'thread_id': thread_id, 'done': True})}\n\n"
    yield "data: [DONE]\n\n"


async def _stream_council(
    prompt: str, models: list[str], thread_id: str, show_council: bool
) -> AsyncGenerator[str, None]:
    """Parallel council calls → optional per-model stream → synthesis."""
    tasks = {m: asyncio.create_task(route(prompt, m)) for m in models}
    results = {}
    for m, task in tasks.items():
        try:
            results[m] = await task
        except Exception as e:
            results[m] = {"result": f"[{m} error: {e}]", "mode": m}

    if show_council:
        for m, res in results.items():
            meta = json.dumps(
                {"council_model": m, "thread_id": thread_id, "done": False}
            )
            yield f"data: {meta}\n\n"
            for word in res.get("result", "").split(" "):
                chunk = json.dumps(
                    {"delta": word + " ", "council_model": m, "thread_id": thread_id}
                )
                yield f"data: {chunk}\n\n"
                await asyncio.sleep(0.005)

    council_text = "\n\n".join(
        f"[{m.upper()}]: {r.get('result', '')}" for m, r in results.items()
    )
    synth_prompt = (
        f"Synthesize these responses into one clear answer:\n\n{council_text}\n\n"
        f"Original question: {prompt}"
    )
    synth_result = await route(synth_prompt, "local")
    synth_text = synth_result.get("result", "")

    council_summary = {m: r.get("result", "") for m, r in results.items()}
    for word in synth_text.split(" "):
        chunk = json.dumps(
            {
                "delta": word + " ",
                "model": "council/synthesis",
                "thread_id": thread_id,
                "done": False,
                "council_detail": council_summary,
            }
        )
        yield f"data: {chunk}\n\n"
        await asyncio.sleep(0.01)

    yield f"data: {json.dumps({'delta': '', 'model': 'council/synthesis', 'thread_id': thread_id, 'done': True, 'council_detail': council_summary})}\n\n"
    yield "data: [DONE]\n\n"


def _append_sse_delta(delta_parts: list[str], chunk: str) -> None:
    if not chunk.startswith("data: ") or "[DONE]" in chunk:
        return
    line = chunk[6:].strip()
    if not line:
        return
    try:
        payload = json.loads(line)
        if not payload.get("done") and "delta" in payload:
            delta_parts.append(str(payload.get("delta", "")))
    except json.JSONDecodeError:
        pass


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.post("/v1/chat/completions")
async def chat_completions(body: CompletionRequest, request: Request):
    start = time.monotonic()
    user_id = _user_id(request)
    user_msg = next(
        (m["content"] for m in reversed(body.messages) if m.get("role") == "user"), ""
    )

    try:
        memory_command = parse_memory_command(user_msg)
    except MemoryFactValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc

    if memory_command is not None:
        check_scopes(request, "memory.write", "admin")

    memory = MemoryService()
    thread_id = await _get_or_create_thread(
        request, user_id, body.thread_id, body.project_id
    )

    if memory_command is not None:
        uid = uuid5(NAMESPACE_DNS, user_id)
        async with rls_connection(request) as conn:
            result = await memory.save_semantic(
                conn=conn,
                user_id=uid,
                fact=memory_command.fact,
                category=memory_command.category,
                provenance={
                    "source_surface": "at0_chat",
                    "source_route": "/v1/chat/completions",
                    "source_thread_id": thread_id,
                    "source_action": "slash_memory_command",
                    "request_model": body.model,
                    "actor_type": str(
                        getattr(request.state, "actor_type", "user") or "user"
                    ),
                    "actor_role": str(getattr(request.state, "role", "user") or "user"),
                },
            )
        result_text = memory_save_response_text(
            saved=bool(result.get("saved")),
            category=memory_command.category,
            reason=result.get("reason"),
            review_required=result.get("review_required"),
        )
        await _save_message(request, thread_id, user_id, "user", user_msg)

        async def _memory_command_generator():
            async for chunk in _stream_deterministic_response(
                text=result_text,
                model_label=MEMORY_COMMAND_MODEL,
                thread_id=thread_id,
            ):
                yield chunk
            latency = int((time.monotonic() - start) * 1000)
            await _save_message(
                request,
                thread_id,
                user_id,
                "assistant",
                result_text,
                model_used=MEMORY_COMMAND_MODEL,
                memory_injected=False,
                latency_ms=latency,
            )

        return StreamingResponse(
            _memory_command_generator(),
            media_type="text/event-stream",
        )

    embedding = await _embed(user_msg)
    uid = uuid5(NAMESPACE_DNS, user_id)

    async with rls_connection(request) as conn:
        context = await memory.build_context(
            conn=conn,
            user_id=uid,
            prompt=user_msg,
            session_id=thread_id,
            embedding=embedding,
            principal_id=user_id,
        )
    memory_injected = bool(context)
    sensitivity = _internet_sensitivity(request)
    at0_self_requested = is_at0_self_query(user_msg)
    web_suggestion = (
        None
        if at0_self_requested
        else suggest_web_for_chat(
            query=user_msg,
            internet_mode=body.internet_mode,
            sensitivity=sensitivity,
        )
    )
    if web_suggestion:
        logger.info(
            "BEACON_CHAT_WEB_SUGGESTION_SHOWN",
            extra={
                "event": "BEACON_CHAT_WEB_SUGGESTION_SHOWN",
                "thread_id": thread_id,
                "suggested_mode": web_suggestion.mode,
                "reason": web_suggestion.reason,
                "confidence": web_suggestion.confidence,
            },
        )
    internet_context: InternetChatContext | None = None
    if body.internet_mode != "none":
        internet_context = await build_chat_internet_context(
            request=request,
            query=user_msg,
            mode=body.internet_mode,
            sensitivity=sensitivity,
        )
        if body.web_suggestion_acceptance:
            await _record_web_suggestion_acceptance(
                request=request,
                context=internet_context,
                acceptance=body.web_suggestion_acceptance,
                requested_mode=body.internet_mode,
                thread_id=thread_id,
            )
    at0_self_context: str | None = None
    if at0_self_requested:
        try:
            async with rls_connection(request) as conn:
                at0_self = await build_at0_self_model(conn)
            at0_self_context = at0_self.prompt_context
        except Exception as exc:
            logger.warning(
                "AT0_SELF_CONTEXT_UNAVAILABLE",
                extra={
                    "event": "AT0_SELF_CONTEXT_UNAVAILABLE",
                    "thread_id": thread_id,
                    "error_type": type(exc).__name__,
                },
            )
            at0_self_context = (await build_at0_self_model(None)).prompt_context
    enriched = _build_enriched_prompt(
        memory_context=context,
        internet_context=internet_context.prompt_context if internet_context else None,
        web_suggestion_context=(
            _web_suggestion_prompt_context(web_suggestion)
            if web_suggestion and not internet_context
            else None
        ),
        at0_self_context=at0_self_context,
        response_surface=body.response_surface,
        personality_id=body.personality_id,
        user_msg=user_msg,
    )

    await _save_message(request, thread_id, user_id, "user", user_msg)

    is_new = body.thread_id is None
    if is_new:
        asyncio.create_task(_auto_name_thread(request, thread_id, user_id, user_msg))

    delta_parts: list[str] = []

    async def _generator():
        if web_suggestion:
            payload = _web_suggestion_sse_metadata(
                suggestion=web_suggestion,
                thread_id=thread_id,
            )
            yield f"data: {json.dumps(payload)}\n\n"

        if internet_context:
            payload = _internet_sse_metadata(
                context=internet_context,
                thread_id=thread_id,
            )
            yield f"data: {json.dumps(payload)}\n\n"

        if _should_short_circuit_internet_response(internet_context):
            assert internet_context is not None
            deterministic_text = _insufficient_beacon_response(internet_context)
            logger.info(
                "BEACON_ASK_INSUFFICIENT_SHORT_CIRCUIT",
                extra={
                    "event": "BEACON_ASK_INSUFFICIENT_SHORT_CIRCUIT",
                    "request_id": str(internet_context.request_id),
                    "source_quality_status": internet_context.source_quality.status,
                    "accepted_citation_count": (
                        internet_context.source_quality.accepted_citation_count
                    ),
                    "rejected_citation_count": (
                        internet_context.source_quality.rejected_citation_count
                    ),
                },
            )
            async for chunk in _stream_deterministic_response(
                text=deterministic_text,
                model_label=BEACON_INSUFFICIENT_MODEL,
                thread_id=thread_id,
            ):
                yield chunk

            latency = int((time.monotonic() - start) * 1000)
            await _save_message(
                request,
                thread_id,
                user_id,
                "assistant",
                deterministic_text,
                model_used=BEACON_INSUFFICIENT_MODEL,
                memory_injected=False,
                latency_ms=latency,
                internet_metadata=_internet_message_metadata(internet_context),
            )
            return

        is_council = body.model == "council" or len(body.council_models) >= 2
        models = body.council_models if body.council_models else [body.model]

        if is_council:
            gen = _stream_council(enriched, models, thread_id, body.show_council)
        else:
            gen = _stream_single(
                enriched,
                body.model,
                thread_id,
                body.model,
                response_surface=body.response_surface,
            )

        async for chunk in gen:
            _append_sse_delta(delta_parts, chunk)
            yield chunk

        latency = int((time.monotonic() - start) * 1000)
        full_text = "".join(delta_parts)
        model_label = "council/synthesis" if is_council else body.model
        council_raw = None

        asyncio.create_task(
            _save_message(
                request,
                thread_id,
                user_id,
                "assistant",
                full_text,
                model_used=model_label,
                council_detail=council_raw,
                memory_injected=memory_injected,
                latency_ms=latency,
                internet_metadata=(
                    _internet_message_metadata(internet_context)
                    if internet_context
                    else _web_suggestion_message_metadata(web_suggestion)
                ),
            )
        )
        asyncio.create_task(_store_memory_bg(uid, thread_id, full_text))

    return StreamingResponse(_generator(), media_type="text/event-stream")


async def _store_memory_bg(uid, thread_id, full_text):
    pool = get_pool()
    memory = MemoryService()
    async with pool.acquire() as conn:
        await memory.store(
            conn=conn,
            user_id=uid,
            session_id=thread_id,
            summary=full_text,
            role="assistant",
            embedding=await _embed(full_text),
            persistent=False,
        )


@router.get("/v1/threads")
async def list_threads(request: Request):
    user_id = _user_id(request)
    rows = []
    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            """SELECT id, title, mode, model_used, project_id, pinned, created_at, updated_at
               FROM chat_threads
               WHERE user_id=$1 AND archived_at IS NULL
               ORDER BY updated_at DESC LIMIT 50""",
            user_id,
        )
    return [dict(r) for r in rows]


@router.patch("/v1/threads/{thread_id}")
async def rename_thread(thread_id: str, body: ThreadPatch, request: Request):
    user_id = _user_id(request)
    title = body.title.strip()[:80] if body.title is not None else None
    if title == "":
        raise HTTPException(400, "Thread title cannot be blank")
    if title is None and body.pinned is None:
        raise HTTPException(400, "Thread patch requires title or pinned")

    set_clauses = ["updated_at=now()"]
    values: list[object] = []
    if title is not None:
        values.append(title)
        set_clauses.append(f"title=${len(values)}")
    if body.pinned is not None:
        values.append(body.pinned)
        set_clauses.append(f"pinned=${len(values)}")
    values.extend([UUID(thread_id), user_id])
    thread_id_param = len(values) - 1
    user_id_param = len(values)

    result = ""
    async with rls_connection(request) as conn:
        result = await conn.execute(
            f"""UPDATE chat_threads
               SET {", ".join(set_clauses)}
               WHERE id=${thread_id_param} AND user_id=${user_id_param}""",
            *values,
        )
    if result == "UPDATE 0":
        raise HTTPException(404, "Thread not found")
    return {"ok": True}


@router.delete("/v1/threads/{thread_id}")
async def archive_thread(thread_id: str, request: Request):
    if _is_child_actor(request):
        raise HTTPException(403, "child_thread_delete_denied")

    user_id = _user_id(request)
    result = ""
    async with rls_connection(request) as conn:
        result = await conn.execute(
            "UPDATE chat_threads SET archived_at=now() WHERE id=$1 AND user_id=$2",
            UUID(thread_id),
            user_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(404, "Thread not found")
    return {"ok": True}


@router.get("/v1/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str, request: Request):
    rows = []
    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            """SELECT id, role, content, model_used, council_detail,
                      memory_injected, latency_ms, internet_metadata, created_at
               FROM chat_messages
               WHERE thread_id=$1
               ORDER BY created_at ASC""",
            UUID(thread_id),
        )
    return [_chat_message_from_row(row) for row in rows]


@router.post("/v1/threads/{thread_id}/escalate")
async def escalate_to_overnight(
    thread_id: str, body: EscalateRequest, request: Request
):
    user_id = _user_id(request)
    created_by_uuid = uuid5(NAMESPACE_DNS, user_id)
    graph_id = uuid4()
    async with rls_connection(request) as conn:
        async with conn.transaction():
            thread = await conn.fetchrow(
                "SELECT title FROM chat_threads WHERE id=$1 AND user_id=$2",
                UUID(thread_id),
                user_id,
            )
            if not thread:
                raise HTTPException(404, "Thread not found")

            messages = await conn.fetch(
                "SELECT role, content FROM chat_messages WHERE thread_id=$1 ORDER BY created_at ASC",
                UUID(thread_id),
            )
            context_summary = "\n".join(
                f"{r['role']}: {r['content'][:300]}" for r in messages[-10:]
            )

            await conn.execute(
                """INSERT INTO alpha_task_graphs
                   (id, title, status, created_by, metadata)
                   VALUES ($1, $2, 'pending', $3, $4::jsonb)""",
                graph_id,
                f"Overnight: {thread['title']}",
                created_by_uuid,
                json.dumps(
                    {
                        "source": "chat_escalation",
                        "thread_id": thread_id,
                        "reason": body.reason,
                        "context_summary": context_summary,
                    }
                ),
            )
            await conn.execute(
                "UPDATE chat_threads SET mode='overnight', updated_at=now() WHERE id=$1",
                UUID(thread_id),
            )

    return {"ok": True, "task_graph_id": str(graph_id)}
