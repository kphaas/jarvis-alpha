from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PAGE = ROOT / "ui/src/App.tsx"
LAYOUT = ROOT / "ui/src/components/Layout.tsx"
ASK_PAGE = ROOT / "ui/src/pages/Ask.tsx"
ASK_SMOKE = ROOT / "scripts/smoke_alpha_ask_ui.py"


def test_alpha_ask_page_is_mounted_in_alpha_ui() -> None:
    app_source = APP_PAGE.read_text(encoding="utf-8")
    layout_source = LAYOUT.read_text(encoding="utf-8")

    assert "const Ask = lazy(() => import('./pages/Ask'))" in app_source
    assert 'path="/ask"' in app_source
    assert '<Navigate to="/" replace />' not in app_source
    assert "to: '/ask'" in layout_source
    assert "label: 'Ask'" in layout_source
    assert "MessageSquare" in layout_source


def test_alpha_ask_page_streams_chat_through_api_wrapper() -> None:
    source = ASK_PAGE.read_text(encoding="utf-8")

    assert "apiFetch('/v1/chat/completions'" in source
    assert "Accept: 'text/event-stream'" in source
    assert "internet_mode: mode" in source
    assert "ReadableStream<Uint8Array>" in source
    assert "body.getReader()" in source
    assert "TextDecoder" in source
    assert "data:'" in source or "data:" in source
    assert "payload.delta" in source
    assert "payload.done === true" in source
    assert "fetch(" not in source
    assert "XMLHttpRequest" not in source


def test_alpha_ask_page_exposes_beacon_modes_and_evidence() -> None:
    source = ASK_PAGE.read_text(encoding="utf-8")

    assert "type InternetMode = 'none' | 'web_search' | 'deep_research'" in source
    assert "MODE_OPTIONS" in source
    assert "Beacon Evidence" in source
    assert "internet_source_quality_status" in source
    assert "internet_citation_count" in source
    assert "internet_accepted_citation_count" in source
    assert "raw_web_content_is_untrusted" in source
    assert "citations.slice(0, 8)" in source
    assert "source_url" in source


def test_alpha_ask_page_surfaces_browser_approval_path() -> None:
    source = ASK_PAGE.read_text(encoding="utf-8")

    assert "apiJson<PendingApprovalsPayload>('/v1/approvals/pending')" in source
    assert "isBeaconBrowserApproval" in source
    assert "beacon_browser_use" in source
    assert "Browser Approvals" in source
    assert 'to="/approvals"' in source


def test_alpha_ask_browser_route_has_smoke_script() -> None:
    source = ASK_SMOKE.read_text(encoding="utf-8")

    assert "Smoke the Alpha /ask browser route" in source
    assert 'f"{base_url.rstrip(' in source
    assert "/ask" in source
    assert 'npm", "run", "dev"' in source
    assert 'Accept": "text/html"' in source
    assert "AT-0 Alpha" in source
    assert "/v1/chat/completions" not in source
