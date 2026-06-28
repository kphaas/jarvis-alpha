from __future__ import annotations

from datetime import date
from pathlib import Path

from brain.services.herald_social import (
    create_social_draft,
    hash_social_draft,
    linkedin_weekly_topic,
    normalize_platforms,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260626_120000_herald_social_outbox.sql"
)
ROUTE = REPO_ROOT / "brain" / "routes" / "herald_social.py"
SERVICE = REPO_ROOT / "brain" / "services" / "herald_social.py"
LINKEDIN_WEEKLY_MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260627_010000_herald_linkedin_weekly.sql"
)
LINKEDIN_PUBLISH_MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260627_120000_herald_linkedin_publish.sql"
)
LINKEDIN_ENGAGEMENT_MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260627_160000_herald_linkedin_engagement_inbox.sql"
)


def test_social_draft_is_draft_only_and_brand_linted() -> None:
    draft = create_social_draft(
        topic="Show the approved Herald social outbox before any platform connector.",
        platform="x",
        max_chars=280,
    )

    assert len(draft.draft_text) <= 280
    assert "AT0" in draft.draft_text
    assert "AT-0" not in draft.draft_text
    assert "draft_only_no_publish" in draft.safety_flags
    assert "human_review_required" in draft.safety_flags
    assert draft.content_hash == hash_social_draft(draft.draft_text)


def test_linkedin_reply_draft_is_reviewed_engagement_only() -> None:
    draft = create_social_draft(
        topic="Agree on the need for human review before agents speak for a brand.",
        platform="linkedin",
        max_chars=3000,
        draft_kind="reply",
        engagement_author="Sam",
    )

    assert "Thanks Sam" in draft.draft_text
    assert "clear trail" in draft.draft_text
    assert "draft_only_no_publish" in draft.safety_flags
    assert "human_review_required" in draft.safety_flags

    try:
        create_social_draft(
            topic="Reply somewhere else.",
            platform="x",
            max_chars=280,
            draft_kind="reply",
        )
    except ValueError as exc:
        assert "reply_drafts_linkedin_only" in str(exc)
    else:
        raise AssertionError("reply drafts should be LinkedIn-only for this slice")


def test_linkedin_draft_uses_spark_context_without_leaking_raw_context() -> None:
    draft = create_social_draft(
        topic="Explain why approval gates matter.",
        platform="linkedin",
        max_chars=3000,
        spark_context="[WHO YOU'RE TALKING TO]\n- Voice: concise and low-hype",
    )

    assert "spark_context_used" in draft.safety_flags
    assert draft.spark_context_hash
    assert "WHO YOU'RE TALKING TO" not in draft.draft_text
    assert "low-hype" not in draft.draft_text
    assert "public bar practical" in draft.draft_text


def test_linkedin_weekly_topic_rotates_without_external_inputs() -> None:
    first = linkedin_weekly_topic(date(2026, 6, 27))
    second = linkedin_weekly_topic(date(2026, 7, 4))

    assert first
    assert second
    assert first != second
    assert "http" not in first.lower()
    assert any(
        term in f"{first} {second}"
        for term in ("Enterprise AI", "enterprise transformation", "AT0")
    )


def test_linkedin_weekly_auto_draft_is_draft_only_and_deduped() -> None:
    source = SERVICE.read_text(encoding="utf-8")

    assert "create_weekly_linkedin_draft_if_due" in source
    assert "active_weekly_draft_exists" in source
    assert "linkedin-weekly-brand" in source
    assert "human_review_required" in source
    assert "publish_linkedin_text" not in source
    assert "publish_linkedin_comment" not in source


def test_linkedin_cadence_counts_live_and_manual_publish_receipts() -> None:
    source = ROUTE.read_text(encoding="utf-8")

    assert "'manual_published', 'linkedin_published'" in source


def test_platform_normalization_deduplicates_and_rejects_unknowns() -> None:
    assert normalize_platforms(["X", "linkedin", "x"]) == ("x", "linkedin")

    try:
        normalize_platforms(["postiz"])
    except ValueError as exc:
        assert "unsupported_platform:postiz" in str(exc)
    else:
        raise AssertionError("unsupported platform should fail closed")


def test_social_outbox_migration_is_local_only_and_append_only() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    for table in (
        "public.alpha_herald_social_platform_profiles",
        "public.alpha_herald_social_draft_requests",
        "public.alpha_herald_social_draft_variants",
        "public.alpha_herald_social_draft_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in source
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in source

    assert "alpha_herald_social_draft_events_immutable" in source
    assert "No social platform publish connector exists here" in source
    assert "Postiz" not in source
    assert "Buffer" not in source


def test_linkedin_weekly_migration_adds_schedule_and_receipt_state() -> None:
    source = LINKEDIN_WEEKLY_MIGRATION.read_text(encoding="utf-8")

    for column in (
        "draft_kind",
        "engagement_author",
        "scheduled_for",
        "publish_status",
        "published_at",
        "published_url",
    ):
        assert column in source
    assert "variant_scheduled" in source
    assert "variant_manual_published" in source
    assert "No platform connector is invoked" in source
    assert "Postiz" not in source
    assert "Buffer" not in source


def test_linkedin_publish_migration_adds_approved_publish_state() -> None:
    source = LINKEDIN_PUBLISH_MIGRATION.read_text(encoding="utf-8")

    for value in (
        "sending",
        "linkedin_published",
        "publish_failed",
        "variant_linkedin_publish_started",
        "variant_linkedin_published",
        "variant_linkedin_publish_failed",
        "provider_post_urn",
    ):
        assert value in source
    assert "access_token" not in source


def test_linkedin_engagement_migration_adds_needs_reply_inbox() -> None:
    source = LINKEDIN_ENGAGEMENT_MIGRATION.read_text(encoding="utf-8")

    assert "public.alpha_herald_social_engagement_items" in source
    assert "needs_reply" in source
    assert "draft_created" in source
    assert "reply_variant_id" in source
    assert "r_member_social" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "access_token" not in source
    assert "client_secret" not in source


def test_social_routes_publish_only_through_linkedin_connector() -> None:
    source = ROUTE.read_text(encoding="utf-8")

    assert "/v1/herald/social" in source
    assert "/linkedin/weekly" in source
    assert "/linkedin/cadence" in source
    assert "/linkedin/read-plan" in source
    assert "/linkedin/engagements" in source
    assert "/linkedin/ingest" in source
    assert "/draft-reply" in source
    assert "/publish-reply" in source
    assert "/schedule" in source
    assert "/publish/manual" in source
    assert "/publish/linkedin" in source
    assert "create_social_draft" in source
    assert "fetch_linkedin_comments" in source
    assert "publish_linkedin_comment" in source
    assert "publish_linkedin_text" in source
    assert "alpha_herald_social_draft_events" in source
    assert "alpha_herald_social_engagement_items" in source
    assert "planned_pending_linkedin_approval" in source
    assert "r_member_social_feed" in source
    assert "send_at0_mail_reply" not in source
    assert "requests.post" not in source
    assert "aiohttp" not in source
    assert "browser" not in source.lower()
    assert "postiz" not in source.lower()
    assert "buffer" not in source.lower()
