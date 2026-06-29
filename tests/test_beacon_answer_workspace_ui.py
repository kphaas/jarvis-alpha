from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ANSWER_SUMMARY = (
    REPO_ROOT
    / "ui"
    / "src"
    / "components"
    / "beacon"
    / "BeaconAnswerSummary.tsx"
)
RESEARCH_COCKPIT = (
    REPO_ROOT
    / "ui"
    / "src"
    / "components"
    / "beacon"
    / "BeaconResearchPlanStrip.tsx"
)


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
    assert "Subquestions" in source
    assert "Ranked sources" in source
    assert "source_rankings" in source
    assert "Stop criteria" in source
