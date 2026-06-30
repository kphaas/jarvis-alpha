from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ANSWER_SUMMARY = (
    REPO_ROOT / "ui" / "src" / "components" / "beacon" / "BeaconAnswerSummary.tsx"
)
RESEARCH_COCKPIT = (
    REPO_ROOT / "ui" / "src" / "components" / "beacon" / "BeaconResearchPlanStrip.tsx"
)
BEACON_PAGE = REPO_ROOT / "ui" / "src" / "pages" / "Beacon.tsx"
BEACON_TYPES = REPO_ROOT / "ui" / "src" / "types" / "beacon.ts"


def test_beacon_answer_workspace_prioritizes_answer_over_debug_context() -> None:
    source = ANSWER_SUMMARY.read_text(encoding="utf-8")

    assert "Answer workspace" in source
    assert "report.summary" in source
    assert "report.key_findings" in source
    assert "Evidence prompt context" in source
    assert "<details" in source


def test_beacon_deep_research_cockpit_shows_plan_and_ranked_sources() -> None:
    source = RESEARCH_COCKPIT.read_text(encoding="utf-8")

    assert "Deep research cockpit" in source
    assert "Plan, coverage, and source ranking" in source
    assert "Exportable citation bundle" in source
    assert "Bundle redacted" in source
    assert "Review raw fields" in source
    assert "raw_web_content_included" in source
    assert "raw_user_query_included" in source
    assert "Progress" in source
    assert "Export report" in source
    assert "Export evidence" in source
    assert "beacon-research-report.md" in source
    assert "beacon-evidence-bundle.json" in source
    assert "Subquestions" in source
    assert "Ranked sources" in source
    assert "source_rankings" in source
    assert "Stop criteria" in source
    assert "Eval gates" in source
    assert "covered_official_target_count" in source
    assert "verified_claim_count" in source
    types = BEACON_TYPES.read_text(encoding="utf-8")
    assert "report_markdown" in types
    assert "BeaconEvidenceBundle" in types
    assert "raw_web_content_included" in types


def test_beacon_page_streams_deep_research_steps() -> None:
    source = BEACON_PAGE.read_text(encoding="utf-8")
    types = BEACON_TYPES.read_text(encoding="utf-8")

    assert "/v1/internet-scout/local-llm/tool/stream" in source
    assert "Live research trace" in source
    assert "Export ready" in source
    assert "providerRoute" in source
    assert "parseBeaconStreamFrame" in source
    assert "evidence_bundle" in source
    assert "BeaconResearchProgressEvent" in types
    assert "max_searches" in types
    assert "expected_source_types" in types


def test_beacon_page_surfaces_product_mode_defaults() -> None:
    source = BEACON_PAGE.read_text(encoding="utf-8")
    config = (
        REPO_ROOT / "ui" / "src" / "components" / "beacon" / "modeConfig.ts"
    ).read_text(encoding="utf-8")
    types = BEACON_TYPES.read_text(encoding="utf-8")

    assert "BeaconModeRunContract" in source
    assert "Source policy" in source
    assert "Provider route" in source
    assert "Extract budget" in source
    assert "Page cap" in source
    assert "activeMode.maxPages" in source
    assert "runLabel" in config
    assert "sourcePolicy" in config
    assert "providerStrategy" in config
    assert "extractBudget" in config
    assert "SearXNG + Brave + Perplexity fanout" in config
    assert "Free source router" in config
    assert "maxPages: 4" in config
    assert "sourcePolicy: string" in types


def test_beacon_page_can_queue_browser_action_approvals() -> None:
    source = BEACON_PAGE.read_text(encoding="utf-8")
    types = BEACON_TYPES.read_text(encoding="utf-8")

    assert "Browser action approval" in source
    assert "/v1/internet-scout/browser-task/approval-request" in source
    assert "browser_clicks" in source
    assert "Queue approval" in source
    assert 'to="/approvals"' in source
    assert "BeaconBrowserApprovalResponse" in types
