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
    evaluate_chat_output_contract_feasibility,
    generation_policy_for_chat_output_contract,
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
    generation_policy = generation_policy_for_chat_output_contract(contract)
    assert generation_policy.deterministic is True
    assert generation_policy.json_mode is True
    assert generation_policy.exact_json_keys == (
        "owner",
        "priority",
        "ticket_count",
    )
    assert generation_policy.response_schema() == {
        "type": "object",
        "properties": {
            key: {"type": ["string", "number", "boolean", "object", "array", "null"]}
            for key in ("owner", "priority", "ticket_count")
        },
        "required": ["owner", "priority", "ticket_count"],
        "additionalProperties": False,
    }
    assert generation_policy.metadata()["chat_generation_policy_exact_key_count"] == 3
    assert "owner" not in json.dumps(generation_policy.metadata())
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
    generation_policy = generation_policy_for_chat_output_contract(contract)
    assert generation_policy.deterministic is True
    assert generation_policy.json_mode is False
    assert generation_policy.exact_json_keys == ()
    assert generation_policy.response_schema() is None
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


def test_feasibility_preflight_detects_phase32_required_forbidden_conflict() -> None:
    contract = compile_explicit_chat_output_contract(
        "[term:7c6ac55a39ab] exercise. Provide a recovery plan for a failed "
        "routing rollout with containment, operator approval, preserve audit, and "
        "do not delete anything. Compare purge privacy tradeoff and cost in one "
        "sentence."
    )

    assert contract is not None
    feasibility = evaluate_chat_output_contract_feasibility(contract)
    assert feasibility.feasible is False
    assert feasibility.conflicts == ("required_term_forbidden",)
    assert feasibility.to_metadata() == {
        "chat_output_contract_feasibility_schema_version": (
            "chat_output_contract_feasibility.v1"
        ),
        "chat_output_contract_feasible": False,
        "chat_output_contract_conflict_count": 1,
        "chat_output_contract_conflicts": ["required_term_forbidden"],
        "chat_output_contract_preflight_action": "skip_generation",
    }


def test_feasibility_preflight_does_not_reject_narrower_required_term() -> None:
    contract = ChatOutputContract(
        contract_id="non_conflicting_substring",
        required_terms=("delete",),
        forbidden_terms=("delete all",),
    )

    assert evaluate_chat_output_contract_feasibility(contract).feasible is True


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
        failed_response_text="reactivate now",
    )
    metadata = evaluation.to_metadata()

    assert "reactivate now" not in prompt
    assert "operator approval" in prompt
    assert (
        "Targeted validation checklist (include each missing term exactly):\n"
        "- operator approval"
    ) in prompt
    assert "operator approval" not in json.dumps(metadata)
    assert metadata["chat_output_contract_issues"] == ["required_content_missing"]


def test_repair_prompt_targets_only_validator_proven_missing_terms() -> None:
    contract = ChatOutputContract(
        contract_id="analysis",
        required_terms=("97", "cost", "4", "privacy", "local", "external"),
    )
    failed_response = (
        "SENSITIVE-PRIOR-CONTENT: Option C has cost 4, local privacy instead of "
        "external privacy."
    )

    prompt = render_chat_output_contract_repair_prompt(
        user_msg="Compare the options.",
        contract=contract,
        issues=("required_content_missing",),
        failed_response_text=failed_response,
    )
    checklist = prompt.split(
        "Targeted validation checklist (include each missing term exactly):\n",
        maxsplit=1,
    )[1].split("\n\nOutput contract", maxsplit=1)[0]

    assert checklist == "- 97"
    assert failed_response not in prompt
    assert "SENSITIVE-PRIOR-CONTENT" not in prompt


def test_repair_prompt_skips_targeting_without_a_proven_omission() -> None:
    contract = ChatOutputContract(
        contract_id="analysis",
        required_terms=("privacy",),
        max_sentences=1,
    )

    wrong_issue_prompt = render_chat_output_contract_repair_prompt(
        user_msg="Use one sentence.",
        contract=contract,
        issues=("sentence_limit_exceeded",),
        failed_response_text="No required content.",
    )
    no_missing_terms_prompt = render_chat_output_contract_repair_prompt(
        user_msg="Include privacy.",
        contract=contract,
        issues=("required_content_missing",),
        failed_response_text="Privacy is local.",
    )

    assert "Targeted validation checklist" not in wrong_issue_prompt
    assert "Targeted validation checklist" not in no_missing_terms_prompt


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
