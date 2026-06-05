from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SPARK_PAGE = REPO_ROOT / "ui" / "src" / "pages" / "Spark.tsx"
SPARK_HOOK = REPO_ROOT / "ui" / "src" / "hooks" / "useSparkDraftReview.ts"
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
        for path in (SPARK_PAGE, SPARK_HOOK, SPARK_TYPES)
    )

    assert "apiJson" in source
    assert "/v1/spark/drafts/imessage" in source
    assert "/v1/spark/drafts/imessage/approval-request" in source
    assert "draft_text_override" in source
    assert "fetch(" not in source
    assert "XMLHttpRequest" not in source


def test_spark_review_ui_keeps_send_out_of_phase() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (SPARK_PAGE, SPARK_HOOK, SPARK_TYPES)
    )

    assert "can_send" in source
    assert "requires_human_approval" in source
    assert "Submit approval" in source
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
