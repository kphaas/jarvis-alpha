import pytest

from brain.services.internet_scout.models import InternetScoutRequest, InternetTool
from brain.services.internet_scout.research_planner import plan_research
from brain.services.internet_scout.source_selection import (
    BEACON_ON_HOLD_DATA_SOURCE_IDS,
    assert_no_on_hold_data_sources,
    select_beacon_data_source_ids,
)


@pytest.mark.parametrize(
    ("query", "expected_source_ids"),
    [
        (
            "Find PubMed studies about GLP-1 treatment outcomes",
            {"pubmed-eutils"},
        ),
        (
            "Find Apple 10-K SEC EDGAR filings and XBRL company facts",
            {"sec-edgar"},
        ),
        (
            "Check CVE-2026-12345 package vulnerability against OSV and CISA KEV",
            {"osv-dev", "cisa-kev"},
        ),
        (
            "Find scholarly citation metadata for a peer reviewed AI paper",
            {"openalex"},
        ),
    ],
)
def test_beacon_source_selection_routes_domain_queries_to_registry_sources(
    query,
    expected_source_ids,
):
    data_source_ids = set(select_beacon_data_source_ids(query, focus_mode="academic"))

    assert expected_source_ids.issubset(data_source_ids)
    assert not data_source_ids.intersection(BEACON_ON_HOLD_DATA_SOURCE_IDS)


def test_beacon_source_selection_includes_productivity_sources_only_when_requested():
    data_source_ids = set(
        select_beacon_data_source_ids(
            "Find context from Gmail, Google Drive, Outlook, and Teams",
            focus_mode="all",
        )
    )

    assert {"google-workspace", "microsoft-graph"}.issubset(data_source_ids)


def test_beacon_source_selection_blocks_on_hold_paid_sources():
    with pytest.raises(ValueError, match="quiverquant"):
        assert_no_on_hold_data_sources(["brave-search", "quiverquant"])


def test_research_plan_carries_recommended_data_sources():
    plan = plan_research(
        InternetScoutRequest(
            query="Find PubMed and OpenAlex evidence for a clinical research paper",
            focus_mode="academic",
            requester="alpha_chat.deep_research",
            max_pages=3,
        ),
        selected_tool=InternetTool.SEARCH,
    )

    assert "pubmed-eutils" in plan.recommended_data_source_ids
    assert "openalex" in plan.recommended_data_source_ids
    assert "quiverquant" not in plan.recommended_data_source_ids
    assert any(
        note.startswith("data_sources:") and "pubmed-eutils" in note
        for note in plan.notes
    )
