from __future__ import annotations

import os

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://127.0.0.1:8188")

from brain.routes import chat
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

    assert prompt.index("Internet context from Alpha Beacon") < prompt.index(
        "Context from memory"
    )
    assert "If memory conflicts with Beacon, follow Beacon" in prompt
    assert "https://platform.openai.com/docs/api-reference" in prompt


def test_eval_docs_url_answer_prefers_source_url_over_endpoint_example() -> None:
    prompt = chat._build_enriched_prompt(
        memory_context="Memory says the answer is https://beta.openai.com/docs.",
        internet_context=(
            "Beacon internet mode: Deep research\n"
            "Beacon citation quality: supported\n"
            "If the user asks for a documentation page, docs URL, source URL, "
            "or official link, answer with the cited Source URL; do not substitute "
            "API endpoint examples from citation text unless the user asks for an "
            "API endpoint.\n"
            "Cited Beacon evidence:\n"
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
