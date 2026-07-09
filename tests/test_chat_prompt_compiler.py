from brain.services.chat_prompt_compiler import (
    PROMPT_MANIFEST_SCHEMA_VERSION,
    compile_chat_prompt,
)


def test_prompt_compiler_keeps_beacon_authoritative_over_memory() -> None:
    compiled = compile_chat_prompt(
        user_msg="Find the official OpenAI API reference URL.",
        memory_context="Stale memory says https://beta.openai.com is current.",
        internet_context="Official source: https://platform.openai.com/docs",
        beacon_authority_rule="Beacon authority rule:",
    )

    assert compiled.prompt.index("https://platform.openai.com/docs") < (
        compiled.prompt.index("https://beta.openai.com")
    )
    assert compiled.manifest.section_order == (
        "beacon_authority_rule",
        "beacon_evidence",
        "memory_secondary_to_beacon",
        "user_message",
    )
    assert compiled.manifest.tool_policy == "beacon_evidence_is_authority"
    assert compiled.manifest.memory_context_priority == "secondary_to_beacon"


def test_prompt_compiler_marks_web_suggestion_as_unverified_boundary() -> None:
    compiled = compile_chat_prompt(
        user_msg="Find the latest OpenAI API docs.",
        memory_context="",
        internet_context=None,
        web_suggestion_context="Beacon has not run yet.",
        web_suggestion_boundary_rule="Smart Web Suggestion boundary:",
    )

    assert compiled.prompt.index("Smart Web Suggestion boundary:") < (
        compiled.prompt.index("Beacon has not run yet.")
    )
    assert compiled.manifest.section_order == (
        "web_suggestion_boundary",
        "web_suggestion",
        "user_message",
    )
    assert compiled.manifest.tool_policy == "web_suggestion_requires_confirmation"
    assert compiled.manifest.internet_used is False


def test_prompt_manifest_metadata_excludes_raw_prompt_text() -> None:
    user_msg = "Do not leak this exact user message."
    compiled = compile_chat_prompt(
        user_msg=user_msg,
        memory_context="private local context",
        internet_context=None,
    )

    metadata = compiled.manifest.to_metadata()

    assert metadata["chat_prompt_schema_version"] == PROMPT_MANIFEST_SCHEMA_VERSION
    assert metadata["chat_prompt_user_message_chars"] == len(user_msg)
    assert metadata["chat_prompt_compiled_chars"] == len(compiled.prompt)
    assert user_msg not in metadata.values()
    assert compiled.prompt not in metadata.values()
