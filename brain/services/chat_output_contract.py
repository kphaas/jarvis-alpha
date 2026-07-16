"""Explicit, model-agnostic output contracts for Alpha chat responses."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

from brain.routing.generation_policy import ChatGenerationPolicy
from brain.services.chat_evidence_pack import ChatResponseVerification

CHAT_OUTPUT_CONTRACT_SCHEMA_VERSION = "chat_output_contract.v1"
CHAT_OUTPUT_CONTRACT_FEASIBILITY_SCHEMA_VERSION = "chat_output_contract_feasibility.v1"
CHAT_OUTPUT_CONTRACT_FEASIBILITY_METADATA_KEYS = (
    "chat_output_contract_feasibility_schema_version",
    "chat_output_contract_feasible",
    "chat_output_contract_conflict_count",
    "chat_output_contract_conflicts",
    "chat_output_contract_preflight_action",
)
_JSON_KEYS_RE = re.compile(
    r"(?is)\b(?:return|respond\s+with|output)\s+only\s+(?:a\s+)?json\s+object"
    r"\s+with\s+keys?\s+(.+?)(?:\.\s|\.$|$)"
)
_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_-]*\b")
_PRIVACY_VALUE_RE = re.compile(r"(?i)\b([a-z][a-z0-9_-]*)\s+privacy\b")
_SENTENCE_LIMIT_RE = re.compile(
    r"(?i)\b(?:in|at\s+most)\s+(one|two|three|four|five|\d+)\s+sentences?\b"
)
_SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+|$)")
_JSON_FENCE_RE = re.compile(r"(?is)\A```(?:json)?\s*\n(.*?)\n```\s*\Z")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


@dataclass(frozen=True)
class ChatOutputConstraintSlot:
    """Typed content that Alpha may safely restore after one failed repair."""

    slot_id: str
    required_terms: tuple[str, ...]
    render_text: str


@dataclass(frozen=True)
class ChatOutputContract:
    """Constraints that can be validated without provider-specific APIs."""

    contract_id: str
    exact_json_keys: tuple[str, ...] = ()
    required_terms: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    ordered_terms: tuple[str, ...] = ()
    max_sentences: int | None = None
    constraint_slots: tuple[ChatOutputConstraintSlot, ...] = ()


@dataclass(frozen=True)
class ChatOutputContractEvaluation:
    contract_id: str
    passed: bool
    issues: tuple[str, ...]

    def to_metadata(self) -> dict[str, object]:
        return {
            "chat_output_contract_schema_version": (
                CHAT_OUTPUT_CONTRACT_SCHEMA_VERSION
            ),
            "chat_output_contract_applied": True,
            "chat_output_contract_id": self.contract_id,
            "chat_output_contract_passed": self.passed,
            "chat_output_contract_issue_count": len(self.issues),
            "chat_output_contract_issues": list(self.issues),
        }


@dataclass(frozen=True)
class ChatOutputContractFeasibility:
    contract_id: str
    feasible: bool
    conflicts: tuple[str, ...]

    def to_metadata(self) -> dict[str, object]:
        return {
            "chat_output_contract_feasibility_schema_version": (
                CHAT_OUTPUT_CONTRACT_FEASIBILITY_SCHEMA_VERSION
            ),
            "chat_output_contract_feasible": self.feasible,
            "chat_output_contract_conflict_count": len(self.conflicts),
            "chat_output_contract_conflicts": list(self.conflicts),
            "chat_output_contract_preflight_action": (
                "allow_generation" if self.feasible else "skip_generation"
            ),
        }


def generation_policy_for_chat_output_contract(
    contract: ChatOutputContract,
) -> ChatGenerationPolicy:
    """Compile provider-neutral decoding controls from a validated contract."""

    return ChatGenerationPolicy(
        deterministic=True,
        json_mode=bool(contract.exact_json_keys),
        exact_json_keys=contract.exact_json_keys,
    )


def compile_explicit_chat_output_contract(
    user_msg: str,
) -> ChatOutputContract | None:
    """Compile only constraints explicitly requested by the user."""

    normalized = user_msg.casefold()
    features: list[str] = []
    json_keys = _explicit_json_keys(user_msg)
    required_terms: list[str] = []
    forbidden_terms: list[str] = []
    ordered_terms: tuple[str, ...] = ()
    constraint_slots: list[ChatOutputConstraintSlot] = []

    if json_keys:
        features.append("exact_json")

    if "privacy tradeoff" in normalized:
        features.append("privacy_tradeoff")
        privacy_terms = ["privacy"]
        if "cost" in normalized:
            privacy_terms.append("cost")
        privacy_values = tuple(
            match.group(1)
            for match in _PRIVACY_VALUE_RE.finditer(user_msg)
            if match.group(1).casefold() not in {"a", "and", "the"}
        )
        privacy_terms.extend(privacy_values)
        required_terms.extend(privacy_terms)
        label = (
            "Privacy and cost tradeoff" if "cost" in normalized else "Privacy tradeoff"
        )
        detail = " versus ".join(privacy_values)
        constraint_slots.append(
            ChatOutputConstraintSlot(
                slot_id="privacy_tradeoff",
                required_terms=_unique(privacy_terms),
                render_text=f"{label}: {detail}." if detail else f"{label}.",
            )
        )

    if "recovery plan" in normalized and (
        "containment" in normalized or "failed routing rollout" in normalized
    ):
        features.append("safe_recovery")
        ordered_terms = ("contain", "verify", "rollback", "monitor")
        if "operator approval" in normalized:
            required_terms.append("operator approval")
        if "preserve audit" in normalized:
            required_terms.extend(("preserve", "audit"))
        if "do not delete" in normalized:
            forbidden_terms.extend(("delete the", "delete all", "purge"))

    max_sentences = _explicit_sentence_limit(user_msg)
    if max_sentences is not None:
        features.append("sentence_limit")

    if not (
        json_keys
        or required_terms
        or forbidden_terms
        or ordered_terms
        or max_sentences is not None
    ):
        return None

    return ChatOutputContract(
        contract_id="+".join(features),
        exact_json_keys=json_keys,
        required_terms=_unique(required_terms),
        forbidden_terms=_unique(forbidden_terms),
        ordered_terms=ordered_terms,
        max_sentences=max_sentences,
        constraint_slots=tuple(constraint_slots),
    )


def evaluate_chat_output_contract(
    response_text: str,
    contract: ChatOutputContract,
) -> ChatOutputContractEvaluation:
    issues: list[str] = []
    cleaned = response_text.strip()
    normalized = cleaned.casefold()

    if contract.exact_json_keys:
        try:
            parsed = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if not isinstance(parsed, dict):
            issues.append("json_object_required")
        elif set(parsed) != set(contract.exact_json_keys):
            issues.append("json_keys_mismatch")

    if _missing_required_terms(response_text=cleaned, contract=contract):
        issues.append("required_content_missing")
    if contract.forbidden_terms and any(
        term.casefold() in normalized for term in contract.forbidden_terms
    ):
        issues.append("forbidden_content_present")
    if contract.ordered_terms:
        positions = [
            normalized.find(term.casefold()) for term in contract.ordered_terms
        ]
        if not all(position >= 0 for position in positions) or positions != sorted(
            positions
        ):
            issues.append("required_order_invalid")
    if (
        contract.max_sentences is not None
        and not contract.exact_json_keys
        and _sentence_count(cleaned) > contract.max_sentences
    ):
        issues.append("sentence_limit_exceeded")

    unique_issues = _unique(issues)
    return ChatOutputContractEvaluation(
        contract_id=contract.contract_id,
        passed=not unique_issues,
        issues=unique_issues,
    )


def evaluate_chat_output_contract_feasibility(
    contract: ChatOutputContract,
) -> ChatOutputContractFeasibility:
    """Reject contracts whose mandatory text necessarily violates an exclusion."""

    conflicts: list[str] = []
    if contract.max_sentences is not None and contract.max_sentences < 1:
        conflicts.append("sentence_limit_invalid")
    if _mandatory_terms_conflict(contract.required_terms, contract.forbidden_terms):
        conflicts.append("required_term_forbidden")
    if _mandatory_terms_conflict(contract.ordered_terms, contract.forbidden_terms):
        conflicts.append("ordered_term_forbidden")
    conflicts.extend(_constraint_slot_conflicts(contract))
    unique_conflicts = _unique(conflicts)
    return ChatOutputContractFeasibility(
        contract_id=contract.contract_id,
        feasible=not unique_conflicts,
        conflicts=unique_conflicts,
    )


def normalize_chat_output_contract_response(
    response_text: str,
    contract: ChatOutputContract,
) -> tuple[str, bool]:
    """Apply bounded structural normalization without changing answer content."""

    cleaned = response_text.strip()
    if contract.exact_json_keys:
        fence_match = _JSON_FENCE_RE.fullmatch(cleaned)
        candidate = fence_match.group(1).strip() if fence_match else cleaned
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            return response_text, False
        if not isinstance(parsed, dict) or set(parsed) != set(contract.exact_json_keys):
            return response_text, False
        normalized = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        return normalized, normalized != response_text

    if (
        contract.max_sentences is not None
        and _sentence_count(cleaned) > contract.max_sentences
    ):
        parts = [
            part.strip()
            for part in _SENTENCE_BOUNDARY_RE.split(cleaned)
            if part.strip()
        ]
        while len(parts) > contract.max_sentences:
            first = parts.pop(0).rstrip(".!?")
            parts[0] = f"{first}; {parts[0]}"
        normalized = " ".join(parts)
        return normalized, normalized != response_text

    return response_text, False


def finalize_chat_output_contract_response(
    response_text: str,
    contract: ChatOutputContract,
) -> tuple[str, bool]:
    """Restore one typed missing slot only when the whole contract then passes."""

    if (
        not response_text.strip()
        or contract.exact_json_keys
        or not contract.constraint_slots
        or not evaluate_chat_output_contract_feasibility(contract).feasible
    ):
        return response_text, False

    missing_slots = tuple(
        slot
        for slot in contract.constraint_slots
        if _missing_terms(response_text=response_text, terms=slot.required_terms)
    )
    if len(missing_slots) != 1:
        return response_text, False

    base = response_text.strip()
    render_text = missing_slots[0].render_text.strip()
    separator = " " if base.endswith((".", "!", "?")) else ". "
    candidate, _normalized = normalize_chat_output_contract_response(
        f"{base}{separator}{render_text}",
        contract,
    )
    if not evaluate_chat_output_contract(candidate, contract).passed:
        return response_text, False
    return candidate, candidate != response_text


def apply_chat_output_contract_verification(
    verification: ChatResponseVerification,
    evaluation: ChatOutputContractEvaluation,
) -> ChatResponseVerification:
    contract_issues = tuple(f"output_contract_{issue}" for issue in evaluation.issues)
    issues = _unique((*verification.issues, *contract_issues))
    return ChatResponseVerification(
        verified=not issues,
        issues=issues,
        requires_web_verification=verification.requires_web_verification,
        evidence_count=verification.evidence_count,
    )


def render_chat_output_contract_prompt(
    *,
    prompt: str,
    contract: ChatOutputContract,
) -> str:
    return f"{prompt}\n\n{_contract_instruction(contract)}"


def render_chat_output_contract_repair_prompt(
    *,
    user_msg: str,
    contract: ChatOutputContract,
    issues: tuple[str, ...],
    failed_response_text: str | None = None,
) -> str:
    issue_summary = ", ".join(issues) or "contract_validation_failed"
    targeted_instruction = _targeted_missing_term_instruction(
        response_text=failed_response_text,
        contract=contract,
        issues=issues,
    )
    return (
        "Repair the answer to the original request below. The prior answer is not "
        "included because it is untrusted. Return only the corrected answer.\n\n"
        f"Original request:\n{user_msg}\n\n"
        f"Validation failures: {issue_summary}\n\n"
        f"{targeted_instruction}"
        f"{_contract_instruction(contract)}"
    )


def _targeted_missing_term_instruction(
    *,
    response_text: str | None,
    contract: ChatOutputContract,
    issues: tuple[str, ...],
) -> str:
    if response_text is None or "required_content_missing" not in issues:
        return ""
    missing_terms = _missing_required_terms(
        response_text=response_text,
        contract=contract,
    )
    if not missing_terms:
        return ""
    checklist = "\n".join(f"- {term}" for term in missing_terms)
    return (
        "Targeted validation checklist (include each missing term exactly):\n"
        f"{checklist}\n\n"
    )


def _contract_instruction(contract: ChatOutputContract) -> str:
    rules: list[str] = ["Output contract (all rules are mandatory):"]
    if contract.exact_json_keys:
        rules.append(
            "- Return exactly one JSON object with no Markdown or commentary. "
            "Use exactly these keys: " + ", ".join(contract.exact_json_keys) + "."
        )
    if contract.required_terms:
        rules.append(
            "- Cover every required term or phrase: "
            + ", ".join(contract.required_terms)
            + "."
        )
    if contract.forbidden_terms:
        rules.append(
            "- Do not include any forbidden term or phrase: "
            + ", ".join(contract.forbidden_terms)
            + "."
        )
    if contract.ordered_terms:
        rules.append(
            "- Present these stages in this order: "
            + " -> ".join(contract.ordered_terms)
            + "."
        )
    if contract.max_sentences is not None:
        rules.append(f"- Use at most {contract.max_sentences} sentence(s).")
    return "\n".join(rules)


def _explicit_json_keys(user_msg: str) -> tuple[str, ...]:
    match = _JSON_KEYS_RE.search(user_msg)
    if not match:
        return ()
    candidate = re.sub(r"(?i)\band\b", " ", match.group(1))
    return _unique(_IDENTIFIER_RE.findall(candidate))


def _explicit_sentence_limit(user_msg: str) -> int | None:
    match = _SENTENCE_LIMIT_RE.search(user_msg)
    if not match:
        return None
    raw = match.group(1).casefold()
    return _NUMBER_WORDS.get(raw, int(raw) if raw.isdigit() else None)


def _mandatory_terms_conflict(
    mandatory_terms: Iterable[str],
    forbidden_terms: Iterable[str],
) -> bool:
    normalized_forbidden = tuple(
        term.strip().casefold() for term in forbidden_terms if term.strip()
    )
    return any(
        forbidden in mandatory.strip().casefold()
        for mandatory in mandatory_terms
        for forbidden in normalized_forbidden
    )


def _constraint_slot_conflicts(contract: ChatOutputContract) -> tuple[str, ...]:
    if not contract.constraint_slots:
        return ()

    conflicts: list[str] = []
    slot_ids = [slot.slot_id.casefold() for slot in contract.constraint_slots]
    if contract.exact_json_keys:
        conflicts.append("constraint_slot_json_unsupported")
    if len(slot_ids) != len(set(slot_ids)) or any(
        not _IDENTIFIER_RE.fullmatch(slot_id) for slot_id in slot_ids
    ):
        conflicts.append("constraint_slot_invalid")

    required_terms = {term.casefold() for term in contract.required_terms}
    for slot in contract.constraint_slots:
        if (
            not slot.required_terms
            or any(not term.strip() for term in slot.required_terms)
            or len(slot.required_terms)
            != len({term.casefold() for term in slot.required_terms})
            or not slot.render_text.strip()
        ):
            conflicts.append("constraint_slot_invalid")
            continue
        if any(term.casefold() not in required_terms for term in slot.required_terms):
            conflicts.append("constraint_slot_unbound")
        if _missing_terms(
            response_text=slot.render_text,
            terms=slot.required_terms,
        ):
            conflicts.append("constraint_slot_render_incomplete")
        if any(
            forbidden.casefold() in slot.render_text.casefold()
            and all(
                forbidden.casefold() not in term.casefold()
                for term in slot.required_terms
            )
            for forbidden in contract.forbidden_terms
        ):
            conflicts.append("constraint_slot_forbidden")
    return _unique(conflicts)


def _missing_required_terms(
    *,
    response_text: str,
    contract: ChatOutputContract,
) -> tuple[str, ...]:
    return _missing_terms(response_text=response_text, terms=contract.required_terms)


def _missing_terms(
    *,
    response_text: str,
    terms: Iterable[str],
) -> tuple[str, ...]:
    normalized = response_text.casefold()
    return tuple(term for term in terms if term.casefold() not in normalized)


def _sentence_count(text: str) -> int:
    return sum(bool(match.group(0).strip()) for match in _SENTENCE_RE.finditer(text))


def _unique(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))
