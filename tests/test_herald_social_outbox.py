from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest

from brain.services.internet_scout.models import (
    GatewaySearchResponse,
    GatewaySearchResult,
)
from brain.services.herald_social import (
    LINKEDIN_LEARNING_MIN_SAMPLES,
    create_social_draft,
    hash_social_draft,
    linkedin_feedback_memory_note,
    linkedin_engagement_slots_due,
    linkedin_metric_engagement_rate,
    linkedin_metric_engagement_total,
    linkedin_metric_clears_learning_threshold,
    linkedin_metric_memory_content,
    linkedin_post_urn_from_url,
    linkedin_review_friction,
    linkedin_target_scout_queries,
    linkedin_weekly_topic,
    normalize_platforms,
    scout_linkedin_engagement_targets,
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
INTERACTION_LEDGER_MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260628_130000_herald_interaction_ledger.sql"
)
ANALYTICS_TARGETS_MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260630_090000_herald_social_analytics_targets.sql"
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

    assert "enterprise AI question" in draft.draft_text
    assert "human approval trail" in draft.draft_text
    assert "draft_only_no_publish" in draft.safety_flags
    assert "human_review_required" in draft.safety_flags
    assert "reply_style_practical" in draft.safety_flags

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


def test_linkedin_reply_styles_include_strong_short_option() -> None:
    strong = create_social_draft(
        topic="AI governance should be tied to business operating models.",
        platform="linkedin",
        max_chars=3000,
        draft_kind="reply",
        engagement_author="Robert",
        reply_style="strong_short",
    )
    warm = create_social_draft(
        topic="AI governance should be tied to business operating models.",
        platform="linkedin",
        max_chars=3000,
        draft_kind="reply",
        engagement_author="Robert",
        reply_style="warm",
    )

    assert len(strong.draft_text) < 240
    assert "Strong point" in strong.draft_text
    assert "reply_style_strong_short" in strong.safety_flags
    assert "Agree with this framing" in warm.draft_text
    assert "reply_style_warm" in warm.safety_flags


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


def test_linkedin_engagement_slots_due_reaches_three_per_week() -> None:
    assert [linkedin_engagement_slots_due(day) for day in range(1, 8)] == [
        1,
        1,
        2,
        2,
        3,
        3,
        3,
    ]


def test_linkedin_target_scout_queries_focus_on_brand_topics() -> None:
    queries = linkedin_target_scout_queries(["AI governance", "AI governance"])

    assert queries == (
        "LinkedIn posts AI governance enterprise AI CIO business transformation",
    )
    assert "http" not in queries[0].lower()


def test_linkedin_post_urn_from_url_extracts_publishable_activity_urn() -> None:
    assert (
        linkedin_post_urn_from_url(
            "https://www.linkedin.com/posts/nick-kervin-6b06874_ai-is-reshaping-activity-7473177453939613696-QL_R"
        )
        == "urn:li:activity:7473177453939613696"
    )
    assert (
        linkedin_post_urn_from_url(
            "https://www.linkedin.com/feed/update/urn%3Ali%3Aactivity%3A7473177453939613696/"
        )
        == "urn:li:activity:7473177453939613696"
    )
    assert linkedin_post_urn_from_url("https://www.linkedin.com/in/someone") is None


def test_linkedin_metrics_promote_only_strong_feedback_to_spark_memory() -> None:
    total = linkedin_metric_engagement_total(
        reactions=5,
        comments=2,
        reposts=1,
        profile_clicks=0,
    )
    rate = linkedin_metric_engagement_rate(engagement_total=total, impressions=200)
    memory = linkedin_metric_memory_content(
        topic="AI operating model for enterprise transformation",
        draft_kind="post",
        reply_style="strong_short",
        engagement_total=total,
        impressions=200,
        engagement_rate=rate,
    )

    assert total == 8
    assert rate == 0.04
    assert memory is not None
    assert "Favor this topic pattern" in memory
    assert (
        linkedin_metric_memory_content(
            topic="Weak topic",
            draft_kind="post",
            reply_style="strong_short",
            engagement_total=1,
            impressions=200,
            engagement_rate=0.005,
        )
        is None
    )
    assert linkedin_metric_clears_learning_threshold(
        engagement_total=LINKEDIN_LEARNING_MIN_SAMPLES,
        engagement_rate=0.0,
    )


def test_linkedin_rejection_feedback_becomes_reviewed_memory_proposal_note() -> None:
    friction = linkedin_review_friction(
        status="rejected",
        reviewer_notes="Too long. Make comments sharper and less generic.",
        review_friction=None,
    )
    note = linkedin_feedback_memory_note(
        topic="AI operating model for enterprise transformation",
        draft_kind="reply",
        reviewer_notes="Too long. Make comments sharper and less generic.",
        review_friction=friction,
    )

    assert friction == "light_edit"
    assert note is not None
    assert note.startswith("Avoid repeating this LinkedIn reply draft pattern")
    assert "reviewer marked light edit" in note
    assert "Make comments sharper" in note
    assert (
        linkedin_review_friction(
            status="approved",
            reviewer_notes=None,
            review_friction=None,
        )
        == "as_is"
    )


@pytest.mark.asyncio
async def test_linkedin_target_scout_queues_local_review_items_only() -> None:
    class FakeSearchClient:
        async def search(self, *, query: str, count: int = 5, provider: str = "auto"):
            assert "enterprise AI" in query
            assert count == 2
            assert provider == "auto"
            return GatewaySearchResponse(
                provider="fake",
                query_hash="a" * 64,
                fetched_at=datetime.now(UTC),
                results=[
                    GatewaySearchResult(
                        title="AI operating model discussion",
                        url="https://www.linkedin.com/posts/example_ai-operating-model-activity-7473177453939613696-QL_R",
                        host="www.linkedin.com",
                        description="A useful thread on approval gates.",
                    ),
                    GatewaySearchResult(
                        title="Unsafe result",
                        url="https://social.example/unsafe",
                        host="social.example",
                        description="Skip me.",
                        risk_markers=["prompt_injection"],
                    ),
                ],
            )

    class FakeConn:
        def __init__(self) -> None:
            self.rows: list[tuple[object, ...]] = []
            self.events: list[tuple[object, ...]] = []

        async def fetchrow(self, _query: str, *args: object):
            self.rows.append(args)
            return {"id": UUID("11111111-1111-4111-8111-111111111111")}

        async def execute(self, _query: str, *args: object):
            self.events.append(args)
            return "INSERT 0 1"

    conn = FakeConn()
    outcome = await scout_linkedin_engagement_targets(
        conn,  # type: ignore[arg-type]
        actor_sub="tester",
        topics=["AI operating model"],
        per_topic=2,
        max_targets=3,
        search_client=FakeSearchClient(),  # type: ignore[arg-type]
    )

    assert outcome.created_count == 1
    assert outcome.skipped_count == 1
    assert outcome.reason == "created"
    assert conn.rows[0][0].startswith("herald:scout:")
    assert conn.rows[0][1] == "urn:li:activity:7473177453939613696"
    assert (
        conn.rows[0][2]
        == "https://www.linkedin.com/posts/example_ai-operating-model-activity-7473177453939613696-QL_R"
    )
    assert conn.events[0][0:5] == (
        "linkedin",
        "engagement",
        "inbound",
        "engagement_scouted",
        "needs_reply",
    )


def test_linkedin_weekly_auto_draft_is_draft_only_and_deduped() -> None:
    source = SERVICE.read_text(encoding="utf-8")

    assert "create_weekly_linkedin_draft_if_due" in source
    assert "active_weekly_draft_exists" in source
    assert "linkedin-weekly-brand" in source
    assert "human_review_required" in source
    assert "publish_linkedin_text" not in source
    assert "publish_linkedin_comment" not in source


def test_linkedin_engagement_scheduler_is_draft_only_and_capped() -> None:
    source = SERVICE.read_text(encoding="utf-8")

    assert "draft_linkedin_engagement_replies_if_due" in source
    assert "weekly_limit: int = 3" in source
    assert "engagement_scheduler" in source
    assert "publish_linkedin_text" not in source
    assert "publish_linkedin_comment" not in source


def test_linkedin_phase2_learning_loop_is_approval_gated() -> None:
    route_source = ROUTE.read_text(encoding="utf-8")
    service_source = SERVICE.read_text(encoding="utf-8")

    assert "propose_personality_memory_from_note" in route_source
    assert "linkedin_feedback_memory_note" in route_source
    assert "review_friction" in route_source
    assert "spark_memory_proposed" in route_source
    assert "spark_memory_proposal_candidate" in route_source
    assert "save_personality_memory(" not in route_source
    assert "LINKEDIN_LEARNING_MIN_SAMPLES = 3" in service_source
    assert "HAVING count(*) >= $1" in service_source
    assert (
        "sum(m.reactions + m.comments + m.reposts + m.profile_clicks) > 0"
        in service_source
    )
    assert "metrics_due_count" in service_source
    assert "review_friction_30d" in service_source
    assert "load_linkedin_analytics_digest" in service_source
    assert "recommendations" in service_source


def test_linkedin_target_scout_uses_gateway_search_without_publish() -> None:
    source = SERVICE.read_text(encoding="utf-8")

    assert "scout_linkedin_engagement_targets" in source
    assert "InternetScoutGatewayClient" in source
    assert "herald:scout:" in source
    assert "alpha_herald_social_engagement_items" in source
    assert "publish_linkedin_text" not in source
    assert "publish_linkedin_comment" not in source


def test_linkedin_cadence_counts_live_and_manual_publish_receipts() -> None:
    source = ROUTE.read_text(encoding="utf-8")
    service_source = SERVICE.read_text(encoding="utf-8")

    assert "'manual_published', 'linkedin_published'" in source
    assert "r.draft_kind = 'post'" in source
    assert "r.campaign = 'linkedin-weekly-brand'" in source
    assert "r.draft_kind = 'post'" in service_source
    assert "r.campaign = 'linkedin-weekly-brand'" in service_source


def test_manual_publish_receipt_clears_stale_publish_error() -> None:
    source = ROUTE.read_text(encoding="utf-8")

    assert "SET publish_status = 'manual_published'" in source
    assert "publish_error_type = NULL" in source
    assert "publish_error_message = NULL" in source


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


def test_herald_interaction_ledger_migration_is_append_only_metadata() -> None:
    source = INTERACTION_LEDGER_MIGRATION.read_text(encoding="utf-8")

    assert "public.alpha_herald_interaction_ledger" in source
    assert "alpha_herald_interaction_ledger_immutable" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "channel IN ('email', 'social', 'linkedin', 'x')" in source
    assert "interaction_kind IN" in source
    assert "No mail body" in source
    assert "draft text" in source
    assert "access_token" not in source
    assert "client_secret" not in source


def test_herald_social_analytics_and_target_graph_migration_is_metadata_only() -> None:
    source = ANALYTICS_TARGETS_MIGRATION.read_text(encoding="utf-8")

    assert "public.alpha_herald_social_metric_snapshots" in source
    assert "public.alpha_herald_thought_leader_targets" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "metric_source IN ('manual', 'linkedin_api')" in source
    assert "relationship_notes" in source
    assert "access_token" not in source
    assert "client_secret" not in source
    assert "private DMs" in source


def test_social_routes_publish_only_through_linkedin_connector() -> None:
    source = ROUTE.read_text(encoding="utf-8")

    assert "/v1/herald/social" in source
    assert "/linkedin/weekly" in source
    assert "/linkedin/cadence" in source
    assert "/linkedin/read-plan" in source
    assert "/linkedin/operator-dashboard" in source
    assert "/linkedin/analytics-digest" in source
    assert "/linkedin/engagements" in source
    assert "/linkedin/engagements/scout" in source
    assert "/linkedin/ingest" in source
    assert "/linkedin/metrics" in source
    assert "/linkedin/thought-leaders" in source
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
    assert 'reply_styles=["strong_short", "practical", "warm"]' in source
    assert "SET reply_variant_id = $1" in source
    assert "feedback_provided" in source
    assert "planned_pending_linkedin_approval" in source
    assert "r_member_social_feed" in source
    assert "send_at0_mail_reply" not in source
    assert "requests.post" not in source
    assert "aiohttp" not in source
    assert "browser" not in source.lower()
    assert "postiz" not in source.lower()
    assert "buffer" not in source.lower()
