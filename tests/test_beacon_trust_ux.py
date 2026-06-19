from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TRANSPARENCY_PANEL = (
    REPO_ROOT
    / "ui"
    / "src"
    / "components"
    / "beacon"
    / "BeaconEvidenceTransparencyPanel.tsx"
)


def test_beacon_evidence_panel_surfaces_trust_chips_and_source_groups() -> None:
    source = TRANSPARENCY_PANEL.read_text(encoding="utf-8")

    assert "Why this answer is trustworthy" in source
    assert "AnswerQualityBadge" in source
    assert "Answer quality" in source
    assert "source_diversity_score" in source
    assert "official_coverage_score" in source
    assert "freshness_score" in source
    assert "rejected_risk_score" in source
    assert "rejected-risk source" in source
    assert "TrustSummaryChip" in source
    assert "buildTrustChips" in source
    assert "Evidence accepted" in source
    assert "Official matched" in source
    assert "Unsupported blocked" in source
    assert "Freshness checked" in source
    assert "Rejections visible" in source

    assert "groupEvidence" in source
    assert "EvidenceGroup" in source
    assert "source_quality" in source
    assert "source{group.items.length === 1 ? '' : 's'} grouped" in source
