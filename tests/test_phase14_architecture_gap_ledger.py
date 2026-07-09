from __future__ import annotations

from pathlib import Path


LEDGER = Path("docs/audit/AT0_CHAT_QUALITY_ARCHITECTURE_GAP_LEDGER_2026-07-09.md")


def test_phase14_gap_ledger_tracks_next_build_queue() -> None:
    text = LEDGER.read_text(encoding="utf-8")

    for heading in (
        "AT-0 Chat Quality Architecture Review + Gap Ledger",
        "Shipped Phase Ledger",
        "Gap Ledger",
        "Next Build Queue",
        "Facts",
        "Assumptions",
        "Risks",
        "Recommendations",
    ):
        assert heading in text

    for phase in (
        "Strategy Contract",
        "Context Compiler / Evidence Pack",
        "Response Verification",
        "Quality Gateway",
        "Escalation Ladder",
        "Council Detail v2",
        "Outcome Metadata",
        "Outcome Inspector",
        "Evaluation Harness",
        "Deploy Regression Gate",
    ):
        assert phase in text

    next_queue = text.split("## Next Build Queue", maxsplit=1)[1]
    assert "Phase 15: Prompt Compiler v2" in next_queue
    assert "Phase 16: Memory/RAG Packing" in next_queue
    assert "Phase 17: Model Capability Registry" in next_queue
    assert "Phase 18: Trace Replay Evals" in next_queue
