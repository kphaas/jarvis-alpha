from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "ui" / "src" / "App.tsx"
LAYOUT = REPO_ROOT / "ui" / "src" / "components" / "Layout.tsx"
BEACON_OPS = REPO_ROOT / "ui" / "src" / "pages" / "BeaconOps.tsx"
TRACKER = REPO_ROOT / "docs" / "state" / "BEACON_INDUSTRY_GAP_TRACKER.md"


def test_beacon_ops_dashboard_is_routed_and_nav_visible() -> None:
    app = APP.read_text(encoding="utf-8")
    layout = LAYOUT.read_text(encoding="utf-8")

    assert "const BeaconOps = lazy(() => import('./pages/BeaconOps'))" in app
    assert '<Route path="/beacon/ops" element={<BeaconOps />} />' in app
    assert "{ to: '/beacon/ops', label: 'Beacon Ops'" in layout
    assert "end={item.to === '/' || item.to === '/beacon'}" in layout


def test_beacon_ops_dashboard_surfaces_core_slo_sections() -> None:
    source = BEACON_OPS.read_text(encoding="utf-8")

    assert "apiJson<HelmSummaryPayload>('/v1/helm/summary')" in source
    assert "Answer Latency" in source
    assert "Provider State" in source
    assert "Cost Guard" in source
    assert "Citation Quality" in source
    assert "Browser Approvals" in source
    assert "Data Sources" in source
    assert "Web Cache" in source
    assert "web_cache.active_entry_count" in source
    assert "web_cache.total_hit_count" in source
    assert "web_cache.raw_user_query_stored" in source
    assert "Show details" in source
    assert "Hide details" in source
    assert "aria-expanded={dataSourcesOpen}" in source
    assert "Operational Details" in source
    assert "beacon-operational-details" in source
    assert "aria-expanded={operationalDetailsOpen}" in source
    assert "aria-expanded={canaryTrendOpen}" in source
    assert "Beacon benchmark pass-rate history" in source
    assert "beacon-canary-trend-details" in source
    assert "latest_precision" in source
    assert "estimated_provider_cost_usd" in source
    assert "Operator Action" in source
    assert "exact_cost_available" in source
    assert "budget_capped_backup_provider_count" in source
    assert "data_sources.registry" in source
    assert "on_hold_data_source_ids" in source
    assert "api_base_url" in source
    assert "slo_met_percent" in source
    assert "prompt_injection_rejection_count" in source
    assert "highest_pending_risk_tier" in source


def test_beacon_ops_gap_tracker_is_marked_complete() -> None:
    tracker = TRACKER.read_text(encoding="utf-8")

    assert "| Ops SLO dashboard | Beacon now has a one-page Ops dashboard" in tracker
    assert "| 10 | Ops/SLO dashboard | Complete |" in tracker
