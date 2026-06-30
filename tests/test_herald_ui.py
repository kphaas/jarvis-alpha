from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HERALD_PAGE = REPO_ROOT / "ui" / "src" / "pages" / "Herald.tsx"
HEALTH_PAGE = REPO_ROOT / "ui" / "src" / "pages" / "Health.tsx"
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
    assert "/v1/at0-mail/drafts?status=all&limit=12${mailboxQuery}" in source
    assert "/v1/at0-mail/scan?max_results=25${mailboxQuery}" in source
    assert "/v1/at0-mail/drafts/${draftId}/send" in source
    assert "apiJson<HealthResponse>('/v1/at0-mail/health')" in source
    assert "latest_graph_health" in source
    assert "Graph send" in source
    assert "Mail.Send" in source
    assert "current_send_failures" in source
    assert "stuck_sending_count" in source
    assert "Send reply" in source
    assert "AT-0 Spark drafts" in source
    assert "fetch(" not in source
    assert "XMLHttpRequest" not in source


def test_herald_ui_exposes_social_approval_outbox() -> None:
    source = HERALD_PAGE.read_text(encoding="utf-8")

    assert "apiJson<SocialPlatformList>('/v1/herald/social/platforms')" in source
    assert (
        "apiJson<SocialDraftList>('/v1/herald/social/drafts?status=all&limit=12')"
        in source
    )
    assert "apiJson<LinkedInCadence>('/v1/herald/social/linkedin/cadence')" in source
    assert "apiJson<LinkedInReadPlan>('/v1/herald/social/linkedin/read-plan')" in source
    assert (
        "apiJson<LinkedInOperatorDashboard>('/v1/herald/social/linkedin/operator-dashboard')"
        in source
    )
    assert (
        "apiJson<ThoughtLeaderTargetList>('/v1/herald/social/linkedin/thought-leaders?status=active&limit=8')"
        in source
    )
    assert (
        "apiJson<ThoughtLeaderTarget>('/v1/herald/social/linkedin/thought-leaders'"
        in source
    )
    assert (
        "apiJson<LinkedInMetricResponse>('/v1/herald/social/linkedin/metrics'"
        in source
    )
    assert (
        "apiJson<SocialEngagementList>('/v1/herald/social/linkedin/engagements?status=all&limit=12')"
        in source
    )
    assert (
        "apiJson<SocialEngagement>('/v1/herald/social/linkedin/engagements'" in source
    )
    assert (
        "apiJson<LinkedInScoutResponse>('/v1/herald/social/linkedin/engagements/scout'"
        in source
    )
    assert "/v1/herald/social/linkedin/engagements/${itemId}/draft-reply" in source
    assert "/v1/herald/social/linkedin/engagements/${itemId}/publish-reply" in source
    assert "/v1/herald/social/linkedin/engagements/${itemId}/status" in source
    assert "apiJson<SocialDraftCreateResponse>('/v1/herald/social/drafts'" in source
    assert (
        "apiJson<SocialDraftCreateResponse>('/v1/herald/social/linkedin/weekly'"
        in source
    )
    assert "/v1/herald/social/drafts/${draftId}/status" in source
    assert "/v1/herald/social/drafts/${draftId}/schedule" in source
    assert "/v1/herald/social/drafts/${draftId}/publish/manual" in source
    assert "/v1/herald/social/drafts/${draftId}/publish/linkedin" in source
    assert "Social approval outbox" in source
    assert "Draft weekly LinkedIn" in source
    assert "Post due" in source
    assert "Best topic" in source
    assert "Thought-leader target graph" in source
    assert "Analytics feedback loop" in source
    assert "Record metrics" in source
    assert "Add target" in source
    assert "LinkedIn engagement inbox" in source
    assert "Scout targets" in source
    assert "Add to inbox" in source
    assert "Draft reply" in source
    assert "LinkedIn reply options created" in source
    assert "Feedback for rejection or next draft" in source
    assert "replyStyleLabel" in source
    assert "Strong short" in source
    assert "reviewer_notes" in source
    assert "r_member_social_feed" in source
    assert "Post to LinkedIn" in source
    assert "Post reply" in source
    assert "Mark published" in source
    assert "publish_failed" in source
    assert 'type="date"' in source
    assert "publish_status" in source
    assert "draft_kind" in source
    assert "safety_flags.map" in source
    assert "toggleSocialPlatform" in source
    assert "Draft social" in source
    assert "Archive" in source
    assert "Postiz" not in source
    assert "Buffer" not in source


def test_health_ui_surfaces_herald_graph_send_monitor() -> None:
    source = HEALTH_PAGE.read_text(encoding="utf-8")

    assert 'apiJson<At0MailHealthPayload>("/v1/at0-mail/health")' in source
    assert "Herald Graph Send Health" in source
    assert "latest_graph_health" in source
    assert "Mail.Send" in source
    assert "current_send_failures" in source
    assert "stuck_sending_count" in source
