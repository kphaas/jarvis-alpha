from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PRIVACY_PAGE = REPO_ROOT / "ui" / "src" / "pages" / "Privacy.tsx"
APPROVALS_PAGE = REPO_ROOT / "ui" / "src" / "pages" / "Approvals.tsx"
PRIVACY_UI_SOURCES = (
    PRIVACY_PAGE,
    REPO_ROOT / "ui" / "src" / "hooks" / "usePrivacyIntake.ts",
    REPO_ROOT / "ui" / "src" / "hooks" / "usePrivacyApprovedActions.ts",
    REPO_ROOT / "ui" / "src" / "hooks" / "usePrivacyCaseDraft.ts",
    REPO_ROOT / "ui" / "src" / "hooks" / "usePrivacyDraftInbox.ts",
    REPO_ROOT / "ui" / "src" / "hooks" / "usePrivacyTargets.ts",
    REPO_ROOT / "ui" / "src" / "lib" / "privacyIntake.ts",
    REPO_ROOT / "ui" / "src" / "types" / "privacy.ts",
    *(REPO_ROOT / "ui" / "src" / "components" / "privacy").glob("*.tsx"),
)


def test_privacy_intake_ui_is_mounted_in_alpha_app() -> None:
    app_source = (REPO_ROOT / "ui" / "src" / "App.tsx").read_text(encoding="utf-8")
    layout_source = (REPO_ROOT / "ui" / "src" / "components" / "Layout.tsx").read_text(
        encoding="utf-8"
    )

    assert "const Privacy = lazy(() => import('./pages/Privacy'))" in app_source
    assert 'path="/privacy"' in app_source
    assert "label: 'Privacy'" in layout_source
    assert "Fingerprint" in layout_source


def test_privacy_intake_ui_uses_p2b_routes_and_api_wrapper() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in PRIVACY_UI_SOURCES)

    assert "apiFetch" in source
    assert "/v1/privacy/subjects" in source
    assert "/identity-tuples" in source
    assert "/v1/privacy/targets" in source
    assert "/v1/privacy/targets/refresh" in source
    assert "fetch(" not in source
    assert "XMLHttpRequest" not in source


def test_privacy_review_packet_panel_is_mounted_on_privacy_page() -> None:
    page_source = PRIVACY_PAGE.read_text(encoding="utf-8")
    source = "\n".join(path.read_text(encoding="utf-8") for path in PRIVACY_UI_SOURCES)

    assert "usePrivacyCaseDraft(subjectId, targets.selectedIds)" in page_source
    assert "<PrivacyCaseDraftPanel" in page_source
    assert "targets.clearSelection();" in page_source
    assert "draftInbox.refreshDrafts();" in page_source
    assert "/case-drafts" in source
    assert "Review Packet" in source


def test_privacy_draft_inbox_is_mounted_on_privacy_page() -> None:
    page_source = PRIVACY_PAGE.read_text(encoding="utf-8")
    source = "\n".join(path.read_text(encoding="utf-8") for path in PRIVACY_UI_SOURCES)

    assert 'usePrivacyDraftInbox(searchParams.get("case"))' in page_source
    assert "<PrivacyDraftInboxPanel" in page_source
    assert "P3-G - manual action workflow" in page_source
    assert "P2-F - draft review inbox" not in page_source
    assert "/v1/privacy/case-drafts" in source
    assert "submit-approval" in source
    assert "archive" in source
    assert "Submit for approval" in source
    assert "Archive" in source
    assert "Draft Inbox" in source
    assert "No targets in this filter" in source
    assert "shown /" in source


def test_privacy_approved_actions_panel_is_mounted_on_privacy_page() -> None:
    page_source = PRIVACY_PAGE.read_text(encoding="utf-8")
    source = "\n".join(path.read_text(encoding="utf-8") for path in PRIVACY_UI_SOURCES)

    assert "usePrivacyApprovedActions()" in page_source
    assert "<PrivacyApprovedActionsPanel" in page_source
    assert "/v1/privacy/actions/approved" in source
    assert "/manual-disposition" in source
    assert "/verification" in source
    assert "/timeline" in source
    assert "/report" in source
    assert "Approved Actions" in source
    assert "Ready for manual operator handling" in source
    assert "Record disposition" in source
    assert "Record verification" in source
    assert "Case report" in source


def test_privacy_approval_handoff_ui_links_to_review_packet() -> None:
    approvals_source = APPROVALS_PAGE.read_text(encoding="utf-8")
    privacy_source = PRIVACY_PAGE.read_text(encoding="utf-8")
    hook_source = (
        REPO_ROOT / "ui" / "src" / "hooks" / "usePrivacyDraftInbox.ts"
    ).read_text(encoding="utf-8")
    panel_source = (
        REPO_ROOT
        / "ui"
        / "src"
        / "components"
        / "privacy"
        / "PrivacyDraftInboxPanel.tsx"
    ).read_text(encoding="utf-8")

    assert "privacy_draft_handoff" in approvals_source
    assert "/privacy?case=" in approvals_source
    assert "Review packet" in approvals_source
    assert "useSearchParams" in privacy_source
    assert 'usePrivacyDraftInbox(searchParams.get("case"))' in privacy_source
    assert "initialCaseId" in hook_source
    assert "Approval queue" in panel_source


def test_privacy_intake_ui_keeps_phase_boundary_local_only() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in PRIVACY_UI_SOURCES)
    forbidden = (
        "requests",
        "httpx",
        "playwright",
        "selenium",
        "smtp",
        "scrape",
        "runner",
        "approval_queue",
        "send_opt_out",
        "alpha_privacy_actions",
    )

    for token in forbidden:
        assert token not in source
