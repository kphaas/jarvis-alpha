from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault(
    "ALPHA_DB_DSN",
    "postgresql://test:test@localhost/test",  # pragma: allowlist secret
)
os.environ.setdefault(
    "ALPHA_DB_DSN_WRITER",
    "postgresql://test:test@localhost/test",  # pragma: allowlist secret
)
os.environ.setdefault(
    "ALPHA_DB_DSN_BUDDY",
    "postgresql://test:test@localhost/test",  # pragma: allowlist secret
)
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://127.0.0.1:8188")

from brain.routes import chat
from brain.services.chat_evidence_pack import (
    CHAT_OUTPUT_CONTRACT_INFEASIBLE_RESPONSE,
    build_chat_evidence_pack,
    verify_chat_response,
)
from brain.services.chat_repair_loop import (
    ChatRepairAttemptResult,
    repair_chat_response_once,
    run_chat_repair_loop,
)
from brain.services.chat_output_contract import (
    ChatOutputContract,
    evaluate_chat_output_contract,
)


PHASE32_CONFLICT_PROMPT = (
    "[term:7c6ac55a39ab] exercise. Provide a recovery plan for a failed routing "
    "rollout with containment, operator approval, preserve audit, and do not delete "
    "anything. Compare purge privacy tradeoff and cost in one sentence."
)


def test_repair_loop_strips_unsupported_web_narration() -> None:
    evidence_pack = build_chat_evidence_pack(
        memory_context="[current] Alpha plan: build the repair loop next.",
        internet_context=None,
    )
    verification = verify_chat_response(
        response_text=(
            "I checked the web and confirmed this. "
            "The current Alpha plan is to build the repair loop next."
        ),
        evidence_pack=evidence_pack,
    )

    repair = repair_chat_response_once(
        response_text=(
            "I checked the web and confirmed this. "
            "The current Alpha plan is to build the repair loop next."
        ),
        evidence_pack=evidence_pack,
        verification=verification,
    )

    assert repair.repaired is True
    assert repair.action == "strip_unsupported_web_claim"
    assert repair.text == "The current Alpha plan is to build the repair loop next."
    assert repair.verification.verified is True
    assert repair.to_metadata()["chat_repair_before_issues"] == [
        "unsupported_web_verification_claim"
    ]


def test_repair_loop_does_not_bypass_web_suggestion_confirmation() -> None:
    evidence_pack = build_chat_evidence_pack(
        memory_context="",
        internet_context=None,
        web_suggestion_context="Beacon has not run yet.",
    )
    verification = verify_chat_response(
        response_text="This needs current verification.",
        evidence_pack=evidence_pack,
    )

    repair = repair_chat_response_once(
        response_text="This needs current verification.",
        evidence_pack=evidence_pack,
        verification=verification,
    )

    assert repair.attempted is False
    assert repair.repaired is False
    assert repair.reason == "requires_beacon"
    assert repair.verification.requires_web_verification is True


@pytest.mark.asyncio
async def test_repair_loop_does_not_retry_empty_response_without_evidence() -> None:
    called = False
    evidence_pack = build_chat_evidence_pack(memory_context="", internet_context=None)

    async def retry_once(_prompt: str) -> ChatRepairAttemptResult:
        nonlocal called
        called = True
        return ChatRepairAttemptResult(text="should not run", model_used="local")

    repair = await run_chat_repair_loop(
        response_text="",
        user_msg="What is the current Alpha plan?",
        evidence_pack=evidence_pack,
        retry_once=retry_once,
    )

    assert called is False
    assert repair.attempted is False
    assert repair.reason == "no_evidence_for_repair"


@pytest.mark.asyncio
async def test_stream_single_retries_empty_response_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_route(prompt: str, mode: str) -> dict[str, object]:
        calls.append(mode)
        if len(calls) == 1:
            return {"result": "", "mode": mode, "chat_route_mode": mode}
        return {
            "result": "The current Alpha plan is to build the repair loop next.",
            "mode": "local",
            "chat_route_mode": "local",
        }

    monkeypatch.setattr(chat, "route", fake_route)
    outcome: dict[str, object] = {}
    evidence_pack = build_chat_evidence_pack(
        memory_context="[current] Alpha plan: build the repair loop next.",
        internet_context=None,
    )

    chunks = [
        chunk
        async for chunk in chat._stream_single(
            "User: What is the current Alpha plan?",
            "auto",
            "thread-1",
            "auto",
            "What is the current Alpha plan?",
            evidence_pack=evidence_pack,
            chat_outcome_holder=outcome,
        )
    ]

    streamed_text = _streamed_text(chunks)
    assert calls == ["auto", "local"]
    assert streamed_text == "The current Alpha plan is to build the repair loop next."
    assert outcome["chat_repair_action"] == "retry_local_once"
    assert outcome["chat_repair_repaired"] is True
    assert outcome["chat_outcome_quality_action"] == "accept"


@pytest.mark.asyncio
async def test_output_contract_retries_once_and_records_reason_only_metadata() -> None:
    prompts: list[str] = []
    evidence_pack = build_chat_evidence_pack(memory_context="", internet_context=None)
    contract = ChatOutputContract(
        contract_id="exact_json",
        exact_json_keys=("status",),
    )

    async def retry_once(prompt: str) -> ChatRepairAttemptResult:
        prompts.append(prompt)
        return ChatRepairAttemptResult(text='{"status":"ready"}', model_used="local")

    repair = await run_chat_repair_loop(
        response_text="The status is ready.",
        user_msg="Return only a JSON object with key status.",
        evidence_pack=evidence_pack,
        retry_once=retry_once,
        output_contract=contract,
    )

    assert len(prompts) == 1
    assert repair.text == '{"status":"ready"}'
    assert repair.repaired is True
    assert repair.reason == "output_contract_repaired"
    assert repair.verification.verified is True
    metadata = repair.to_metadata()
    assert metadata["chat_output_contract_passed"] is True
    assert "The status is ready" not in json.dumps(metadata)


@pytest.mark.asyncio
async def test_output_contract_retry_targets_missing_terms_without_retaining_them() -> (
    None
):
    prompts: list[str] = []
    evidence_pack = build_chat_evidence_pack(memory_context="", internet_context=None)
    contract = ChatOutputContract(
        contract_id="targeted_analysis",
        required_terms=("Missing-Needle-9F", "local"),
    )

    async def retry_once(prompt: str) -> ChatRepairAttemptResult:
        prompts.append(prompt)
        return ChatRepairAttemptResult(
            text="Use the local plan with Missing-Needle-9F.",
            model_used="local",
        )

    repair = await run_chat_repair_loop(
        response_text="Use the local plan. SENSITIVE-FAILED-ANSWER",
        user_msg="Recommend the local plan and include the required identifier.",
        evidence_pack=evidence_pack,
        retry_once=retry_once,
        output_contract=contract,
    )

    assert len(prompts) == 1
    checklist = (
        prompts[0]
        .split(
            "Targeted validation checklist (include each missing term exactly):\n",
            maxsplit=1,
        )[1]
        .split("\n\nOutput contract", maxsplit=1)[0]
    )
    assert checklist == "- Missing-Needle-9F"
    assert "SENSITIVE-FAILED-ANSWER" not in prompts[0]
    assert repair.repaired is True
    metadata = json.dumps(repair.to_metadata())
    assert "Missing-Needle-9F" not in metadata
    assert "SENSITIVE-FAILED-ANSWER" not in metadata


@pytest.mark.asyncio
async def test_output_contract_stops_after_one_failed_retry() -> None:
    calls = 0
    evidence_pack = build_chat_evidence_pack(memory_context="", internet_context=None)
    contract = ChatOutputContract(
        contract_id="exact_json",
        exact_json_keys=("status",),
    )

    async def retry_once(_prompt: str) -> ChatRepairAttemptResult:
        nonlocal calls
        calls += 1
        return ChatRepairAttemptResult(text="still not json", model_used="local")

    repair = await run_chat_repair_loop(
        response_text="not json",
        user_msg="Return only a JSON object with key status.",
        evidence_pack=evidence_pack,
        retry_once=retry_once,
        output_contract=contract,
    )

    assert calls == 1
    assert repair.attempts == 1
    assert repair.repaired is False
    assert repair.reason == "output_contract_retry_failed_verification"
    assert repair.output_contract is not None
    assert repair.output_contract.passed is False
    assert repair.text == "still not json"
    assert repair.output_contract == evaluate_chat_output_contract(
        repair.text,
        contract,
    )


@pytest.mark.asyncio
async def test_failed_contract_retry_keeps_retry_issues_aligned() -> None:
    evidence_pack = build_chat_evidence_pack(memory_context="", internet_context=None)
    contract = ChatOutputContract(
        contract_id="safe_recovery",
        required_terms=("privacy",),
        ordered_terms=("contain", "verify", "rollback", "monitor"),
    )

    async def retry_once(_prompt: str) -> ChatRepairAttemptResult:
        return ChatRepairAttemptResult(
            text="Privacy monitor then contain.",
            model_used="local",
        )

    repair = await run_chat_repair_loop(
        response_text="Contain then rollback.",
        user_msg="Provide the privacy recovery stages.",
        evidence_pack=evidence_pack,
        retry_once=retry_once,
        output_contract=contract,
    )

    assert repair.repaired is False
    assert repair.text == "Privacy monitor then contain."
    assert repair.output_contract == evaluate_chat_output_contract(
        repair.text,
        contract,
    )
    assert repair.after_issues == repair.verification.issues


@pytest.mark.asyncio
async def test_output_contract_preflight_skips_repair_call() -> None:
    calls = 0
    evidence_pack = build_chat_evidence_pack(memory_context="", internet_context=None)
    contract = ChatOutputContract(
        contract_id="conflicting_terms",
        required_terms=("purge",),
        forbidden_terms=("purge",),
    )

    async def retry_once(_prompt: str) -> ChatRepairAttemptResult:
        nonlocal calls
        calls += 1
        return ChatRepairAttemptResult(text="should not run", model_used="local")

    repair = await run_chat_repair_loop(
        response_text=CHAT_OUTPUT_CONTRACT_INFEASIBLE_RESPONSE,
        user_msg=PHASE32_CONFLICT_PROMPT,
        evidence_pack=evidence_pack,
        retry_once=retry_once,
        output_contract=contract,
    )

    assert calls == 0
    assert repair.attempted is False
    assert repair.action == "skip_generation"
    assert repair.reason == "output_contract_infeasible"
    assert repair.verification.issues == ("output_contract_contract_infeasible",)
    assert repair.to_metadata()["chat_output_contract_preflight_action"] == (
        "skip_generation"
    )


@pytest.mark.asyncio
async def test_stream_single_preflight_skips_initial_and_repair_model_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake_route(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise AssertionError("infeasible contract must not reach a provider")

    monkeypatch.setattr(chat, "route", fake_route)
    outcome: dict[str, object] = {}
    evidence_pack = build_chat_evidence_pack(memory_context="", internet_context=None)

    chunks = [
        chunk
        async for chunk in chat._stream_single(
            f"User: {PHASE32_CONFLICT_PROMPT}",
            "local",
            "thread-contract-infeasible",
            "local",
            PHASE32_CONFLICT_PROMPT,
            evidence_pack=evidence_pack,
            chat_outcome_holder=outcome,
        )
    ]

    assert calls == 0
    assert _streamed_text(chunks) == CHAT_OUTPUT_CONTRACT_INFEASIBLE_RESPONSE
    assert outcome["chat_output_contract_feasible"] is False
    assert outcome["chat_output_contract_preflight_action"] == "skip_generation"
    assert outcome["chat_repair_action"] == "skip_generation"
    assert outcome["chat_outcome_quality_reason"] == "output_contract_infeasible"
    assert outcome["chat_outcome_escalation_rung"] == "operator_review"


@pytest.mark.asyncio
async def test_stream_council_preflight_skips_all_model_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake_route(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise AssertionError("infeasible contract must not reach council providers")

    monkeypatch.setattr(chat, "route", fake_route)
    outcome: dict[str, object] = {}
    detail: dict[str, object] = {}
    evidence_pack = build_chat_evidence_pack(memory_context="", internet_context=None)

    chunks = [
        chunk
        async for chunk in chat._stream_council(
            f"User: {PHASE32_CONFLICT_PROMPT}",
            ["claude", "gemini"],
            "thread-council-contract-infeasible",
            True,
            PHASE32_CONFLICT_PROMPT,
            evidence_pack=evidence_pack,
            council_detail_holder=detail,
            chat_outcome_holder=outcome,
        )
    ]

    assert calls == 0
    assert _streamed_text(chunks).strip() == CHAT_OUTPUT_CONTRACT_INFEASIBLE_RESPONSE
    assert detail["model_count"] == 0
    assert detail["synthesis_model"] == chat.CONTRACT_FEASIBILITY_MODEL_LABEL
    assert outcome["chat_output_contract_feasible"] is False
    assert outcome["chat_outcome_quality_reason"] == "output_contract_infeasible"


@pytest.mark.asyncio
async def test_stream_single_fails_closed_after_contract_retry_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake_route(
        _prompt: str,
        _mode: str,
        **kwargs: object,
    ) -> dict[str, object]:
        nonlocal calls
        calls += 1
        assert "generation_policy" in kwargs
        return {"result": "not json", "mode": "local"}

    monkeypatch.setattr(chat, "route", fake_route)
    outcome: dict[str, object] = {}
    evidence_pack = build_chat_evidence_pack(memory_context="", internet_context=None)

    chunks = [
        chunk
        async for chunk in chat._stream_single(
            "User: Return only a JSON object with key status.",
            "local",
            "thread-contract-failed",
            "local",
            "Return only a JSON object with key status.",
            evidence_pack=evidence_pack,
            chat_outcome_holder=outcome,
        )
    ]

    assert calls == 2
    assert _streamed_text(chunks) == (
        "I could not satisfy the requested output contract reliably. Try again "
        "or switch to a stronger model."
    )
    assert outcome["chat_outcome_quality_reason"] == "output_contract_failed"
    assert outcome["chat_outcome_escalation_rung"] == "operator_review"


@pytest.mark.asyncio
async def test_stream_single_enforces_exact_json_for_local_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    async def fake_route(
        prompt: str,
        mode: str,
        **kwargs: object,
    ) -> dict[str, object]:
        prompts.append(prompt)
        assert "generation_policy" in kwargs
        if len(prompts) == 1:
            return {"result": "Owner is Delta.", "mode": "local"}
        return {"result": '{"owner":"Delta"}', "mode": "local"}

    monkeypatch.setattr(chat, "route", fake_route)
    outcome: dict[str, object] = {}
    evidence_pack = build_chat_evidence_pack(memory_context="", internet_context=None)

    chunks = [
        chunk
        async for chunk in chat._stream_single(
            "User: Return only a JSON object with key owner.",
            "local",
            "thread-contract",
            "local",
            "Return only a JSON object with key owner.",
            evidence_pack=evidence_pack,
            chat_outcome_holder=outcome,
        )
    ]

    assert len(prompts) == 2
    assert "Output contract" in prompts[0]
    assert _streamed_text(chunks) == '{"owner":"Delta"}'
    assert outcome["chat_output_contract_id"] == "exact_json"
    assert outcome["chat_output_contract_passed"] is True
    assert outcome["chat_outcome_quality_action"] == "accept"


@pytest.mark.asyncio
async def test_stream_single_normalizes_isolated_json_fence_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake_route(
        _prompt: str,
        _mode: str,
        **kwargs: object,
    ) -> dict[str, object]:
        nonlocal calls
        calls += 1
        assert "generation_policy" in kwargs
        return {
            "result": '```json\n{"status": "ready"}\n```',
            "mode": "local",
        }

    monkeypatch.setattr(chat, "route", fake_route)
    outcome: dict[str, object] = {}
    evidence_pack = build_chat_evidence_pack(memory_context="", internet_context=None)

    chunks = [
        chunk
        async for chunk in chat._stream_single(
            "User: Return only a JSON object with key status.",
            "local",
            "thread-contract-normalized",
            "local",
            "Return only a JSON object with key status.",
            evidence_pack=evidence_pack,
            chat_outcome_holder=outcome,
        )
    ]

    assert calls == 1
    assert _streamed_text(chunks) == '{"status":"ready"}'
    assert outcome["chat_repair_action"] == "normalize_output_contract"
    assert outcome["chat_repair_before_issues"] == [
        "output_contract_json_object_required"
    ]
    assert outcome["chat_outcome_quality_action"] == "accept"


def _streamed_text(chunks: list[str]) -> str:
    parts: list[str] = []
    for chunk in chunks:
        if not chunk.startswith("data: ") or "[DONE]" in chunk:
            continue
        payload = json.loads(chunk[6:])
        if "delta" in payload and not payload.get("done"):
            parts.append(str(payload["delta"]))
    return "".join(parts)
