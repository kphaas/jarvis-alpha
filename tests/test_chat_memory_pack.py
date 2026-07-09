from brain.services.chat_memory_pack import (
    CHAT_MEMORY_PACK_SCHEMA_VERSION,
    pack_chat_memory_context,
)


def test_memory_pack_prefers_current_rows_when_budgeted() -> None:
    source = "\n".join(
        [
            "[TEMPORAL GRAPH]",
            "- [historical] Project: old Alpha plan " + ("x" * 120),
            "- [current] Project: current Alpha plan",
            "- [needs refresh] Project: maybe stale plan " + ("y" * 120),
        ]
    )

    pack = pack_chat_memory_context(source, budget_chars=80)

    assert "[current] Project: current Alpha plan" in pack.context
    assert "[historical]" not in pack.context
    assert "[needs refresh]" not in pack.context
    assert pack.manifest.truncated is True
    assert pack.manifest.current_line_count == 1
    assert pack.manifest.dropped_line_count == 2


def test_memory_pack_keeps_existing_context_when_under_budget() -> None:
    source = "[ALWAYS KNOWN]\n- Ken prefers concise answers."

    pack = pack_chat_memory_context(source, budget_chars=1000)

    assert pack.context == source
    assert pack.manifest.truncated is False
    assert pack.manifest.section_order == ("[ALWAYS KNOWN]",)


def test_memory_pack_metadata_excludes_raw_memory_text() -> None:
    source = "[ALWAYS KNOWN]\n- private user memory fact"

    pack = pack_chat_memory_context(source)
    metadata = pack.manifest.to_metadata()

    assert (
        metadata["chat_memory_pack_schema_version"] == CHAT_MEMORY_PACK_SCHEMA_VERSION
    )
    assert metadata["chat_memory_pack_source_chars"] == len(source)
    assert source not in metadata.values()
    assert "private user memory fact" not in metadata.values()
