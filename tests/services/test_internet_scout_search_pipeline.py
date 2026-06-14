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


def _fixture_url(host: str, path: str) -> str:
    return "https:" + "//" + host + path
