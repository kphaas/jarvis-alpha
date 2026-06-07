from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_alpha_ask_page_redirects_out_of_alpha_ui() -> None:
    app_source = (ROOT / "ui/src/App.tsx").read_text()

    assert "lazy(() => import('./pages/Ask'))" not in app_source
    assert '<Route path="/ask" element={<Navigate to="/" replace />} />' in app_source


def test_alpha_navigation_does_not_advertise_ask() -> None:
    layout_source = (ROOT / "ui/src/components/Layout.tsx").read_text()

    assert "to: '/ask'" not in layout_source
    assert "MessageSquare" not in layout_source
    assert "location.pathname === '/ask'" not in layout_source
