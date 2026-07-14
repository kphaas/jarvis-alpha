"""Explicit, model-agnostic output contracts for Alpha chat responses."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

from brain.services.chat_evidence_pack import ChatResponseVerification

CHAT_OUTPUT_CONTRACT_SCHEMA_VERSION = "chat_output_contract.v1"
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
class ChatOutputContract:
    """Constraints that can be validated without provider-specific APIs."""

    contract_id: str
    exact_json_keys: tuple[str, ...] = ()
    required_terms: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    ordered_terms: tuple[str, ...] = ()
    max_sentences: int | None = None


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

    if json_keys:
        features.append("exact_json")

    if "privacy tradeoff" in normalized:
        features.append("privacy_tradeoff")
        required_terms.append("privacy")
        if "cost" in normalized:
            required_terms.append("cost")
        required_terms.extend(
            match.group(1)
            for match in _PRIVACY_VALUE_RE.finditer(user_msg)
            if match.group(1).casefold() not in {"a", "and", "the"}
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

    if contract.required_terms and not all(
        term.casefold() in normalized for term in contract.required_terms
    ):
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
) -> str:
    issue_summary = ", ".join(issues) or "contract_validation_failed"
    return (
        "Repair the answer to the original request below. The prior answer is not "
        "included because it is untrusted. Return only the corrected answer.\n\n"
        f"Original request:\n{user_msg}\n\n"
        f"Validation failures: {issue_summary}\n\n"
        f"{_contract_instruction(contract)}"
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


def _sentence_count(text: str) -> int:
    return sum(bool(match.group(0).strip()) for match in _SENTENCE_RE.finditer(text))


def _unique(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))
