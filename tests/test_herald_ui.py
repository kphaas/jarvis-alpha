from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HERALD_PAGE = REPO_ROOT / "ui" / "src" / "pages" / "Herald.tsx"
APP_PAGE = REPO_ROOT / "ui" / "src" / "App.tsx"
LAYOUT = REPO_ROOT / "ui" / "src" / "components" / "Layout.tsx"


def test_herald_ui_is_mounted_in_alpha_app() -> None:
    app_source = APP_PAGE.read_text(encoding="utf-8")
    layout_source = LAYOUT.read_text(encoding="utf-8")

    assert "const Herald = lazy(() => import('./pages/Herald'))" in app_source
    assert 'path="/herald"' in app_source
    assert "label: 'Herald'" in layout_source
    assert "Inbox" in layout_source


def test_herald_ui_splits_view_by_configured_mailbox() -> None:
    source = HERALD_PAGE.read_text(encoding="utf-8")

    assert "apiJson<MailboxList>('/v1/at0-mail/mailboxes')" in source
    assert "selectedMailbox" in source
    assert "All inboxes" in source
    assert "mailbox=${encodeURIComponent(selectedMailbox)}" in source
    assert "/v1/at0-mail/messages?limit=12${mailboxQuery}" in source
    assert "/v1/at0-mail/drafts?limit=8${mailboxQuery}" in source
    assert "/v1/at0-mail/scan?max_results=25${mailboxQuery}" in source
    assert "AT-0 Spark drafts" in source
    assert "fetch(" not in source
    assert "XMLHttpRequest" not in source
