from __future__ import annotations

import os

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://127.0.0.1:8188")

from brain.routes import chat
from brain.services.at0_self_model import is_at0_self_query
from brain.services.internet_scout.web_suggestion import suggest_web_for_chat
from tests.test_chat_internet_metadata import (
    _insufficient_context,
    _supported_openai_context,
)


def test_eval_beacon_evidence_is_authority_over_stale_memory() -> None:
    prompt = chat._build_enriched_prompt(
        memory_context="Memory says use https://beta.openai.com/docs/api-reference.",
        internet_context=_supported_openai_context().prompt_context,
        user_msg="Find the official OpenAI API reference URL.",
    )

    assert prompt.index("Beacon evidence") < prompt.index("Context from memory")
    assert "If memory conflicts with Beacon, follow Beacon" in prompt
    assert "https://platform.openai.com/docs/api-reference" in prompt


def test_eval_docs_url_answer_prefers_source_url_over_endpoint_example() -> None:
    prompt = chat._build_enriched_prompt(
        memory_context="Memory says the answer is https://beta.openai.com/docs.",
        internet_context=(
            "Beacon mode: Deep research\n"
            "Beacon citation quality: supported\n"
            "If the user asks for a documentation page, docs URL, source URL, "
            "or official link, answer with the cited Source URL; do not substitute "
            "API endpoint examples from citation text unless the user asks for an "
            "API endpoint.\n"
            "Beacon evidence:\n"
            "Answer target: source URL\n"
            "Preferred answer URL: "
            "https://platform.openai.com/docs/api-reference/responses [1]\n"
            "Do not answer with API endpoint URLs, request paths, or examples found "
            "in citation text unless the user explicitly asks for an API endpoint.\n"
            "Claim: The official OpenAI Responses API documentation URL is "
            "https://platform.openai.com/docs/api-reference/responses.\n"
            "[1] Official documentation URL: "
            "https://platform.openai.com/docs/api-reference/responses. "
            "Example endpoint: GET https://api.openai.com/v1/responses/resp_123.\n"
            "Source: https://platform.openai.com/docs/api-reference/responses"
        ),
        user_msg=(
            "What is the official OpenAI API documentation URL for the Responses API? "
            "Cite the source."
        ),
    )

    assert "If memory conflicts with Beacon, follow Beacon" in prompt
    assert "Do not answer with API endpoint URLs" in prompt
    assert prompt.index(
        "https://platform.openai.com/docs/api-reference/responses"
    ) < prompt.index("https://api.openai.com/v1/responses/resp_123")


def test_eval_insufficient_official_evidence_fails_closed() -> None:
    context = _insufficient_context()

    assert chat._should_short_circuit_internet_response(context) is True
    response = chat._insufficient_beacon_response(context)

    assert "accepted official source" in response
    assert "beta.openai.com" not in response


def test_eval_smart_web_suggestion_does_not_silently_search() -> None:
    suggestion = suggest_web_for_chat(
        query="Find the official OpenAI API reference URL.",
        internet_mode="none",
        sensitivity="normal",
    )

    assert suggestion is not None
    assert suggestion.requires_confirmation is True
    assert suggestion.mode == "deep_research"


def test_at0_voice_surface_injects_style_context() -> None:
    prompt = chat._build_enriched_prompt(
        memory_context="",
        internet_context=None,
        response_surface="voice",
        personality_id="calm_operator",
        user_msg="How is the weather?",
    )

    assert "AT-0 interaction style:" in prompt
    assert "Surface: Voice" in prompt
    assert "one or two conversational sentences" in prompt
    assert "under 45 words" in prompt
    assert "No markdown" in prompt
    assert "Calm Operator" in prompt
    assert "do not correct him" in prompt
    assert "User: How is the weather?" in prompt


def test_at0_chat_surface_injects_detailed_grounded_contract() -> None:
    prompt = chat._build_enriched_prompt(
        memory_context="",
        internet_context=None,
        user_msg="Hello",
    )

    assert "Surface: Chat" in prompt
    assert "fuller useful answer" in prompt
    assert "short sections or bullets" in prompt
    assert "Do not invent backend updates" in prompt
    assert prompt.endswith("User: Hello")


def test_at0_avatar_surface_injects_brief_presence_contract() -> None:
    prompt = chat._build_enriched_prompt(
        memory_context="",
        internet_context=None,
        response_surface="avatar",
        user_msg="Hello",
    )

    assert "Surface: Avatar" in prompt
    assert "under 35 words" in prompt
    assert "do not narrate interface" in prompt
    assert prompt.endswith("User: Hello")


def test_at0_voice_polish_removes_robotic_weather_preamble() -> None:
    polished = chat._polish_model_response(
        "According to Open-Meteo, which is a reliable source for current "
        "weather conditions, it is 72 F, feeling like 73 F. Please note that "
        "conditions can change.",
        "voice",
    )

    assert polished.startswith("Open-Meteo has it as")
    assert "reliable source for current weather conditions" not in polished
    assert "feeling like 73 degrees" in polished
    assert "Please note" not in polished


def test_at0_voice_polish_replaces_robotic_status_phrases() -> None:
    polished = chat._polish_model_response(
        "As a private AI assistant, I am functioning within normal parameters. "
        "Please note that diagnostics are nominal.",
        "voice",
    )

    assert "private AI assistant" not in polished
    assert "functioning within normal parameters" not in polished
    assert "Please note" not in polished
    assert polished.startswith("I'm ready")


def test_at0_voice_polish_removes_markdown_heading() -> None:
    polished = chat._polish_model_response(
        "**Voice Processing Optimizations** We are close. The next move is "
        "reducing the pause before speech starts.",
        "voice",
    )

    assert (
        polished
        == "We are close. The next move is reducing the pause before speech starts."
    )
    assert "**" not in polished


def test_at0_voice_polish_removes_inline_heading_and_unsupported_system_claim() -> None:
    polished = chat._polish_model_response(
        "We can reduce the delay. I've checked the system and found the current "
        "configuration is efficient. **Caveats**: balance quality and speed.",
        "voice",
    )

    assert "I've checked the system" not in polished
    assert "**" not in polished
    assert "Caveats:" in polished


def test_at0_final_response_strips_unsupported_beacon_claim() -> None:
    finalized = chat._finalize_model_response(
        "Beacon checked our architecture and performance metrics. We are close "
        "to a two-second voice response.",
        "voice",
        "How do we make voice feel near real time?",
        internet_verified=False,
    )

    assert finalized == "We are close to a two-second voice response."
    assert "Beacon checked" not in finalized


def test_at0_final_response_replaces_fake_conversation_update_plan() -> None:
    finalized = chat._finalize_model_response(
        "**Update Conversational Models** Run a Beacon update from Alpha. "
        "Then update macOS on each node and refresh my models with the latest NLP "
        "and dialogue management techniques.",
        "chat",
        "What is the best way to improve AT-0 conversation quality in chat and voice?",
        internet_verified=False,
    )

    assert "eval-driven" in finalized
    assert "Chat should be fuller" in finalized
    assert "Voice should be short" in finalized
    assert "Beacon update" not in finalized
    assert "macOS" not in finalized
    assert "NLP" not in finalized


def test_eval_sports_schedule_suggests_web_search() -> None:
    suggestion = suggest_web_for_chat(
        query="What time does USMNT play tomorrow?",
        internet_mode="none",
        sensitivity="normal",
    )

    assert suggestion is not None
    assert suggestion.mode == "web_search"
    assert suggestion.reason == "sports_schedule_likely"
    assert suggestion.confidence == "high"


def test_eval_sports_schedule_without_beacon_short_circuits_stale_answer() -> None:
    suggestion = suggest_web_for_chat(
        query="Don't USA men's soccer play Friday at 3 PM EST?",
        internet_mode="none",
        sensitivity="normal",
    )

    assert suggestion is not None
    assert chat._should_short_circuit_web_suggestion(suggestion) is True

    response = chat._web_verification_required_response(suggestion, "voice")

    assert "Beacon" in response
    assert "check" in response
    assert "3 PM" not in response


def test_eval_avatar_web_howto_is_self_query_not_stale_fact() -> None:
    query = "In avatar mode, how do I make you search the internet?"
    suggestion = suggest_web_for_chat(
        query=query,
        internet_mode="none",
        sensitivity="normal",
    )

    assert is_at0_self_query(query) is True
    assert suggestion is not None
    assert suggestion.reason == "current_information_likely"
    assert chat._should_short_circuit_web_suggestion(suggestion) is False


def test_eval_current_capabilities_is_self_query_not_stale_fact() -> None:
    query = "Can you know yourself and your current capabilities? Explain how."
    suggestion = suggest_web_for_chat(
        query=query,
        internet_mode="none",
        sensitivity="normal",
    )

    assert is_at0_self_query(query) is True
    assert suggestion is not None
    assert suggestion.reason == "current_information_likely"
    assert chat._should_short_circuit_web_suggestion(suggestion) is False


def test_conversation_quality_voice_response_stays_brief_and_conversational() -> None:
    response = chat._conversation_quality_response(
        "How do we improve conversation quality in chat and voice?",
        "voice",
    )

    assert response is not None
    assert len(response.split()) <= 45
    assert "**" not in response
    assert "\n" not in response
    assert "Beacon update" not in response
    assert "macOS" not in response


def test_voice_latency_question_uses_conversation_quality_contract() -> None:
    response = chat._conversation_quality_response(
        "How do we make your voice response feel near real time?",
        "voice",
    )

    assert response is not None
    assert len(response.split()) <= 45
    assert "latency" in response
    assert "**" not in response
    assert "\n" not in response


def test_conversation_quality_chat_response_is_detailed_and_structured() -> None:
    response = chat._conversation_quality_response(
        "What is the best way to improve AT-0 conversation quality in chat and voice?",
        "chat",
    )

    assert response is not None
    assert "eval-driven" in response
    assert "- Chat should be fuller" in response
    assert "- Voice should be short" in response
    assert "- Avatar should be even tighter" in response
    assert len(response.split()) > 80
    assert "Beacon update" not in response
    assert "macOS" not in response


def test_at0_self_quick_response_is_concise_for_voice_capabilities() -> None:
    response = chat._at0_self_quick_response(
        "Can you explain what you can do, what you can’t do, and what you know about me?",
        "voice",
    )

    assert response is not None
    assert "I can chat" in response
    assert "approved memory" in response
    assert "Beacon" in response
    assert len(response.split()) <= 40
    assert "Please note" not in response


def test_at0_self_quick_response_explains_web_search_without_fail_closed_copy() -> None:
    response = chat._at0_self_quick_response(
        "In avatar mode, how do I make you search the internet?",
        "avatar",
    )

    assert response is not None
    assert "Turn on Web search" in response
    assert "I need Beacon to check" not in response
