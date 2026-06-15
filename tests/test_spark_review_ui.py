from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SPARK_PAGE = REPO_ROOT / "ui" / "src" / "pages" / "Spark.tsx"
SPARK_HOOK = REPO_ROOT / "ui" / "src" / "hooks" / "useSparkDraftReview.ts"
SPARK_GUARDRAIL_HOOK = REPO_ROOT / "ui" / "src" / "hooks" / "useSparkGuardrails.ts"
SPARK_GUARDRAIL_PANEL = (
    REPO_ROOT / "ui" / "src" / "components" / "spark" / "SparkGuardrailsPanel.tsx"
)
SPARK_MEMORY_HOOK = REPO_ROOT / "ui" / "src" / "hooks" / "useSparkPersonalityMemory.ts"
SPARK_MEMORY_PANEL = (
    REPO_ROOT / "ui" / "src" / "components" / "spark" / "SparkMemoryReviewPanel.tsx"
)
SPARK_TYPES = REPO_ROOT / "ui" / "src" / "types" / "spark.ts"
APP_PAGE = REPO_ROOT / "ui" / "src" / "App.tsx"
LAYOUT = REPO_ROOT / "ui" / "src" / "components" / "Layout.tsx"
APPROVALS_PAGE = REPO_ROOT / "ui" / "src" / "pages" / "Approvals.tsx"


def test_spark_review_ui_is_mounted_in_alpha_app() -> None:
    app_source = APP_PAGE.read_text(encoding="utf-8")
    layout_source = LAYOUT.read_text(encoding="utf-8")

    assert "const Spark = lazy(() => import('./pages/Spark'))" in app_source
    assert 'path="/spark"' in app_source
    assert "label: 'Spark'" in layout_source
    assert "Sparkles" in layout_source


def test_spark_review_ui_uses_draft_routes_and_api_wrapper() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            SPARK_PAGE,
            SPARK_HOOK,
            SPARK_GUARDRAIL_HOOK,
            SPARK_GUARDRAIL_PANEL,
            SPARK_MEMORY_HOOK,
            SPARK_MEMORY_PANEL,
            SPARK_TYPES,
        )
    )

    assert "apiJson" in source
    assert "/v1/spark/drafts/imessage/targets" in source
    assert "/v1/spark/drafts/imessage" in source
    assert "/v1/spark/drafts/imessage/approval-request" in source
    assert "/v1/spark/drafts/imessage/outbox/" in source
    assert "/v1/spark/persona/guardrails" in source
    assert "/v1/spark/persona/memory" in source
    assert "/v1/spark/persona/memory/propose" in source
    assert "/v1/spark/persona/memory/approve" in source
    assert "/v1/spark/persona/memory/archive" in source
    assert "/v1/spark/persona/memory/reject" in source
    assert "/v1/spark/drafts/imessage/feedback" in source
    assert "draft_text_override" in source
    assert "fetch(" not in source
    assert "XMLHttpRequest" not in source


def test_spark_review_ui_keeps_send_out_of_phase() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            SPARK_PAGE,
            SPARK_HOOK,
            SPARK_GUARDRAIL_HOOK,
            SPARK_GUARDRAIL_PANEL,
            SPARK_MEMORY_HOOK,
            SPARK_MEMORY_PANEL,
            SPARK_TYPES,
        )
    )

    assert "can_send" in source
    assert "requires_human_approval" in source
    assert "Submit approval" in source
    assert "Send approved" in source
    assert "auto_send_enabled: false" in source
    forbidden = (
        "/message/text",
        "imessage.send",
        "send_message",
        "Send message",
    )
    for token in forbidden:
        assert token not in source


def test_spark_approval_handoff_ui_links_to_spark_review() -> None:
    approvals_source = APPROVALS_PAGE.read_text(encoding="utf-8")
    spark_source = SPARK_PAGE.read_text(encoding="utf-8")

    assert "spark_draft_handoff" in approvals_source
    assert "/spark?approval=" in approvals_source
    assert "Review Spark" in approvals_source
    assert "useSearchParams" in spark_source
    assert "Approval queue" in spark_source


def test_spark_guardrail_ui_is_editable_without_message_content() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            SPARK_PAGE,
            SPARK_GUARDRAIL_HOOK,
            SPARK_GUARDRAIL_PANEL,
            SPARK_MEMORY_HOOK,
            SPARK_MEMORY_PANEL,
            SPARK_TYPES,
        )
    )

    assert "SparkGuardrailsPanel" in source
    assert "saveGuardrails" in source
    assert "protected_relationships" in source
    assert "protected_topics" in source
    assert "return 'child'" in source
    assert "target_voice" in source
    assert "avoid_voice" in source
    assert "signature_phrases" in source
    assert "message_body" not in source
    assert "private inbound body" not in source


def test_spark_memory_review_ui_exposes_approval_backlog_without_raw_threads() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            SPARK_PAGE,
            SPARK_MEMORY_HOOK,
            SPARK_MEMORY_PANEL,
            SPARK_TYPES,
        )
    )

    assert "SparkMemoryReviewPanel" in source
    assert "Ask Buddy" in source
    assert "Propose memory" in source
    assert "candidate_key_phrases" in source
    assert "calibration_lessons" in source
    assert "Edit lessons" in source
    assert "key phrases" in source
    assert "Approve" in source
    assert "Archive" in source
    assert "Reject" in source
    assert "proposals" in source
    assert "approved_by" in source
    assert "raw thread" not in source.lower()
    assert "message_body" not in source


def test_spark_workbench_exposes_thread_memory_debug_and_feedback() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            SPARK_PAGE,
            SPARK_HOOK,
            SPARK_MEMORY_HOOK,
            SPARK_MEMORY_PANEL,
            SPARK_TYPES,
        )
    )

    assert "SPARK_PRINCIPALS" in source
    assert "sweta" in source
    assert "ryleigh" in source
    assert "sloane" in source
    assert "meagan" in source
    assert "mother" in source
    assert "Review console" in source
    assert "Voice profile" in source
    assert "Draft target" in source
    assert "Generate for" in source
    assert "needs approved thread" in source
    assert "Thread preview" in source
    assert "Decision rail" in source
    assert "Review details" in source
    assert "Memory and guardrails" in source
    assert "Guardrails" in source
    assert "Side-by-side" in source
    assert "Compare" in source
    assert "Thread context" in source
    assert "Draft memory" in source
    assert "Drafting to" in source
    assert "Last thread message" in source
    assert "Recent thread" in source
    assert "Ken-like score" in source
    assert "Channel parity" in source
    assert "Draft memory debug" in source
    assert "Memory scorecard" in source
    assert "include_context_preview" in source
    assert "include_memory_preview" in source
    assert "context_preview" in source
    assert "personality_memory_preview" in source
    assert "conversation_summary" in source
    assert "draft_quality" in source
    assert "source_readiness" in source
    assert "scorecard" in source
    assert "runtime only" in source
    assert "newest first" in source
    assert "Edit learning" in source
    assert "Sounds like me" in source
    assert "Too robotic" in source
    assert "Too formal" in source
    assert "Too much policy" in source
    assert "spark.draft.send" not in source
    assert "/message/text" not in source
