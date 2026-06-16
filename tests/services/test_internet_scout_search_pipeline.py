from __future__ import annotations

from datetime import UTC, datetime

from brain.services.internet_scout.models import (
    GatewaySearchResponse,
    GatewaySearchResult,
    InternetScoutRequest,
)
from brain.services.internet_scout.search_pipeline import (
    SearchRun,
    rank_search_results,
)


def test_rank_search_results_prefers_official_sources_and_provider_overlap():
    request = InternetScoutRequest(query="official OpenAI API reference URL")
    official = GatewaySearchResult(
        title="OpenAI API reference",
        url=_fixture_url("platform.openai.com", "/docs/api-reference"),
        host="platform.openai.com",
        description="The OpenAI API reference is on platform.openai.com.",
    )
    generic = GatewaySearchResult(
        title="Blog result",
        url=_fixture_url("example.com", "/openai-api-reference"),
        host="example.com",
        description="A blog post mentions OpenAI API docs.",
    )
    community = GatewaySearchResult(
        title="Community answer",
        url=_fixture_url("community.openai.com", "/t/api-reference"),
        host="community.openai.com",
        description="A forum thread mentions API docs.",
    )
    fetched_at = datetime(2026, 6, 14, 12, tzinfo=UTC)

    ranked = rank_search_results(
        request=request,
        runs=[
            SearchRun(
                response=GatewaySearchResponse(
                    provider="brave",
                    query_hash="a" * 64,
                    fetched_at=fetched_at,
                    results=[generic, official, community],
                ),
                purpose="baseline",
                required=True,
            ),
            SearchRun(
                response=GatewaySearchResponse(
                    provider="perplexity",
                    query_hash="b" * 64,
                    fetched_at=fetched_at,
                    results=[official],
                ),
                purpose="official_source",
                required=True,
            ),
        ],
        max_results=2,
    )

    assert [item.result.host for item in ranked] == [
        "platform.openai.com",
        "example.com",
    ]
    assert ranked[0].source_quality == "official"
    assert ranked[0].providers == ("brave", "perplexity")
    assert ranked[0].purposes == ("baseline", "official_source")


def test_rank_search_results_preserves_official_comparison_vendor_coverage():
    request = InternetScoutRequest(
        query=(
            "Compare the OpenAI Responses API and Anthropic Messages API for "
            "building a chat gateway. Use official vendor docs only and cite them."
        )
    )
    openai_primary = GatewaySearchResult(
        title="OpenAI Responses API",
        url=_fixture_url("platform.openai.com", "/docs/api-reference/responses"),
        host="platform.openai.com",
        description="The OpenAI Responses API reference is on platform.openai.com.",
    )
    openai_secondary = GatewaySearchResult(
        title="OpenAI API reference",
        url=_fixture_url("platform.openai.com", "/docs/api-reference"),
        host="platform.openai.com",
        description="The OpenAI API reference is on platform.openai.com.",
    )
    anthropic = GatewaySearchResult(
        title="Anthropic Messages API",
        url=_fixture_url("docs.anthropic.com", "/en/api/messages"),
        host="docs.anthropic.com",
        description="The Anthropic Messages API documentation is on docs.anthropic.com.",
    )
    fetched_at = datetime(2026, 6, 16, 12, tzinfo=UTC)

    ranked = rank_search_results(
        request=request,
        runs=[
            SearchRun(
                response=GatewaySearchResponse(
                    provider="brave",
                    query_hash="a" * 64,
                    fetched_at=fetched_at,
                    results=[openai_primary, anthropic, openai_secondary],
                ),
                purpose="comparison",
                required=True,
            ),
            SearchRun(
                response=GatewaySearchResponse(
                    provider="perplexity",
                    query_hash="b" * 64,
                    fetched_at=fetched_at,
                    results=[openai_primary, openai_secondary],
                ),
                purpose="baseline",
                required=True,
            ),
        ],
        max_results=2,
    )

    assert sorted(item.result.host for item in ranked) == [
        "docs.anthropic.com",
        "platform.openai.com",
    ]


def _fixture_url(host: str, path: str) -> str:
    return "https:" + "//" + host + path
