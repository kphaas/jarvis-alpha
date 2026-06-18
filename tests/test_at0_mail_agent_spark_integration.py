from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT = REPO_ROOT / "brain" / "services" / "at0_mail_agent.py"


def test_herald_mail_agent_uses_at0_spark_for_reply_drafts() -> None:
    source = AGENT.read_text(encoding="utf-8")

    assert "create_at0_spark_reply_draft" in source
    assert "proposed_body=draft.proposed_body" in source
    assert "build_reply_draft" not in source
