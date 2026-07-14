from __future__ import annotations

import json

from brain.services.chat_evidence_pack import (
    ChatResponseVerification,
    build_chat_evidence_pack,
    evaluate_chat_quality_gate,
    verify_chat_response,
)
from brain.services.chat_output_contract import (
    ChatOutputContract,
    apply_chat_output_contract_verification,
    compile_explicit_chat_output_contract,
    evaluate_chat_output_contract,
    normalize_chat_output_contract_response,
    render_chat_output_contract_repair_prompt,
)


def test_compiler_extracts_explicit_exact_json_contract() -> None:
    contract = compile_explicit_chat_output_contract(
        "Return only a JSON object with keys owner, priority, and ticket_count. "
        "Use the supplied ticket data."
    )

    assert contract is not None
    assert contract.contract_id == "exact_json"
    assert contract.exact_json_keys == ("owner", "priority", "ticket_count")
    assert (
        evaluate_chat_output_contract(
            '{"owner":"Delta","priority":"high","ticket_count":3}',
            contract,
        ).passed
        is True
    )
    assert evaluate_chat_output_contract(
        '```json\n{"owner":"Delta"}\n```',
        contract,
    ).issues == ("json_object_required",)

    normalized, changed = normalize_chat_output_contract_response(
        '```json\n{"owner":"Delta","priority":"high","ticket_count":3}\n```',
        contract,
    )
    assert changed is True
    assert normalized == '{"owner":"Delta","priority":"high","ticket_count":3}'
    assert normalize_chat_output_contract_response(
        "Result:\n```json\n{}\n```",
        contract,
    ) == ("Result:\n```json\n{}\n```", False)


def test_compiler_builds_privacy_and_sentence_constraints() -> None:
    contract = compile_explicit_chat_output_contract(
        "Compare external privacy with local privacy and explain the cost and "
        "privacy tradeoff in at most three sentences."
    )

    assert contract is not None
    assert contract.required_terms == ("privacy", "cost", "external", "local")
    assert contract.max_sentences == 3
    evaluation = evaluate_chat_output_contract(
        "Local execution improves privacy. It costs more.",
        contract,
    )
    assert evaluation.issues == ("required_content_missing",)


def test_sentence_normalization_preserves_required_grounding_terms() -> None:
    contract = ChatOutputContract(
        contract_id="grounded",
        required_terms=("paused", "rollback test", "[e1]", "[e2]"),
        forbidden_terms=("[e3]",),
        max_sentences=1,
    )

    normalized, changed = normalize_chat_output_contract_response(
        "Atlas is paused [E1]. It resumes after the rollback test [E2].",
        contract,
    )

    assert changed is True
    assert normalized == (
        "Atlas is paused [E1]; It resumes after the rollback test [E2]."
    )
    assert evaluate_chat_output_contract(normalized, contract).passed is True


def test_safe_recovery_contract_enforces_order_and_destructive_exclusions() -> None:
    contract = compile_explicit_chat_output_contract(
        "Create a recovery plan for a failed routing rollout. Preserve audit "
        "evidence, require operator approval, and do not delete data. Order the "
        "plan from containment through monitoring."
    )

    assert contract is not None
    assert contract.ordered_terms == ("contain", "verify", "rollback", "monitor")
    evaluation = evaluate_chat_output_contract(
        "Contain traffic, verify evidence, rollback safely, obtain operator approval, "
        "preserve the audit record, then monitor recovery.",
        contract,
    )
    assert evaluation.passed is True
    assert evaluate_chat_output_contract(
        "Contain, delete all records, verify, rollback, then monitor.",
        contract,
    ).issues == ("required_content_missing", "forbidden_content_present")


def test_contract_metadata_and_repair_prompt_do_not_retain_prior_response() -> None:
    contract = ChatOutputContract(
        contract_id="safe_plan",
        required_terms=("operator approval",),
    )
    evaluation = evaluate_chat_output_contract("reactivate now", contract)
    prompt = render_chat_output_contract_repair_prompt(
        user_msg="Require operator approval before reactivation.",
        contract=contract,
        issues=evaluation.issues,
    )
    metadata = evaluation.to_metadata()

    assert "reactivate now" not in prompt
    assert "operator approval" in prompt
    assert "operator approval" not in json.dumps(metadata)
    assert metadata["chat_output_contract_issues"] == ["required_content_missing"]


def test_contract_verification_fails_closed_through_quality_gateway() -> None:
    pack = build_chat_evidence_pack(memory_context="", internet_context=None)
    base = ChatResponseVerification(
        verified=True,
        issues=(),
        requires_web_verification=False,
        evidence_count=0,
    )
    contract = ChatOutputContract(
        contract_id="exact_json",
        exact_json_keys=("status",),
    )
    evaluation = evaluate_chat_output_contract("Status is ready.", contract)
    verification = apply_chat_output_contract_verification(base, evaluation)

    gate = evaluate_chat_quality_gate(
        evidence_pack=pack,
        verification=verification,
    )

    assert verification.issues == ("output_contract_json_object_required",)
    assert gate.passed is False
    assert gate.reason == "output_contract_failed"
    assert gate.action == "replace_with_safe_fallback"


def test_beacon_requirement_outranks_output_contract_failure() -> None:
    pack = build_chat_evidence_pack(memory_context="", internet_context=None)
    base = verify_chat_response(
        response_text="I checked the web and confirmed this.",
        evidence_pack=pack,
    )
    contract = ChatOutputContract(
        contract_id="exact_json",
        exact_json_keys=("status",),
    )
    verification = apply_chat_output_contract_verification(
        base,
        evaluate_chat_output_contract(
            "I checked the web and confirmed this.", contract
        ),
    )

    gate = evaluate_chat_quality_gate(
        evidence_pack=pack,
        verification=verification,
    )

    assert gate.reason == "unsupported_web_verification_claim"
