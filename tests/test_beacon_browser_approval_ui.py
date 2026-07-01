from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APPROVALS = REPO_ROOT / "ui" / "src" / "pages" / "Approvals.tsx"
PANEL = (
    REPO_ROOT
    / "ui"
    / "src"
    / "components"
    / "beacon"
    / "BeaconBrowserApprovalPanel.tsx"
)


def test_beacon_browser_approval_ui_surfaces_v2_review_contract() -> None:
    source = PANEL.read_text(encoding="utf-8")

    assert "interface BeaconScreenshotPolicy" in source
    assert "interface BeaconActionTimelineItem" in source
    assert "export interface BeaconApprovalContext" in source
    assert "approval_contract_version" in source
    assert "allowed_hosts" in source
    assert "url_hashes" in source
    assert "screenshot_policy" in source
    assert "screenshots_available_after_run" in source
    assert "screenshot_refs_redacted_until_execution" in source
    assert "credential_entry_allowed" in source
    assert "risk_labels" in source
    assert "interface BeaconClickTarget" in source
    assert "click_targets" in source
    assert "action_timeline" in source


def test_beacon_browser_approval_ui_has_operator_review_sections() -> None:
    source = PANEL.read_text(encoding="utf-8")

    assert "Beacon browser approval" in source
    assert "Review summary" in source
    assert "Same-host lock" in source
    assert "Screenshots staged" in source
    assert "Click targets" in source
    assert "No credential entry" in source
    assert "Host allowlist" in source
    assert "URL hashes" in source
    assert "Screenshot review" in source
    assert "Blocked capabilities" in source
    assert "Credential entry" in source
    assert "Risk labels" in source
    assert "Action timeline" in source
    assert "Click target review" in source
    assert "Only listed selectors can run after approval." in source
    assert "same host only" in source
    assert "Interaction requested, but no click targets were reported." in source
    assert "expected host" in source
    assert "Decision boundary" in source
    assert "Approve plan" in source
    assert "Deny plan" in source
    assert "Runs only this reviewed browser plan" in source
    assert "Leaves the browser runtime untouched" in source


def test_beacon_browser_approval_ui_keeps_url_and_screenshot_refs_redacted() -> None:
    source = PANEL.read_text(encoding="utf-8")

    assert "shortEvidenceHash" in source
    assert "Screenshot files stay private" in source
    assert "content-addressed refs after execution" in source
    assert "raw_task_text_included ? 'included' : 'hidden'" in source
    assert "raw_web_content_is_untrusted ? 'untrusted evidence' : 'trusted'" in source


def test_approvals_page_uses_beacon_browser_approval_panel() -> None:
    source = APPROVALS.read_text(encoding="utf-8")

    assert "BeaconBrowserApprovalPanel, type BeaconApprovalContext" in source
    assert (
        "<BeaconBrowserApprovalPanel beacon={item.beacon} isDark={isDark} />" in source
    )


def test_approvals_page_surfaces_browser_execution_history() -> None:
    source = APPROVALS.read_text(encoding="utf-8")

    assert "new URLSearchParams" in source
    assert "offset: String(historyOffset)" in source
    assert "historyParams.set('q', trimmedQuery)" in source
    assert "historyParams.set('event_type', historyEventType)" in source
    assert "Browser execution history" in source
    assert "History summary" in source
    assert "latest page only" in source
    assert "historyDisplayStatus" in source
    assert "executed" in source
    assert "denied" in source
    assert "expired" in source
    assert "} obs" in source
    assert "} shots" in source
    assert "} audit" in source
    assert "Technical audit" in source
    assert "historyHasMore" in source
    assert "Search request, approval, host" in source
    assert "Approval requests" in source
    assert "Browser runs" in source
    assert "Action events" in source
    assert "Blocked or failed" in source
    assert "Previous" in source
    assert "Next" in source
    assert "interface BrowserHistoryItem" in source
    assert "approval_queue_id" in source
    assert "browser_action" in source
    assert "Audited actions" in source
    assert "Browser history unavailable" in source


def test_approvals_page_marks_beacon_decision_boundary() -> None:
    source = APPROVALS.read_text(encoding="utf-8")

    assert "Decision applies to the reviewed Beacon browser plan" in source
    assert "item.beacon ? 'Approve plan' : 'Approve'" in source
    assert "item.beacon ? 'Deny plan' : 'Deny'" in source
