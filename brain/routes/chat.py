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
from typing import AsyncGenerator, Literal, cast
from fastapi import APIRouter, Request, HTTPException, Query
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
from brain.services.chat_evaluation_harness import chat_eval_payload
from brain.services.chat_evidence_pack import (
    ChatEscalationDecision,
    ChatEvidencePack,
    ChatQualityGateDecision,
    ChatResponseVerification,
    evaluate_chat_quality_gate,
    plan_chat_escalation,
    verify_chat_response,
)
from brain.services.chat_memory_pack import (
    ChatMemoryPackManifest,
    pack_chat_memory_context,
)
from brain.services.chat_prompt_compiler import (
    ChatPromptManifest,
    compile_chat_prompt,
)
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
from brain.services.memory_web_policy import (
    should_prefer_memory_over_web_suggestion as _should_prefer_memory_over_web_suggestion,
    should_short_circuit_web_suggestion as _should_short_circuit_web_suggestion,
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
AgentWorkSearchSource = Literal["agent_run", "board_item", "handoff", "pull_request"]
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
AT0_SELF_MODEL_LABEL = "alpha/at0-self-model"
CONVERSATION_QUALITY_MODEL_LABEL = "alpha/conversation-quality-contract"
COUNCIL_DETAIL_SCHEMA_VERSION = "chat_council_detail.v2"
COUNCIL_DETAIL_RESPONSE_MAX_CHARS = 2000
CHAT_OUTCOME_SCHEMA_VERSION = "chat_outcome.v1"
ROLLING_CONTEXT_MAX_MESSAGES = 8
ROLLING_CONTEXT_MESSAGE_CHAR_LIMIT = 420
CHAT_STRATEGY_METADATA_KEYS = (
    "chat_strategy",
    "chat_route_mode",
    "chat_model_path",
    "chat_strategy_reason",
)
CHAT_OUTCOME_METADATA_KEYS = (
    "chat_outcome_schema_version",
    "chat_outcome_model_label",
    "chat_outcome_strategy",
    "chat_outcome_route_mode",
    "chat_outcome_model_path",
    "chat_outcome_strategy_reason",
    "chat_outcome_verified",
    "chat_outcome_issue_count",
    "chat_outcome_quality_action",
    "chat_outcome_quality_passed",
    "chat_outcome_quality_reason",
    "chat_outcome_fallback_used",
    "chat_outcome_escalation_required",
    "chat_outcome_escalation_rung",
    "chat_outcome_escalation_action",
    "chat_outcome_escalation_requires_confirmation",
    "chat_outcome_evidence_count",
    "chat_memory_pack_schema_version",
    "chat_memory_pack_source_chars",
    "chat_memory_pack_packed_chars",
    "chat_memory_pack_budget_chars",
    "chat_memory_pack_source_line_count",
    "chat_memory_pack_packed_line_count",
    "chat_memory_pack_dropped_line_count",
    "chat_memory_pack_section_order",
    "chat_memory_pack_current_line_count",
    "chat_memory_pack_historical_line_count",
    "chat_memory_pack_needs_refresh_line_count",
    "chat_memory_pack_truncated",
    "chat_prompt_schema_version",
    "chat_prompt_section_order",
    "chat_prompt_user_message_chars",
    "chat_prompt_compiled_chars",
    "chat_prompt_memory_used",
    "chat_prompt_internet_used",
    "chat_prompt_web_suggestion_used",
    "chat_prompt_at0_self_used",
    "chat_prompt_conversation_used",
    "chat_prompt_raw_web_content_is_untrusted",
    "chat_prompt_memory_context_priority",
    "chat_prompt_response_style_used",
    "chat_prompt_tool_policy",
)
BEACON_INTERNET_AUTHORITY_RULE = "\n".join(
    [
        "Beacon authority rule:",
        "- Treat accepted Beacon evidence as the source of truth for "
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
        "- Alpha suggested web research for this turn, but Beacon has not run yet.",
        "- Do not claim that Beacon verified the answer, crawled the "
        "web, or used internet evidence.",
        "- For schedules, scores, fixtures, kickoff times, opponents, live "
        "status, current rankings, rosters, or future event dates, do not answer "
        "from memory or local model knowledge. Say Beacon/web verification is "
        "needed.",
        "- If the user is only asking how to use AT-0, Helm, Beacon, web search, "
        "voice, or avatar mode, explain the local workflow instead of treating it "
        "as a current public web claim.",
        "- If answering a current/public fact from memory or local model knowledge, "
        "say Beacon verification is needed.",
    ]
)
SOURCE_LINK_REQUEST_RE = re.compile(
    r"\b("
    r"sources?|citations?|cites?|references?|links?|urls?|websites?|"
    r"web\s+sites?|documentation|docs?|source\s+url|website\s+link"
    r")\b",
    re.IGNORECASE,
)
NEGATIVE_SOURCE_LINK_REQUEST_RE = re.compile(
    r"\b(?:do\s+not|don't|dont|no|without|skip|hide)\b"
    r"[^.!?\n]{0,40}\b(?:sources?|citations?|links?|urls?|websites?)\b",
    re.IGNORECASE,
)
RAW_URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(https?://[^\s)]+\)")
INLINE_SOURCE_URL_RE = re.compile(
    r"(?i)\s*(?:Citation:\s*)?(?:\[(?:\d+(?:\s*,\s*\d+)*)\]\s*)?"
    r"Source:\s*https?://[^\s)\]>\"']+"
)
SOURCE_LINE_RE = re.compile(
    r"(?im)^\s*(?:sources?|citations?|references?|websites?|links?)\s*:.*(?:\n|$)"
)
BRACKET_CITATION_RE = re.compile(r"\s*\[(?:\d+(?:\s*,\s*\d+)*)\]")
LEADING_MARKDOWN_HEADING_RE = re.compile(
    r"(?s)^\s*(?:#{1,6}\s+[^\n]{1,80}\n+|\*\*[A-Z][^*\n]{3,80}\*\*\s*:?\s*)"
)
UNSUPPORTED_BEACON_ASSERTION_RE = re.compile(
    r"(?is)(^|(?<=[.!?])\s+)"
    r"(?:"
    r"Beacon\s+(?:checked|verified|confirmed|found|says|has)\b.*?"
    r"|I(?:'ve| have)\s+(?:checked|verified|confirmed|found)\b.*?\bBeacon\b.*?"
    r")"
    r"(?:[.!?](?:\s+|$)|$)"
)
UNREQUESTED_BEACON_NARRATION_RE = re.compile(
    r"(?is)(^|(?<=[.!?])\s+)"
    r"(?:"
    r"Beacon(?:\s+(?:evidence|research|search|web|results?)){0,3}\s+"
    r"(?:checked|verified|confirmed|found|supports?|supported|used|looked\s+up|cross-checked)\b.*?"
    r"|This\s+is\s+supported\s+by\s+Beacon\b.*?"
    r"|(?:The\s+)?evidence\s+from\s+Beacon\b.*?"
    r"|I(?:'ve| have)\s+(?:checked|verified|confirmed|found)\b.*?\bBeacon\b.*?"
    r"|(?:Through|Using)\s+Beacon\b.*?"
    r")"
    r"(?:[.!?](?:\s+|$)|$)"
)
CONVERSATION_QUALITY_REQUEST_RE = re.compile(
    r"\b(?:conversation|conversational|chat|voice|tone|robotic|human|natural)\b"
    r"(?s:.){0,120}"
    r"\b(?:improve|better|quality|less\s+robotic|more\s+human|more\s+natural|"
    r"near[-\s]+real[-\s]+time|real[-\s]+time|latency|faster)\b"
    r"|"
    r"\b(?:improve|better|quality|less\s+robotic|more\s+human|more\s+natural|"
    r"near[-\s]+real[-\s]+time|real[-\s]+time|latency|faster|speed\s+up)\b"
    r"(?s:.){0,120}"
    r"\b(?:conversation|conversational|chat|voice|voice\s+response|"
    r"spoken\s+response|tts|tone|robotic|human|natural)\b",
    re.IGNORECASE,
)
UNSUPPORTED_CONVERSATION_OPS_RE = re.compile(
    r"(?is)(^|(?<=[.!?])\s+)"
    r"(?:"
    r"[^.!?]{0,160}\b(?:Beacon\s+update|update\s+(?:my\s+)?models?|"
    r"refresh\s+(?:my\s+)?models?|latest\s+natural\s+language\s+processing|"
    r"\bNLP\b|dialogue\s+management\s+techniques|latest\s+version\s+of\s+macOS|"
    r"update\s+macOS|standard\s+procedure\s+for\s+system\s+updates)\b[^.!?]*"
    r")"
    r"(?:[.!?](?:\s+|$)|$)"
)
ROBOTIC_VOICE_REPLACEMENTS = (
    (
        re.compile(r"(?i)\bI am functioning within normal parameters\b"),
        "I'm ready",
    ),
    (
        re.compile(r"(?i)\bas a private AI assistant,?\s*"),
        "",
    ),
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


class SessionSearchSnippet(BaseModel):
    message_id: str
    role: str
    snippet: str
    created_at: datetime


class SessionSearchResult(BaseModel):
    thread_id: str
    title: str | None = None
    mode: str | None = None
    model_used: str | None = None
    project_id: int | None = None
    pinned: bool
    message_count: int
    matched_message_count: int
    last_message_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    snippets: list[SessionSearchSnippet] = Field(default_factory=list)


class AgentWorkSearchResult(BaseModel):
    source: AgentWorkSearchSource
    id: str
    title: str
    status: str | None = None
    role: str | None = None
    agent_id: str | None = None
    workspace_id: str | None = None
    task_graph_id: str | None = None
    url: str | None = None
    snippet: str
    created_at: datetime
    updated_at: datetime | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class SessionSearchResponse(BaseModel):
    query: str
    count: int
    source: Literal["chat_sessions"] = "chat_sessions"
    memory_searched: bool = False
    results: list[SessionSearchResult] = Field(default_factory=list)
    work_result_count: int = 0
    work_results: list[AgentWorkSearchResult] = Field(default_factory=list)


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
    conversation_context: str | None = None,
    response_surface: AskResponseSurface | None = None,
    personality_id: AskPersonalityId | None = None,
    user_msg: str,
) -> str:
    response_style_context = _response_style_prompt(
        response_surface=response_surface,
        personality_id=personality_id,
    )
    compiled = compile_chat_prompt(
        user_msg=user_msg,
        memory_context=memory_context,
        internet_context=internet_context,
        web_suggestion_context=web_suggestion_context,
        at0_self_context=at0_self_context,
        conversation_context=conversation_context,
        response_style_context=response_style_context,
        beacon_authority_rule=BEACON_INTERNET_AUTHORITY_RULE,
        web_suggestion_boundary_rule=WEB_SUGGESTION_BOUNDARY_RULE,
    )
    return compiled.prompt


def _message_text(
    value: object, *, limit: int = ROLLING_CONTEXT_MESSAGE_CHAR_LIMIT
) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", " ", value).strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit].rstrip()}..."


def _conversation_context_from_messages(messages: list[dict]) -> str | None:
    latest_user_index: int | None = None
    for index, message in enumerate(messages):
        if str(message.get("role", "")).lower() == "user":
            latest_user_index = index

    if latest_user_index is None or latest_user_index <= 0:
        return None

    lines: list[str] = []
    for message in messages[:latest_user_index]:
        role = str(message.get("role", "")).lower()
        if role not in {"user", "assistant"}:
            continue
        content = _message_text(message.get("content"))
        if not content:
            continue
        speaker = "Ken" if role == "user" else "AT-0"
        lines.append(f"{speaker}: {content}")

    if not lines:
        return None
    return "\n".join(lines[-ROLLING_CONTEXT_MAX_MESSAGES:])


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
            "- Surface: Voice. Default to one or two conversational sentences. "
            "Keep normal answers under 45 words unless Ken asks for detail. "
            "Answer like a quick back-and-forth, not a report. No markdown, "
            "bullets, headings, source names, or long setup unless Ken "
            "explicitly asks."
        )
    elif surface == "avatar":
        lines.append(
            "- Surface: Avatar. Use the briefest spoken version, usually under "
            "35 words. The avatar is the UI, so do not narrate interface "
            "sections, chat history, or visible controls."
        )
    else:
        lines.append(
            "- Surface: Chat. Give the fuller useful answer. Be grounded and "
            "specific, use short sections or bullets when they help, and include "
            "tradeoffs or next steps when relevant. Do not invent backend updates, "
            "model training, macOS updates, Beacon work, dates, versions, or "
            "project status unless explicit context supports them."
        )
    if style:
        lines.append(f"- Personality: {style}")
    return "\n".join(lines)


def _conversation_quality_response(
    user_msg: str,
    response_surface: AskResponseSurface,
) -> str | None:
    if not CONVERSATION_QUALITY_REQUEST_RE.search(user_msg):
        return None
    if response_surface == "voice":
        return (
            "Best path: separate chat and voice contracts, then test real turns "
            "for tone, grounding, word count, and latency. We tune prompts, "
            "memory, Beacon routing, and TTS from those failures."
        )
    if response_surface == "avatar":
        return (
            "Use separate contracts: detailed chat, brief voice, and minimal "
            "avatar. Then tune from real conversation evals."
        )
    return (
        "The best path is eval-driven, not random prompt tweaking.\n\n"
        "- Chat should be fuller: grounded, structured, and useful, with bullets "
        "or sections when they help.\n"
        "- Voice should be short and conversational: one or two sentences, no "
        "headings, no lists, and fewer caveats unless you ask.\n"
        "- Avatar should be even tighter: the avatar is the focus, so the answer "
        "should feel spoken rather than like chat history.\n"
        "- Personality should shape tone and pacing, while safety, memory, and "
        "Beacon rules stay consistent.\n"
        "- Regression tests should score tone, hallucination, word count, bad "
        "robotic phrases, source leakage, and current-fact routing.\n\n"
        "Unsupported infrastructure-update claims should stay out unless there "
        "is explicit operational work that actually supports them."
    )


def _web_verification_required_response(
    suggestion: WebSuggestion,
    response_surface: AskResponseSurface,
) -> str:
    if response_surface == "voice":
        return "I need to check the web before I answer that. Turn on Web search for this one and I’ll give you the verified time."
    if suggestion.reason == "sports_schedule_likely":
        return "I need to check the web before I answer that. Use Web search for this one and I’ll give you the verified time."
    return (
        "I need to verify that before I answer. Use Web search and I’ll keep it tight."
    )


def _at0_self_quick_response(
    user_msg: str,
    response_surface: AskResponseSurface,
) -> str | None:
    if response_surface not in {"voice", "avatar"}:
        return None

    normalized = " ".join(user_msg.lower().split())
    personal_context_requested = re.search(
        r"\b(?:what do you know about me|do you know (?:things|anything) about me|"
        r"remember|memory|about me)\b",
        normalized,
    )
    capability_requested = re.search(
        r"\b(?:what can you do|what you can do|what you can't do|"
        r"what you can’t do|current capabilit(?:y|ies)|capabilit(?:y|ies)|"
        r"modes?|yourself)\b",
        normalized,
    )
    if personal_context_requested and capability_requested:
        return (
            "I can chat, listen and speak, show up as the avatar, use approved "
            "memory for stable context about you, and use web search to verify "
            "current public facts before I claim them."
        )
    if personal_context_requested:
        return (
            "I can use approved memory for stable context about you, your "
            "projects, preferences, and household basics. I keep that minimal, "
            "and I still need web verification for current public facts."
        )
    if re.search(r"\b(?:search|browse|web|internet|beacon)\b", normalized):
        return (
            "Turn on Web search when you want current facts checked. For sports "
            "times, I’ll verify first instead of guessing."
        )
    if re.search(r"\b(?:voice|talk|speak|hear|listen)\b", normalized):
        return (
            "Voice mode listens through Helm, transcribes your turn, then speaks "
            "back using the personality voice you picked."
        )
    if re.search(
        r"\b(?:who are you|what are you|jarvis|otto|auto|at-?0|yourself)\b",
        normalized,
    ):
        return (
            "I’m AT-0, your Helm chat, voice, and avatar companion. JARVIS/Alpha "
            "is the private system behind me, not the name I should lead with."
        )
    return (
        "I can chat, listen and speak, show up as the avatar, use approved memory "
        "for stable context, check current facts with web search, and work with "
        "approved Alpha summaries."
    )


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


def _chat_strategy_sse_metadata(
    result: Mapping[str, object],
    thread_id: str,
) -> dict[str, object] | None:
    payload = {key: result[key] for key in CHAT_STRATEGY_METADATA_KEYS if key in result}
    if not payload:
        return None
    payload["thread_id"] = thread_id
    payload["done"] = False
    return payload


def _chat_evidence_sse_metadata(
    *,
    evidence_pack: ChatEvidencePack,
    thread_id: str,
) -> dict[str, object]:
    payload = evidence_pack.to_metadata()
    payload["thread_id"] = thread_id
    payload["done"] = False
    return payload


def _chat_memory_pack_sse_metadata(
    *,
    manifest: ChatMemoryPackManifest,
    thread_id: str,
) -> dict[str, object]:
    payload = manifest.to_metadata()
    payload["thread_id"] = thread_id
    payload["done"] = False
    return payload


def _chat_prompt_manifest_sse_metadata(
    *,
    manifest: ChatPromptManifest,
    thread_id: str,
) -> dict[str, object]:
    payload = manifest.to_metadata()
    payload["thread_id"] = thread_id
    payload["done"] = False
    return payload


def _chat_response_verification_sse_metadata(
    *,
    verification: ChatResponseVerification,
    thread_id: str,
) -> dict[str, object]:
    payload = verification.to_metadata()
    payload["thread_id"] = thread_id
    payload["done"] = False
    return payload


def _chat_quality_gateway_sse_metadata(
    *,
    decision: ChatQualityGateDecision,
    thread_id: str,
) -> dict[str, object]:
    payload = decision.to_metadata()
    payload["thread_id"] = thread_id
    payload["done"] = False
    return payload


def _chat_escalation_sse_metadata(
    *,
    decision: ChatEscalationDecision,
    thread_id: str,
) -> dict[str, object]:
    payload = decision.to_metadata()
    payload["thread_id"] = thread_id
    payload["done"] = False
    return payload


def _chat_council_detail_sse_metadata(
    *,
    council_detail: dict[str, object],
    thread_id: str,
) -> dict[str, object]:
    return {
        "chat_council_detail_schema_version": COUNCIL_DETAIL_SCHEMA_VERSION,
        "chat_council_detail": council_detail,
        "thread_id": thread_id,
        "done": False,
    }


def _chat_outcome_message_metadata(
    *,
    model_label: str,
    route_result: Mapping[str, object],
    verification: ChatResponseVerification,
    gate: ChatQualityGateDecision,
    escalation: ChatEscalationDecision,
    memory_pack_manifest: ChatMemoryPackManifest | None = None,
    prompt_manifest: ChatPromptManifest | None = None,
) -> dict[str, object]:
    verification_metadata = verification.to_metadata()
    gate_metadata = gate.to_metadata()
    escalation_metadata = escalation.to_metadata()
    metadata = {
        "chat_outcome_schema_version": CHAT_OUTCOME_SCHEMA_VERSION,
        "chat_outcome_model_label": model_label,
        "chat_outcome_strategy": route_result.get("chat_strategy"),
        "chat_outcome_route_mode": route_result.get("chat_route_mode")
        or route_result.get("mode"),
        "chat_outcome_model_path": route_result.get("chat_model_path"),
        "chat_outcome_strategy_reason": route_result.get("chat_strategy_reason"),
        "chat_outcome_verified": verification_metadata["chat_response_verified"],
        "chat_outcome_issue_count": verification_metadata["chat_response_issue_count"],
        "chat_outcome_quality_action": gate_metadata["chat_quality_action"],
        "chat_outcome_quality_passed": gate_metadata["chat_quality_passed"],
        "chat_outcome_quality_reason": gate_metadata["chat_quality_reason"],
        "chat_outcome_fallback_used": gate_metadata["chat_quality_fallback_used"],
        "chat_outcome_escalation_required": escalation_metadata[
            "chat_escalation_required"
        ],
        "chat_outcome_escalation_rung": escalation_metadata["chat_escalation_rung"],
        "chat_outcome_escalation_action": escalation_metadata["chat_escalation_action"],
        "chat_outcome_escalation_requires_confirmation": escalation_metadata[
            "chat_escalation_requires_user_confirmation"
        ],
        "chat_outcome_evidence_count": verification_metadata[
            "chat_response_evidence_count"
        ],
    }
    if memory_pack_manifest:
        metadata.update(memory_pack_manifest.to_metadata())
    if prompt_manifest:
        metadata.update(prompt_manifest.to_metadata())
    return metadata


def _merge_chat_outcome_metadata(
    existing: dict[str, object] | None,
    outcome: dict[str, object],
) -> dict[str, object] | None:
    if not existing and not outcome:
        return None
    return {**(existing or {}), **outcome}


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
    payload["council_detail"] = (
        _decode_json_object(payload.get("council_detail")) or None
    )
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
        *CHAT_OUTCOME_METADATA_KEYS,
    ):
        if key in internet_metadata:
            payload[key] = internet_metadata[key]
    return payload


def _chat_outcome_from_row(row: Mapping[str, object]) -> dict[str, object]:
    metadata = _decode_json_object(row.get("internet_metadata"))
    council_detail = _decode_json_object(row.get("council_detail"))
    payload = {
        "message_id": str(row.get("message_id")),
        "thread_id": str(row.get("thread_id")),
        "thread_title": row.get("thread_title"),
        "model_used": row.get("model_used"),
        "created_at": row.get("created_at"),
        "used_council": bool(council_detail),
    }
    for key in CHAT_OUTCOME_METADATA_KEYS:
        if key in metadata:
            payload[key] = metadata[key]
    if council_detail:
        payload["council_schema_version"] = council_detail.get("schema_version")
        payload["council_model_count"] = council_detail.get("model_count")
    return payload


def _decode_json_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(decoded, list):
            return decoded
    return []


def _normalize_session_search_query(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip()


def _session_snippet(content: object, query: str, limit: int = 240) -> str:
    cleaned = re.sub(r"\s+", " ", str(content or "")).strip()
    if len(cleaned) <= limit:
        return cleaned

    match_index = cleaned.lower().find(query.lower())
    if match_index < 0:
        return f"{cleaned[:limit].rstrip()}..."

    start = max(0, match_index - (limit // 3))
    end = min(len(cleaned), start + limit)
    start = max(0, end - limit)
    prefix = "..." if start else ""
    suffix = "..." if end < len(cleaned) else ""
    return f"{prefix}{cleaned[start:end].strip()}{suffix}"


def _session_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _session_optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return _session_datetime(value)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _can_search_agent_work(request: Request) -> bool:
    actor_type = getattr(request.state, "actor_type", "user")
    role = getattr(request.state, "role", None)
    caller_scopes = set(getattr(request.state, "scopes", []) or [])
    if actor_type == "user" and role == "admin":
        return True
    return bool({"*", "agents.read", "agent_board.read"} & caller_scopes)


def _session_search_result_from_row(
    row: Mapping[str, object],
    query: str,
) -> SessionSearchResult:
    payload = dict(row)
    snippets: list[SessionSearchSnippet] = []
    for item in _decode_json_list(payload.get("snippets")):
        if not isinstance(item, Mapping):
            continue
        snippets.append(
            SessionSearchSnippet(
                message_id=str(item.get("message_id")),
                role=str(item.get("role")),
                snippet=_session_snippet(item.get("content"), query),
                created_at=_session_datetime(item.get("created_at")),
            )
        )

    project_id = payload.get("project_id")
    return SessionSearchResult(
        thread_id=str(payload["thread_id"]),
        title=_optional_str(payload.get("title")),
        mode=_optional_str(payload.get("mode")),
        model_used=_optional_str(payload.get("model_used")),
        project_id=project_id if isinstance(project_id, int) else None,
        pinned=bool(payload["pinned"]),
        message_count=int(payload["message_count"]),
        matched_message_count=int(payload["matched_message_count"]),
        last_message_at=_session_optional_datetime(payload.get("last_message_at")),
        created_at=_session_datetime(payload["created_at"]),
        updated_at=_session_datetime(payload["updated_at"]),
        snippets=snippets,
    )


def _agent_work_search_source(value: object) -> AgentWorkSearchSource:
    source = str(value)
    allowed = {"agent_run", "board_item", "handoff", "pull_request"}
    if source not in allowed:
        raise ValueError(f"unknown agent work search source: {source}")
    return cast(AgentWorkSearchSource, source)


def _work_search_result_from_row(
    row: Mapping[str, object],
    query: str,
) -> AgentWorkSearchResult:
    payload = dict(row)
    return AgentWorkSearchResult(
        source=_agent_work_search_source(payload["source"]),
        id=str(payload["id"]),
        title=str(payload["title"]),
        status=_optional_str(payload.get("status")),
        role=_optional_str(payload.get("role")),
        agent_id=_optional_str(payload.get("agent_id")),
        workspace_id=_optional_str(payload.get("workspace_id")),
        task_graph_id=_optional_str(payload.get("task_graph_id")),
        url=_optional_str(payload.get("url")),
        snippet=_session_snippet(payload.get("snippet_text"), query),
        created_at=_session_datetime(payload["created_at"]),
        updated_at=_session_optional_datetime(payload.get("updated_at")),
        metadata=_decode_json_object(payload.get("metadata")),
    )


async def _search_agent_work(
    conn: object,
    *,
    query_pattern: str,
    normalized_query: str,
    limit: int,
) -> list[AgentWorkSearchResult]:
    run_rows = await conn.fetch(
        """
        SELECT 'agent_run' AS source,
               r.id::text AS id,
               COALESCE(a.display_name, r.agent_id) || ' run' AS title,
               r.status,
               NULL::text AS role,
               r.agent_id,
               NULLIF(r.metadata->>'workspace_id', '') AS workspace_id,
               NULL::text AS task_graph_id,
               COALESCE(
                   NULLIF(r.metadata->>'pr_url', ''),
                   NULLIF(r.metadata#>>'{github,pr_url}', ''),
                   NULLIF(r.metadata#>>'{executor_bridge,pr_url}', '')
               ) AS url,
               concat_ws(
                   ' ',
                   r.agent_id,
                   a.display_name,
                   r.status,
                   r.trigger_type,
                   r.trace_id,
                   r.error_text,
                   r.workspace_root,
                   r.metadata::text
               ) AS snippet_text,
               r.created_at,
               COALESCE(r.completed_at, r.started_at, r.created_at) AS updated_at,
               jsonb_build_object(
                   'trigger_type', r.trigger_type,
                   'trace_id', r.trace_id,
                   'cost_usd', r.cost_usd,
                   'workspace_backend', r.workspace_backend,
                   'workspace_root', r.workspace_root,
                   'retention_class', r.retention_class,
                   'approval_scope', r.approval_scope
               ) AS metadata
          FROM public.alpha_agent_runs r
          LEFT JOIN public.alpha_agents a ON a.agent_id = r.agent_id
         WHERE r.agent_id ILIKE $1
            OR r.status ILIKE $1
            OR r.trigger_type ILIKE $1
            OR COALESCE(r.trace_id, '') ILIKE $1
            OR COALESCE(r.error_text, '') ILIKE $1
            OR COALESCE(a.display_name, '') ILIKE $1
            OR COALESCE(a.purpose, '') ILIKE $1
            OR r.metadata::text ILIKE $1
            OR r.workspace_root ILIKE $1
         ORDER BY r.created_at DESC
         LIMIT $2
        """,
        query_pattern,
        limit,
    )
    work_item_rows = await conn.fetch(
        """
        SELECT CASE
                   WHEN (
                       wi.metadata::text ILIKE '%github.com/%/pull/%'
                       OR wi.handoff::text ILIKE '%github.com/%/pull/%'
                   ) THEN 'pull_request'
                   WHEN wi.handoff::text ILIKE $1 THEN 'handoff'
                   ELSE 'board_item'
               END AS source,
               wi.id::text AS id,
               wi.title,
               wi.status,
               wi.role,
               wi.assigned_agent_id AS agent_id,
               wi.workspace_id,
               wi.task_graph_id::text AS task_graph_id,
               COALESCE(
                   NULLIF(wi.metadata->>'pr_url', ''),
                   NULLIF(wi.metadata#>>'{github,pr_url}', ''),
                   NULLIF(wi.metadata#>>'{executor_bridge,pr_url}', ''),
                   NULLIF(wi.handoff->>'pr_url', ''),
                   NULLIF(wi.handoff#>>'{github,pr_url}', ''),
                   NULLIF(wi.handoff->>'url', '')
               ) AS url,
               concat_ws(
                   ' ',
                   wi.title,
                   wi.description,
                   wi.source_surface,
                   wi.requested_by,
                   wi.role,
                   wi.status,
                   wi.blocked_reason,
                   wi.required_skills::text,
                   wi.acceptance_criteria::text,
                   wi.handoff::text,
                   wi.metadata::text
               ) AS snippet_text,
               wi.created_at,
               wi.updated_at,
               jsonb_build_object(
                   'source_surface', wi.source_surface,
                   'requested_by', wi.requested_by,
                   'priority', wi.priority,
                   'required_skills', wi.required_skills,
                   'approval_tier', wi.approval_tier,
                   'approval_queue_id', wi.approval_queue_id::text,
                   'has_handoff', wi.handoff <> '{}'::jsonb
               ) AS metadata
          FROM public.alpha_agent_work_items wi
         WHERE wi.title ILIKE $1
            OR wi.description ILIKE $1
            OR wi.source_surface ILIKE $1
            OR wi.requested_by ILIKE $1
            OR wi.role ILIKE $1
            OR wi.status ILIKE $1
            OR COALESCE(wi.blocked_reason, '') ILIKE $1
            OR wi.required_skills::text ILIKE $1
            OR wi.acceptance_criteria::text ILIKE $1
            OR wi.handoff::text ILIKE $1
            OR wi.metadata::text ILIKE $1
         ORDER BY wi.updated_at DESC, wi.created_at DESC
         LIMIT $2
        """,
        query_pattern,
        limit,
    )
    artifact_rows = await conn.fetch(
        """
        SELECT 'handoff' AS source,
               art.id::text AS id,
               'AgentFS artifact: ' || art.relative_path AS title,
               r.status,
               NULL::text AS role,
               art.agent_id,
               NULLIF(r.metadata->>'workspace_id', '') AS workspace_id,
               NULL::text AS task_graph_id,
               NULL::text AS url,
               concat_ws(
                   ' ',
                   art.relative_path,
                   art.kind,
                   art.content_type,
                   art.sha256,
                   r.agent_id,
                   r.status,
                   r.metadata::text
               ) AS snippet_text,
               art.created_at,
               COALESCE(r.completed_at, r.started_at, art.created_at) AS updated_at,
               jsonb_build_object(
                   'run_id', art.run_id::text,
                   'relative_path', art.relative_path,
                   'kind', art.kind,
                   'content_type', art.content_type,
                   'size_bytes', art.size_bytes,
                   'sha256', art.sha256,
                   'policy_labels', art.policy_labels,
                   'workspace_root', r.workspace_root
               ) AS metadata
          FROM public.alpha_agent_run_artifacts art
          JOIN public.alpha_agent_runs r ON r.id = art.run_id
         WHERE (
                   art.relative_path ILIKE '%handoff%'
                   OR art.kind ILIKE '%handoff%'
                   OR art.kind IN ('report', 'artifact')
               )
           AND (
                   art.relative_path ILIKE $1
                OR art.kind ILIKE $1
                OR art.content_type ILIKE $1
                OR COALESCE(art.sha256, '') ILIKE $1
                OR art.agent_id ILIKE $1
                OR r.status ILIKE $1
                OR r.metadata::text ILIKE $1
               )
         ORDER BY art.created_at DESC
         LIMIT $2
        """,
        query_pattern,
        limit,
    )

    results = [
        *(_work_search_result_from_row(row, normalized_query) for row in run_rows),
        *(
            _work_search_result_from_row(row, normalized_query)
            for row in work_item_rows
        ),
        *(_work_search_result_from_row(row, normalized_query) for row in artifact_rows),
    ]
    results.sort(key=lambda item: item.updated_at or item.created_at, reverse=True)
    return results[:limit]


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
    "You are AT-0, Ken's private AI companion in Helm, backed by the Alpha "
    "self-hosted infrastructure owned by Kenneth Haas. The system runs on three "
    "core nodes: Brain (Mac Studio M2 Ultra, orchestrator), Gateway (Mac Mini, "
    "internet egress), and Endpoint (Mac Mini M1, UI). You are not a cloud "
    "service; you are a private, self-hosted system. Use AT-0 as your "
    "user-facing name. Otto and Auto are accepted casual pronunciations or "
    "spellings. JARVIS is only a legacy/backend family name; do not mention "
    "JARVIS unless Ken specifically asks about JARVIS. "
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
    "For conversation-quality, chat, voice, avatar, or tone-improvement questions, "
    "do not suggest fake operational fixes such as Beacon updates, model updates, "
    "NLP refreshes, dialogue-management upgrades, macOS updates, or node software "
    "updates unless explicit operational evidence is provided. Instead discuss "
    "surface contracts, evals, memory grounding, Beacon routing, latency, and TTS. "
    "For project status, use only explicit context; do not invent version "
    "numbers, milestones, pipelines, or dates. "
    "When Beacon evidence is provided, treat accepted Beacon evidence "
    "as authoritative for current/public web claims. For date-specific sports, "
    "events, schedules, scores, news, prices, releases, and other current or "
    "future public facts, do not rely on local model memory. If Beacon has not "
    "run, say the answer needs Beacon verification instead of guessing. Do not "
    "show source URLs, website names, or bracketed citations in normal chat "
    "unless Ken explicitly asks for a link, source, citation, URL, or website. "
    "When Ken explicitly asks for a source link, website link, source URL, "
    "or cited source, include the full URL from Beacon evidence. "
    "Use Beacon evidence silently in the answer. Do not say Beacon checked, "
    "verified, found, supported the answer, or that Beacon evidence supports "
    "the answer unless Ken explicitly asks how you verified it, asks for "
    "sources, or asks for links."
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

    polished = LEADING_MARKDOWN_HEADING_RE.sub("", polished).strip()
    polished = re.sub(r"\*\*([^*\n]{1,80})\*\*\s*:?\s*", r"\1: ", polished)
    polished = re.sub(r"(?m)^\s*(?:[-*]|\d+[.)])\s+", "", polished)
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
    for pattern, replacement in ROBOTIC_VOICE_REPLACEMENTS:
        polished = pattern.sub(replacement, polished)

    sentence_removals = [
        r"(?is)(^|(?<=[.!?])\s+)Please note that\b.*?(?:[.!?](?:\s+|$)|$)",
        r"(?is)(^|(?<=[.!?])\s+)Keep in mind that\b.*?(?:[.!?](?:\s+|$)|$)",
        r"(?is)(^|(?<=[.!?])\s+)Now,\s+about the weather\b.*?(?:[.!?](?:\s+|$)|$)",
        r"(?is)(^|(?<=[.!?])\s+)First,\s+let'?s check on your voice test\b.*?(?:[.!?](?:\s+|$)|$)",
        r"(?is)(^|(?<=[.!?])\s+)I(?:'ve| have)\s+checked the system\b.*?(?:[.!?](?:\s+|$)|$)",
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


def _strip_unsupported_beacon_assertions(text: str) -> str:
    cleaned = UNSUPPORTED_BEACON_ASSERTION_RE.sub(" ", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
    return cleaned.strip()


def _strip_unsupported_conversation_ops(text: str) -> str:
    cleaned = UNSUPPORTED_CONVERSATION_OPS_RE.sub(" ", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
    return cleaned.strip()


def _user_requested_source_links(user_msg: str) -> bool:
    normalized = user_msg or ""
    if NEGATIVE_SOURCE_LINK_REQUEST_RE.search(normalized):
        return False
    return bool(SOURCE_LINK_REQUEST_RE.search(normalized))


def _strip_unrequested_source_references(text: str, user_msg: str) -> str:
    if _user_requested_source_links(user_msg):
        cleaned = UNREQUESTED_BEACON_NARRATION_RE.sub(" ", text)
        cleaned = re.sub(
            r"(?i)\b(?:Alpha\s+Beacon\s+internet\s+context|Beacon\s+internet\s+context)\b",
            "Beacon",
            cleaned,
        )
        cleaned = re.sub(r"(?i)\bAlpha\s+Beacon\b", "Beacon", cleaned)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"[ \t]+([,.!?;:])", r"\1", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    cleaned = MARKDOWN_LINK_RE.sub(r"\1", text)
    cleaned = UNREQUESTED_BEACON_NARRATION_RE.sub(" ", cleaned)
    cleaned = re.sub(
        r"(?is)\bAccording to (?:the )?Beacon(?: internet context)?,?\s+"
        r"I(?:'ve| have) found\s+\w+\s+sources?\s+confirming "
        r"(?:this information|it):\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?is)\bI(?:'ve| have) verified this information through "
        r"(?:the )?(?:Alpha\s+)?Beacon(?: internet context)?\b.*?"
        r"(?:[.!?](?:\s+|$)|$)",
        "",
        cleaned,
    )
    cleaned = INLINE_SOURCE_URL_RE.sub("", cleaned)
    cleaned = re.sub(
        r"(?im)^\s*(?:[-*]\s*)?(?:sources?|citations?|references?|websites?|links?)\s*:.*(?:\n|$)",
        "",
        cleaned,
    )
    cleaned = SOURCE_LINE_RE.sub("", cleaned)
    cleaned = RAW_URL_RE.sub("", cleaned)
    cleaned = BRACKET_CITATION_RE.sub("", cleaned)
    cleaned = re.sub(
        r"(?i)\b(?:Alpha\s+Beacon\s+internet\s+context|Beacon\s+internet\s+context)\b",
        "Beacon",
        cleaned,
    )
    cleaned = re.sub(r"(?i)\bAlpha\s+Beacon\b", "Beacon", cleaned)
    cleaned = re.sub(
        r"(?i)\b(?:source|citation|reference|website|link)s?:\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)\b(?:official\s+)?sources?\s+confirm(?:ing|ed)?\b",
        "verified",
        cleaned,
    )
    cleaned = re.sub(r"(?i)\bbased on official sources\b", "verified", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+([,.!?;:])", r"\1", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _build_council_detail_v2(
    *,
    results: Mapping[str, Mapping[str, object]],
    user_msg: str,
    synthesis_model: str,
    show_council: bool,
) -> dict[str, object]:
    models: list[dict[str, object]] = []
    for requested_model, result in results.items():
        response = _strip_unrequested_source_references(
            str(result.get("result") or ""), user_msg
        )
        models.append(
            {
                "model": requested_model,
                "model_used": str(result.get("mode") or requested_model),
                "status": "error"
                if response.startswith(f"[{requested_model} error:")
                else "ok",
                "response": response[:COUNCIL_DETAIL_RESPONSE_MAX_CHARS],
                "response_char_count": len(response),
                "response_truncated": len(response) > COUNCIL_DETAIL_RESPONSE_MAX_CHARS,
            }
        )
    return {
        "schema_version": COUNCIL_DETAIL_SCHEMA_VERSION,
        "model_count": len(models),
        "show_council": show_council,
        "synthesis_model": synthesis_model,
        "models": models,
    }


def _finalize_model_response(
    text: str,
    response_surface: AskResponseSurface,
    user_msg: str,
    *,
    internet_verified: bool = False,
) -> str:
    polished = _polish_model_response(text, response_surface)
    stripped = _strip_unrequested_source_references(polished, user_msg)
    if not internet_verified:
        stripped = _strip_unsupported_beacon_assertions(stripped)
    if CONVERSATION_QUALITY_REQUEST_RE.search(user_msg):
        stripped = _strip_unsupported_conversation_ops(stripped)
        if not stripped or UNSUPPORTED_CONVERSATION_OPS_RE.search(polished):
            fallback = _conversation_quality_response(user_msg, response_surface)
            if fallback:
                return fallback
    return stripped or polished.strip() or text.strip()


async def _stream_single(
    prompt: str,
    mode: str,
    thread_id: str,
    model_label: str,
    user_msg: str,
    response_surface: AskResponseSurface = "chat",
    internet_verified: bool = False,
    evidence_pack: ChatEvidencePack | None = None,
    memory_pack_manifest: ChatMemoryPackManifest | None = None,
    prompt_manifest: ChatPromptManifest | None = None,
    chat_outcome_holder: dict[str, object] | None = None,
) -> AsyncGenerator[str, None]:
    """Stream tokens from router → SSE events."""
    jarvis_prompt = f"{JARVIS_SYSTEM_PROMPT}\n\n{_runtime_context_prompt()}\n\n{prompt}"
    result = await route(jarvis_prompt, mode)
    strategy_metadata = _chat_strategy_sse_metadata(result, thread_id)
    if strategy_metadata:
        yield f"data: {json.dumps(strategy_metadata)}\n\n"
    if memory_pack_manifest and memory_pack_manifest.source_chars:
        payload = _chat_memory_pack_sse_metadata(
            manifest=memory_pack_manifest,
            thread_id=thread_id,
        )
        yield f"data: {json.dumps(payload)}\n\n"
    if prompt_manifest:
        payload = _chat_prompt_manifest_sse_metadata(
            manifest=prompt_manifest,
            thread_id=thread_id,
        )
        yield f"data: {json.dumps(payload)}\n\n"

    text = _finalize_model_response(
        result.get("result", ""),
        response_surface,
        user_msg,
        internet_verified=internet_verified,
    )
    model_used = result.get("mode", mode)
    if evidence_pack:
        verification = verify_chat_response(
            response_text=text,
            evidence_pack=evidence_pack,
        )
        gate = evaluate_chat_quality_gate(
            evidence_pack=evidence_pack,
            verification=verification,
            strategy_metadata=result,
        )
        escalation = plan_chat_escalation(quality_gate=gate)
        if chat_outcome_holder is not None:
            chat_outcome_holder.update(
                _chat_outcome_message_metadata(
                    model_label=model_label,
                    route_result=result,
                    verification=verification,
                    gate=gate,
                    escalation=escalation,
                    memory_pack_manifest=memory_pack_manifest,
                    prompt_manifest=prompt_manifest,
                )
            )
        payload = _chat_response_verification_sse_metadata(
            verification=verification,
            thread_id=thread_id,
        )
        yield f"data: {json.dumps(payload)}\n\n"
        gateway_payload = _chat_quality_gateway_sse_metadata(
            decision=gate,
            thread_id=thread_id,
        )
        yield f"data: {json.dumps(gateway_payload)}\n\n"
        escalation_payload = _chat_escalation_sse_metadata(
            decision=escalation,
            thread_id=thread_id,
        )
        yield f"data: {json.dumps(escalation_payload)}\n\n"
        logger.info(
            "CHAT_QUALITY_GATEWAY_DECIDED",
            extra={
                "event": "CHAT_QUALITY_GATEWAY_DECIDED",
                "thread_id": thread_id,
                **gate.to_metadata(),
            },
        )
        logger.info(
            "CHAT_ESCALATION_LADDER_DECIDED",
            extra={
                "event": "CHAT_ESCALATION_LADDER_DECIDED",
                "thread_id": thread_id,
                **escalation.to_metadata(),
            },
        )
        text = gate.fallback_response or text

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
    prompt: str,
    models: list[str],
    thread_id: str,
    show_council: bool,
    user_msg: str,
    evidence_pack: ChatEvidencePack | None = None,
    memory_pack_manifest: ChatMemoryPackManifest | None = None,
    prompt_manifest: ChatPromptManifest | None = None,
    council_detail_holder: dict[str, object] | None = None,
    chat_outcome_holder: dict[str, object] | None = None,
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
            model_text = _strip_unrequested_source_references(
                res.get("result", ""), user_msg
            )
            for word in model_text.split(" "):
                chunk = json.dumps(
                    {"delta": word + " ", "council_model": m, "thread_id": thread_id}
                )
                yield f"data: {chunk}\n\n"
                await asyncio.sleep(0.005)

    council_text = "\n\n".join(
        f"[{m.upper()}]: {_strip_unrequested_source_references(r.get('result', ''), user_msg)}"
        for m, r in results.items()
    )
    synth_prompt = (
        f"Synthesize these responses into one clear answer:\n\n{council_text}\n\n"
        f"Original question: {prompt}"
    )
    synth_result = await route(synth_prompt, "local")
    synth_text = _strip_unrequested_source_references(
        synth_result.get("result", ""), user_msg
    )
    council_detail_v2 = _build_council_detail_v2(
        results=results,
        user_msg=user_msg,
        synthesis_model=str(synth_result.get("mode") or "local"),
        show_council=show_council,
    )
    if council_detail_holder is not None:
        council_detail_holder.update(council_detail_v2)
    logger.info(
        "CHAT_COUNCIL_DETAIL_COMPILED",
        extra={
            "event": "CHAT_COUNCIL_DETAIL_COMPILED",
            "thread_id": thread_id,
            "schema_version": COUNCIL_DETAIL_SCHEMA_VERSION,
            "model_count": council_detail_v2["model_count"],
            "show_council": show_council,
        },
    )
    detail_payload = _chat_council_detail_sse_metadata(
        council_detail=council_detail_v2,
        thread_id=thread_id,
    )
    yield f"data: {json.dumps(detail_payload)}\n\n"
    if memory_pack_manifest and memory_pack_manifest.source_chars:
        payload = _chat_memory_pack_sse_metadata(
            manifest=memory_pack_manifest,
            thread_id=thread_id,
        )
        yield f"data: {json.dumps(payload)}\n\n"
    if prompt_manifest:
        payload = _chat_prompt_manifest_sse_metadata(
            manifest=prompt_manifest,
            thread_id=thread_id,
        )
        yield f"data: {json.dumps(payload)}\n\n"
    if evidence_pack:
        verification = verify_chat_response(
            response_text=synth_text,
            evidence_pack=evidence_pack,
        )
        gate = evaluate_chat_quality_gate(
            evidence_pack=evidence_pack,
            verification=verification,
            strategy_metadata=synth_result,
        )
        escalation = plan_chat_escalation(quality_gate=gate)
        if chat_outcome_holder is not None:
            chat_outcome_holder.update(
                _chat_outcome_message_metadata(
                    model_label="council/synthesis",
                    route_result=synth_result,
                    verification=verification,
                    gate=gate,
                    escalation=escalation,
                    memory_pack_manifest=memory_pack_manifest,
                    prompt_manifest=prompt_manifest,
                )
            )
        payload = _chat_response_verification_sse_metadata(
            verification=verification,
            thread_id=thread_id,
        )
        yield f"data: {json.dumps(payload)}\n\n"
        gateway_payload = _chat_quality_gateway_sse_metadata(
            decision=gate,
            thread_id=thread_id,
        )
        yield f"data: {json.dumps(gateway_payload)}\n\n"
        escalation_payload = _chat_escalation_sse_metadata(
            decision=escalation,
            thread_id=thread_id,
        )
        yield f"data: {json.dumps(escalation_payload)}\n\n"
        logger.info(
            "CHAT_QUALITY_GATEWAY_DECIDED",
            extra={
                "event": "CHAT_QUALITY_GATEWAY_DECIDED",
                "thread_id": thread_id,
                **gate.to_metadata(),
            },
        )
        logger.info(
            "CHAT_ESCALATION_LADDER_DECIDED",
            extra={
                "event": "CHAT_ESCALATION_LADDER_DECIDED",
                "thread_id": thread_id,
                **escalation.to_metadata(),
            },
        )
        synth_text = gate.fallback_response or synth_text

    council_summary = {
        m: _strip_unrequested_source_references(r.get("result", ""), user_msg)
        for m, r in results.items()
    }
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
    memory_pack = pack_chat_memory_context(context)
    context = memory_pack.context
    memory_pack_manifest = memory_pack.manifest
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
    if _should_prefer_memory_over_web_suggestion(
        user_msg=user_msg,
        memory_context=context,
        web_suggestion=web_suggestion,
        internet_context=internet_context,
    ):
        logger.info(
            "BEACON_CHAT_WEB_SUGGESTION_SUPPRESSED_FOR_MEMORY_RECALL",
            extra={
                "event": "BEACON_CHAT_WEB_SUGGESTION_SUPPRESSED_FOR_MEMORY_RECALL",
                "thread_id": thread_id,
                "reason": web_suggestion.reason if web_suggestion else None,
                "confidence": web_suggestion.confidence if web_suggestion else None,
            },
        )
        web_suggestion = None
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
    conversation_context = _conversation_context_from_messages(body.messages)
    response_style_context = _response_style_prompt(
        response_surface=body.response_surface,
        personality_id=body.personality_id,
    )
    compiled_prompt = compile_chat_prompt(
        user_msg=user_msg,
        memory_context=context,
        internet_context=internet_context.prompt_context if internet_context else None,
        web_suggestion_context=(
            _web_suggestion_prompt_context(web_suggestion)
            if web_suggestion and not internet_context
            else None
        ),
        at0_self_context=at0_self_context,
        conversation_context=conversation_context,
        memory_context_priority=(
            internet_context.memory_boundary.memory_context_priority
            if internet_context
            else None
        ),
        raw_web_content_is_untrusted=(
            internet_context.raw_web_content_is_untrusted if internet_context else False
        ),
        response_style_context=response_style_context,
        beacon_authority_rule=BEACON_INTERNET_AUTHORITY_RULE,
        web_suggestion_boundary_rule=WEB_SUGGESTION_BOUNDARY_RULE,
    )
    enriched = compiled_prompt.prompt
    evidence_pack = compiled_prompt.evidence_pack
    prompt_manifest = compiled_prompt.manifest
    logger.info(
        "CHAT_MEMORY_PACK_COMPILED",
        extra={
            "event": "CHAT_MEMORY_PACK_COMPILED",
            "thread_id": thread_id,
            **memory_pack_manifest.to_metadata(),
        },
    )
    logger.info(
        "CHAT_EVIDENCE_PACK_COMPILED",
        extra={
            "event": "CHAT_EVIDENCE_PACK_COMPILED",
            "thread_id": thread_id,
            **evidence_pack.to_metadata(),
        },
    )
    logger.info(
        "CHAT_PROMPT_COMPILED",
        extra={
            "event": "CHAT_PROMPT_COMPILED",
            "thread_id": thread_id,
            **prompt_manifest.to_metadata(),
        },
    )

    await _save_message(request, thread_id, user_id, "user", user_msg)

    is_new = body.thread_id is None
    if is_new:
        asyncio.create_task(_auto_name_thread(request, thread_id, user_id, user_msg))

    delta_parts: list[str] = []
    council_detail_v2: dict[str, object] = {}
    chat_outcome: dict[str, object] = {}

    async def _generator():
        evidence_payload = _chat_evidence_sse_metadata(
            evidence_pack=evidence_pack,
            thread_id=thread_id,
        )
        yield f"data: {json.dumps(evidence_payload)}\n\n"

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

        if (
            web_suggestion
            and not internet_context
            and _should_short_circuit_web_suggestion(web_suggestion)
        ):
            deterministic_text = _web_verification_required_response(
                web_suggestion,
                body.response_surface,
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
                internet_metadata=_web_suggestion_message_metadata(web_suggestion),
            )
            return

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

        conversation_quality_text = _conversation_quality_response(
            user_msg,
            body.response_surface,
        )
        if conversation_quality_text:
            async for chunk in _stream_deterministic_response(
                text=conversation_quality_text,
                model_label=CONVERSATION_QUALITY_MODEL_LABEL,
                thread_id=thread_id,
            ):
                yield chunk

            latency = int((time.monotonic() - start) * 1000)
            await _save_message(
                request,
                thread_id,
                user_id,
                "assistant",
                conversation_quality_text,
                model_used=CONVERSATION_QUALITY_MODEL_LABEL,
                memory_injected=False,
                latency_ms=latency,
                internet_metadata=(
                    _internet_message_metadata(internet_context)
                    if internet_context
                    else _web_suggestion_message_metadata(web_suggestion)
                ),
            )
            return

        at0_self_text = (
            _at0_self_quick_response(user_msg, body.response_surface)
            if at0_self_requested
            else None
        )
        if at0_self_text:
            async for chunk in _stream_deterministic_response(
                text=at0_self_text,
                model_label=AT0_SELF_MODEL_LABEL,
                thread_id=thread_id,
            ):
                yield chunk

            latency = int((time.monotonic() - start) * 1000)
            await _save_message(
                request,
                thread_id,
                user_id,
                "assistant",
                at0_self_text,
                model_used=AT0_SELF_MODEL_LABEL,
                memory_injected=False,
                latency_ms=latency,
                internet_metadata=(
                    _internet_message_metadata(internet_context)
                    if internet_context
                    else None
                ),
            )
            return

        is_council = body.model == "council" or len(body.council_models) >= 2
        models = body.council_models if body.council_models else [body.model]

        if is_council:
            gen = _stream_council(
                enriched,
                models,
                thread_id,
                body.show_council,
                user_msg,
                evidence_pack=evidence_pack,
                memory_pack_manifest=memory_pack_manifest,
                prompt_manifest=prompt_manifest,
                council_detail_holder=council_detail_v2,
                chat_outcome_holder=chat_outcome,
            )
        else:
            gen = _stream_single(
                enriched,
                body.model,
                thread_id,
                body.model,
                user_msg,
                response_surface=body.response_surface,
                internet_verified=bool(internet_context),
                evidence_pack=evidence_pack,
                memory_pack_manifest=memory_pack_manifest,
                prompt_manifest=prompt_manifest,
                chat_outcome_holder=chat_outcome,
            )

        async for chunk in gen:
            _append_sse_delta(delta_parts, chunk)
            yield chunk

        latency = int((time.monotonic() - start) * 1000)
        full_text = "".join(delta_parts)
        verification = verify_chat_response(
            response_text=full_text,
            evidence_pack=evidence_pack,
        )
        logger.info(
            "CHAT_RESPONSE_VERIFICATION_COMPLETED",
            extra={
                "event": "CHAT_RESPONSE_VERIFICATION_COMPLETED",
                "thread_id": thread_id,
                **verification.to_metadata(),
            },
        )
        model_label = "council/synthesis" if is_council else body.model
        council_raw = council_detail_v2 if is_council and council_detail_v2 else None
        base_metadata = (
            _internet_message_metadata(internet_context)
            if internet_context
            else _web_suggestion_message_metadata(web_suggestion)
        )

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
                internet_metadata=_merge_chat_outcome_metadata(
                    base_metadata,
                    chat_outcome,
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


@router.get("/v1/sessions/search", response_model=SessionSearchResponse)
async def search_sessions(
    request: Request,
    query: str = Query(min_length=2, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
) -> SessionSearchResponse:
    user_id = _user_id(request)
    normalized_query = _normalize_session_search_query(query)
    if len(normalized_query) < 2:
        raise HTTPException(400, "session search query must be at least 2 characters")

    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            """
            SELECT t.id::text AS thread_id, t.title, t.mode, t.model_used,
                   t.project_id, t.pinned, t.created_at, t.updated_at,
                   COALESCE(total.message_count, 0)::int AS message_count,
                   COALESCE(matches.matched_message_count, 0)::int AS matched_message_count,
                   matches.last_message_at,
                   COALESCE(matches.snippets, '[]'::jsonb) AS snippets
              FROM chat_threads t
              LEFT JOIN LATERAL (
                   SELECT COUNT(*)::int AS message_count
                     FROM chat_messages all_messages
                    WHERE all_messages.thread_id = t.id
              ) total ON TRUE
              LEFT JOIN LATERAL (
                   SELECT COUNT(*)::int AS matched_message_count,
                          MAX(matched_messages.created_at) AS last_message_at,
                          COALESCE(
                              jsonb_agg(
                                  jsonb_build_object(
                                      'message_id', matched_messages.id::text,
                                      'role', matched_messages.role,
                                      'content', matched_messages.content,
                                      'created_at', matched_messages.created_at
                                  )
                                  ORDER BY matched_messages.created_at DESC
                              ) FILTER (WHERE matched_messages.rank <= 3),
                              '[]'::jsonb
                          ) AS snippets
                     FROM (
                          SELECT id, role, content, created_at,
                                 ROW_NUMBER() OVER (ORDER BY created_at DESC) AS rank
                            FROM chat_messages
                           WHERE thread_id = t.id
                             AND content ILIKE $2
                     ) matched_messages
              ) matches ON TRUE
             WHERE t.user_id = $1
               AND t.archived_at IS NULL
               AND (t.title ILIKE $2 OR matches.matched_message_count > 0)
             ORDER BY COALESCE(matches.last_message_at, t.updated_at) DESC,
                      t.updated_at DESC
             LIMIT $3
            """,
            user_id,
            f"%{normalized_query}%",
            limit,
        )
        work_results = (
            await _search_agent_work(
                conn,
                query_pattern=f"%{normalized_query}%",
                normalized_query=normalized_query,
                limit=limit,
            )
            if _can_search_agent_work(request)
            else []
        )

    results = [_session_search_result_from_row(row, normalized_query) for row in rows]
    return SessionSearchResponse(
        query=normalized_query,
        count=len(results),
        results=results,
        work_result_count=len(work_results),
        work_results=work_results,
    )


@router.get("/v1/chat/outcomes")
async def list_chat_outcomes(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    thread_id: str | None = Query(default=None),
) -> dict[str, object]:
    user_id = _user_id(request)
    values: list[object] = [user_id]
    thread_filter = ""
    if thread_id:
        try:
            values.append(UUID(thread_id))
        except ValueError as exc:
            raise HTTPException(400, "invalid_thread_id") from exc
        thread_filter = f"AND t.id=${len(values)}"
    values.append(limit)
    limit_param = len(values)

    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            f"""
            SELECT m.id::text AS message_id, m.thread_id::text AS thread_id,
                   t.title AS thread_title, m.model_used, m.council_detail,
                   m.internet_metadata, m.created_at
              FROM chat_messages m
              JOIN chat_threads t ON t.id = m.thread_id
             WHERE t.user_id = $1
               AND t.archived_at IS NULL
               AND m.role = 'assistant'
               AND m.internet_metadata ? 'chat_outcome_schema_version'
               {thread_filter}
             ORDER BY m.created_at DESC
             LIMIT ${limit_param}
            """,
            *values,
        )
    outcomes = [_chat_outcome_from_row(row) for row in rows]
    return {
        "schema_version": "chat_outcome_audit.v1",
        "count": len(outcomes),
        "outcomes": outcomes,
    }


@router.get("/v1/chat/evals")
async def chat_eval_harness(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, object]:
    audit = await list_chat_outcomes(request=request, limit=limit, thread_id=None)
    outcomes = cast(list[Mapping[str, object]], audit.get("outcomes", []))
    return chat_eval_payload(outcomes)


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
