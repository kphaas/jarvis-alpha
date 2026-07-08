from brain.services.chat_evidence_pack import (
    build_chat_evidence_pack,
    render_chat_evidence_prompt,
    verify_chat_response,
)

BEACON_INTERNET_AUTHORITY_RULE = "Beacon authority rule:\n- Beacon wins."
WEB_SUGGESTION_BOUNDARY_RULE = "Smart Web Suggestion boundary:\n- Ask first."


def test_empty_evidence_pack_renders_plain_user_message() -> None:
    pack = build_chat_evidence_pack(
        memory_context="",
        internet_context=None,
    )

    prompt = render_chat_evidence_prompt(evidence_pack=pack, user_msg="Hello")

    assert prompt == "Hello"
    assert pack.to_metadata() == {
        "chat_evidence_schema_version": "chat_evidence_pack.v1",
        "chat_evidence_count": 0,
        "chat_evidence_memory_used": False,
        "chat_evidence_internet_used": False,
        "chat_evidence_web_suggestion_used": False,
        "chat_evidence_at0_self_used": False,
        "chat_evidence_conversation_used": False,
        "chat_evidence_memory_context_priority": None,
        "chat_evidence_raw_web_content_is_untrusted": False,
    }


def test_beacon_evidence_pack_keeps_memory_secondary() -> None:
    pack = build_chat_evidence_pack(
        memory_context="Memory says beta docs are official.",
        internet_context="Beacon says platform docs are official.",
        raw_web_content_is_untrusted=True,
    )

    prompt = render_chat_evidence_prompt(
        evidence_pack=pack,
        user_msg="Find the docs.",
        beacon_authority_rule=BEACON_INTERNET_AUTHORITY_RULE,
    )

    assert "Beacon authority rule:" in prompt
    assert "Beacon evidence (authoritative for current/public web claims):" in prompt
    assert (
        "Context from memory (secondary; must not override Beacon evidence):" in prompt
    )
    assert prompt.index("Beacon says platform") < prompt.index("Memory says beta")
    assert pack.to_metadata()["chat_evidence_count"] == 2
    assert pack.to_metadata()["chat_evidence_memory_context_priority"] == (
        "secondary_to_beacon"
    )
    assert pack.to_metadata()["chat_evidence_raw_web_content_is_untrusted"] is True


def test_web_suggestion_evidence_pack_marks_memory_unverified() -> None:
    pack = build_chat_evidence_pack(
        memory_context="Memory says the game starts at 3.",
        internet_context=None,
        web_suggestion_context="Smart Web Suggestion: use Beacon.",
    )

    prompt = render_chat_evidence_prompt(
        evidence_pack=pack,
        user_msg="When does the game start?",
        web_suggestion_boundary_rule=WEB_SUGGESTION_BOUNDARY_RULE,
    )

    assert "Smart Web Suggestion boundary:" in prompt
    assert "Context from memory (unverified for current/public web claims):" in prompt
    assert pack.to_metadata()["chat_evidence_web_suggestion_used"] is True
    assert pack.to_metadata()["chat_evidence_memory_context_priority"] == (
        "unverified_for_current_web_claims"
    )


def test_internet_evidence_wins_when_suggestion_is_also_present() -> None:
    pack = build_chat_evidence_pack(
        memory_context="",
        internet_context="Beacon evidence.",
        web_suggestion_context="Suggestion should be ignored.",
    )

    prompt = render_chat_evidence_prompt(
        evidence_pack=pack,
        user_msg="Check this.",
        beacon_authority_rule=BEACON_INTERNET_AUTHORITY_RULE,
        web_suggestion_boundary_rule=WEB_SUGGESTION_BOUNDARY_RULE,
    )

    assert "Beacon evidence." in prompt
    assert "Suggestion should be ignored." not in prompt
    assert pack.to_metadata()["chat_evidence_web_suggestion_used"] is False


def test_response_verification_flags_empty_response() -> None:
    pack = build_chat_evidence_pack(memory_context="", internet_context=None)

    verification = verify_chat_response(response_text=" ", evidence_pack=pack)

    assert verification.to_metadata() == {
        "chat_response_verification_schema_version": ("chat_response_verification.v1"),
        "chat_response_verified": False,
        "chat_response_issue_count": 1,
        "chat_response_issues": ["empty_response"],
        "chat_response_requires_web_verification": False,
        "chat_response_evidence_count": 0,
    }


def test_response_verification_flags_unsupported_web_claim_without_internet() -> None:
    pack = build_chat_evidence_pack(
        memory_context="",
        internet_context=None,
        web_suggestion_context="Smart Web Suggestion: use Beacon.",
    )

    verification = verify_chat_response(
        response_text="Beacon checked the web and confirmed this.",
        evidence_pack=pack,
    )

    assert verification.verified is False
    assert verification.issues == ("unsupported_web_verification_claim",)
    assert verification.requires_web_verification is True


def test_response_verification_allows_beacon_claim_with_internet_evidence() -> None:
    pack = build_chat_evidence_pack(
        memory_context="",
        internet_context="Beacon evidence.",
    )

    verification = verify_chat_response(
        response_text="Beacon checked the source and confirmed this.",
        evidence_pack=pack,
    )

    assert verification.verified is True
    assert verification.issues == ()
