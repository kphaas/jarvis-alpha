from __future__ import annotations

from pathlib import Path

from brain.services.herald_social import (
    create_social_draft,
    hash_social_draft,
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


def test_social_routes_do_not_publish_to_platforms() -> None:
    source = ROUTE.read_text(encoding="utf-8")

    assert "/v1/herald/social" in source
    assert "create_social_draft" in source
    assert "alpha_herald_social_draft_events" in source
    assert "send_at0_mail_reply" not in source
    assert "postiz" not in source.lower()
    assert "buffer" not in source.lower()
