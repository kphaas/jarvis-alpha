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
        "Prompt Compiler v2",
        "Memory/RAG Packing",
        "Model Capability Registry",
        "Trace Replay Evals",
        "Repair Loop",
        "MCP Tool Boundary",
        "Trend Observability",
        "Redacted Real Trace Corpus",
        "Outcome-Calibrated Model Scores",
        "Helm Trend Panel",
        "Real Trace Sampling Workflow",
        "Calibrated Routing Rollout Gate",
        "Per-Model Task Benchmarks",
        "Benchmark Evidence Ingestion + Operator Comparison",
        "Local Output Contract Hardening",
        "Deterministic Local Decoding",
    ):
        assert phase in text

    next_queue = text.split("## Next Build Queue", maxsplit=1)[1]
    assert "Phase 19: Repair Loop" not in next_queue
    assert "Phase 20: MCP Tool Boundary" not in next_queue
    assert "Phase 21: Trend Observability" not in next_queue
    assert "Phase 22: Redacted Real Trace Corpus" not in next_queue
    assert "Phase 23: Outcome-Calibrated Model Scores" not in next_queue
    assert "Phase 24: Helm Trend Panel" not in next_queue
    assert "Phase 25: Real Trace Sampling Workflow" not in next_queue
    assert "Phase 26: Calibrated Routing Rollout Gate" not in next_queue
    assert "Phase 27: Per-Model Task Benchmarks" not in next_queue
    assert (
        "Phase 28: Benchmark Evidence Ingestion + Operator Comparison" not in next_queue
    )
    assert "Deploy Phase 29" not in next_queue
    assert "deploy Phase 30" in next_queue
    assert "three-sample local stability gate" in next_queue
