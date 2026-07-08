from brain.services.chat_evidence_pack import (
    build_chat_evidence_pack,
    evaluate_chat_quality_gate,
    plan_chat_escalation,
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


def test_quality_gate_accepts_verified_response() -> None:
    pack = build_chat_evidence_pack(memory_context="", internet_context=None)
    verification = verify_chat_response(
        response_text="Plain answer.", evidence_pack=pack
    )

    gate = evaluate_chat_quality_gate(
        evidence_pack=pack,
        verification=verification,
        strategy_metadata={
            "chat_strategy": "fast_local",
            "chat_model_path": "local",
        },
    )

    assert gate.to_metadata() == {
        "chat_quality_gateway_schema_version": "chat_quality_gateway.v1",
        "chat_quality_action": "accept",
        "chat_quality_passed": True,
        "chat_quality_reason": "verified_response",
        "chat_quality_fallback_used": False,
        "chat_quality_response_verified": True,
        "chat_quality_response_issues": [],
        "chat_quality_evidence_count": 0,
        "chat_quality_strategy": "fast_local",
        "chat_quality_model_path": "local",
    }


def test_quality_gate_requires_beacon_for_web_suggestion_without_internet() -> None:
    pack = build_chat_evidence_pack(
        memory_context="",
        internet_context=None,
        web_suggestion_context="Smart Web Suggestion: use Beacon.",
    )
    verification = verify_chat_response(
        response_text="I can answer generally.",
        evidence_pack=pack,
    )

    gate = evaluate_chat_quality_gate(evidence_pack=pack, verification=verification)

    assert gate.action == "require_beacon"
    assert gate.passed is False
    assert gate.reason == "web_verification_required"
    assert gate.fallback_response == (
        "I need Beacon verification before I can answer that as current or verified."
    )


def test_quality_gate_replaces_unsupported_web_claim() -> None:
    pack = build_chat_evidence_pack(memory_context="", internet_context=None)
    verification = verify_chat_response(
        response_text="I searched online and verified this.",
        evidence_pack=pack,
    )

    gate = evaluate_chat_quality_gate(evidence_pack=pack, verification=verification)

    assert gate.action == "replace_with_safe_fallback"
    assert gate.passed is False
    assert gate.reason == "unsupported_web_verification_claim"
    assert gate.fallback_response == (
        "I need Beacon verification before I can claim this was checked online."
    )


def test_escalation_ladder_does_nothing_when_quality_passes() -> None:
    pack = build_chat_evidence_pack(memory_context="", internet_context=None)
    verification = verify_chat_response(
        response_text="Plain answer.", evidence_pack=pack
    )
    gate = evaluate_chat_quality_gate(evidence_pack=pack, verification=verification)

    escalation = plan_chat_escalation(quality_gate=gate)

    assert escalation.to_metadata() == {
        "chat_escalation_schema_version": "chat_escalation_ladder.v1",
        "chat_escalation_required": False,
        "chat_escalation_rung": "none",
        "chat_escalation_action": "none",
        "chat_escalation_reason": "quality_gate_passed",
        "chat_escalation_automatic": False,
        "chat_escalation_requires_user_confirmation": False,
        "chat_escalation_source_quality_action": "accept",
    }


def test_escalation_ladder_routes_web_requirement_to_beacon() -> None:
    pack = build_chat_evidence_pack(
        memory_context="",
        internet_context=None,
        web_suggestion_context="Smart Web Suggestion: use Beacon.",
    )
    verification = verify_chat_response(
        response_text="I can answer generally.",
        evidence_pack=pack,
    )
    gate = evaluate_chat_quality_gate(evidence_pack=pack, verification=verification)

    escalation = plan_chat_escalation(quality_gate=gate)

    assert escalation.required is True
    assert escalation.rung == "beacon"
    assert escalation.action == "run_beacon"
    assert escalation.reason == "web_verification_required"
    assert escalation.automatic is False
    assert escalation.requires_user_confirmation is True


def test_escalation_ladder_routes_empty_response_to_local_retry() -> None:
    pack = build_chat_evidence_pack(memory_context="", internet_context=None)
    verification = verify_chat_response(response_text="", evidence_pack=pack)
    gate = evaluate_chat_quality_gate(evidence_pack=pack, verification=verification)

    escalation = plan_chat_escalation(quality_gate=gate)

    assert escalation.required is True
    assert escalation.rung == "retry_local"
    assert escalation.action == "retry_local_once"
    assert escalation.requires_user_confirmation is False
