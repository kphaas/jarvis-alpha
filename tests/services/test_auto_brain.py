from __future__ import annotations

import pytest

from brain.services.auto_brain import (
    AutoBrainConfigError,
    load_auto_spark_context,
)


def test_auto_spark_context_returns_metadata_only(tmp_path) -> None:
    _write_auto_vault(tmp_path)

    context = load_auto_spark_context(tmp_path)
    payload = context.model_dump()
    serialized = str(payload).lower()

    assert context.source_count == 4
    assert context.rule_count == 5
    assert context.runtime_mode.spark_can_read is True
    assert context.runtime_mode.spark_can_write is False
    assert context.runtime_mode.durable_memory_writes is False
    assert context.runtime_mode.outbound_send_allowed is False
    assert context.body_access is False
    assert context.raw_content_returned is False
    assert {source.path for source in context.sources} == {
        "auto/mission.md",
        "auto/context/current_state.md",
        "auto/context/open_loops.md",
        "04_delegation/delegation_policy.yml",
    }
    assert "private body" not in serialized
    assert "secret" not in serialized


def test_auto_spark_context_rejects_write_enabled(tmp_path) -> None:
    _write_auto_vault(tmp_path, spark_can_write=True)

    with pytest.raises(AutoBrainConfigError, match="write_enabled"):
        load_auto_spark_context(tmp_path)


def test_auto_spark_context_rejects_path_escape(tmp_path) -> None:
    _write_auto_vault(tmp_path, extra_source="../secrets.txt")

    with pytest.raises(AutoBrainConfigError, match="path_not_allowed"):
        load_auto_spark_context(tmp_path)


def _write_auto_vault(
    root,
    *,
    spark_can_write: bool = False,
    extra_source: str | None = None,
) -> None:
    (root / "auto" / "interfaces").mkdir(parents=True)
    (root / "auto" / "context").mkdir(parents=True)
    (root / "04_delegation").mkdir(parents=True)

    sources = [
        "auto/mission.md",
        "auto/context/current_state.md",
        "auto/context/open_loops.md",
        "04_delegation/delegation_policy.yml",
    ]
    if extra_source:
        sources.append(extra_source)

    source_lines = "\n".join(f"  - {source}" for source in sources)
    (root / "auto" / "interfaces" / "spark_context.yml").write_text(
        f"""
version: 0.1.0
allowed_for:
  - spark-draft
read_sources:
{source_lines}
rules:
  - "Use context only."
  - "Do not copy notes."
  - "Do not expose internals."
  - "Escalate sensitive context."
  - "Principal voice wins."
runtime_mode:
  spark_can_read: true
  spark_can_write: {str(spark_can_write).lower()}
  durable_memory_writes: false
  outbound_send_allowed: false
""",
        encoding="utf-8",
    )
    (root / "auto" / "mission.md").write_text(
        "# Auto Mission\n\nPrivate body text stays inside the vault.",
        encoding="utf-8",
    )
    (root / "auto" / "context" / "current_state.md").write_text(
        "# Current State\n\nSecret operational details stay inside the vault.",
        encoding="utf-8",
    )
    (root / "auto" / "context" / "open_loops.md").write_text(
        "# Open Loops\n\nNo raw Auto note body should be returned.",
        encoding="utf-8",
    )
    (root / "04_delegation" / "delegation_policy.yml").write_text(
        "# Delegation Policy\n\nversion: 0.1.0\n",
        encoding="utf-8",
    )
