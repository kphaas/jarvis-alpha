"""Deterministic Spark learning router for reviewed memory writes.

The router accepts operator-authored Spark learnings and chooses the safest
existing memory lane. It does not inspect raw message bodies and it does not
execute temporal graph writes; graph updates stay behind the reviewed-write
proposal queue.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from brain.memory.semantic_commands import (
    MemoryCategory,
    MemoryFactValidationError,
    infer_memory_category,
    sanitize_semantic_fact,
)

SparkMemoryDestination = Literal[
    "spark_personality",
    "spark_target",
    "semantic",
    "temporal_graph",
]
SparkMemoryRisk = Literal["standard", "high_visibility", "reviewed_write"]

_PERSONALITY_TEXT = re.compile(
    r"\b(phrase|phrasing|say|voice|tone|style|sound like|avoid sounding|"
    r"kind of person|value|principle)\b",
    re.IGNORECASE,
)
_TARGET_TEXT = re.compile(
    r"\b(they|she|he|target|recipient|thread|follow up|ask|owes|needs|"
    r"prefers|likes|dislikes)\b",
    re.IGNORECASE,
)
_GRAPH_TEXT = re.compile(
    r"\b(planning|plan|trip|relationship|partner|project|working with|"
    r"met with|connected to|collaborating|dating|married|custody)\b",
    re.IGNORECASE,
)
_HEALTH_OR_CHILD_TEXT = re.compile(
    r"\b(health|medical|doctor|medicine|medication|allerg|kidney|emergency|"
    r"ryleigh|sloane|child|daughter|school|teacher|custody)\b",
    re.IGNORECASE,
)
_KNOWN_PEOPLE = ("ken", "sweta", "ryleigh", "sloane", "meagan")
_OPEN_LOOP_TEXT = re.compile(
    r"\b(follow up|ask|todo|to do|needs?|owes|waiting|open loop|remind)\b",
    re.IGNORECASE,
)
_PREFERENCE_TEXT = re.compile(
    r"\b(prefers?|likes?|dislikes?|favorite|avoid|enjoys?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SparkMemoryRoutePlan:
    status: Literal["routable", "rejected"]
    destination: SparkMemoryDestination | None
    note: str
    reason: str
    risk: SparkMemoryRisk
    review_lane: str
    confidence: float
    semantic_category: MemoryCategory | None = None
    personality_kind: str | None = None
    target_kind: str | None = None
    graph_payload: dict[str, Any] | None = None
    required_metadata: tuple[str, ...] = field(default_factory=tuple)


def plan_spark_memory_route(
    *,
    note: str,
    principal_id: str = "ken",
    target_label: str | None = None,
    has_target_context: bool = False,
) -> SparkMemoryRoutePlan:
    """Classify one operator-authored Spark learning into a memory lane."""

    try:
        clean = sanitize_semantic_fact(note)
    except MemoryFactValidationError as exc:
        return SparkMemoryRoutePlan(
            status="rejected",
            destination=None,
            note="",
            reason=exc.detail,
            risk="high_visibility",
            review_lane="rejected",
            confidence=0.0,
        )

    lowered = clean.casefold()
    sensitive = bool(_HEALTH_OR_CHILD_TEXT.search(clean))
    if _should_route_graph(clean):
        return SparkMemoryRoutePlan(
            status="routable",
            destination="temporal_graph",
            note=clean,
            reason="people/project/relationship fact changes over time",
            risk="reviewed_write",
            review_lane="memory_graph_reviewed_write",
            confidence=0.78,
            graph_payload=_graph_node_payload(
                note=clean,
                principal_id=principal_id,
                target_label=target_label,
            ),
        )
    if has_target_context and _TARGET_TEXT.search(clean):
        missing = _target_required_metadata()
        return SparkMemoryRoutePlan(
            status="routable",
            destination="spark_target",
            note=clean,
            reason="selected-recipient memory belongs in Spark target memory",
            risk="high_visibility",
            review_lane="spark_target_memory_review",
            confidence=0.76,
            target_kind=_target_kind(clean),
            required_metadata=missing,
        )
    if _PERSONALITY_TEXT.search(clean):
        return SparkMemoryRoutePlan(
            status="routable",
            destination="spark_personality",
            note=clean,
            reason="voice/style/value learning belongs in Spark personality memory",
            risk="high_visibility",
            review_lane="spark_personality_memory_review",
            confidence=0.74,
            personality_kind=_personality_kind(lowered),
        )

    category = infer_memory_category(clean)
    review_lane = "semantic_high_visibility" if sensitive else "semantic_standard"
    return SparkMemoryRoutePlan(
        status="routable",
        destination="semantic",
        note=clean,
        reason="general durable user fact belongs in semantic memory",
        risk="high_visibility" if sensitive else "standard",
        review_lane=review_lane,
        confidence=0.7,
        semantic_category=category,
    )


def _should_route_graph(note: str) -> bool:
    if _HEALTH_OR_CHILD_TEXT.search(note):
        return False
    lowered = note.casefold()
    person_hits = [name for name in _KNOWN_PEOPLE if name in lowered]
    return bool(_GRAPH_TEXT.search(note) and len(person_hits) >= 2)


def _graph_node_payload(
    *,
    note: str,
    principal_id: str,
    target_label: str | None,
) -> dict[str, Any]:
    people = [name for name in _KNOWN_PEOPLE if name in note.casefold()]
    node_type = (
        "project"
        if re.search(r"\b(plan|planning|trip|project)\b", note, re.I)
        else "relationship"
    )
    label_preview = _label_preview(note)
    note_hash = hashlib.sha256(note.encode("utf-8")).hexdigest()
    return {
        "node_type": node_type,
        "label_preview": label_preview,
        "source": "spark",
        "confidence": 0.78,
        "properties": {
            "memory_router": True,
            "route": "spark_memory_router",
            "people": people,
            "target_label": target_label,
            "source_note_hash": note_hash,
        },
        "provenance": {
            "source_surface": "spark_memory_router",
            "source_action": "spark_learning_route",
            "principal_id": principal_id,
            "contains_raw_spark_body": False,
        },
    }


def _label_preview(note: str) -> str:
    clean = re.sub(r"\s+", " ", note.strip().strip("\"'"))
    if clean.endswith("."):
        clean = clean[:-1]
    if len(clean) > 96:
        clean = clean[:93].rstrip() + "..."
    return clean[0].upper() + clean[1:] if clean else "Spark memory graph note"


def _target_kind(note: str) -> str:
    if _OPEN_LOOP_TEXT.search(note):
        return "open_loop"
    if _PREFERENCE_TEXT.search(note):
        return "preference"
    return "profile_fact"


def _personality_kind(lowered_note: str) -> str:
    if "phrase" in lowered_note or "say" in lowered_note:
        return "phrase"
    if "avoid" in lowered_note:
        return "avoid"
    if (
        "voice" in lowered_note
        or "tone" in lowered_note
        or "sound like" in lowered_note
    ):
        return "voice"
    if (
        "value" in lowered_note
        or "principle" in lowered_note
        or "kind of person" in lowered_note
    ):
        return "value"
    if "style" in lowered_note:
        return "style"
    return "preference"


def _target_required_metadata() -> tuple[str, ...]:
    return (
        "approval_id",
        "target_ref_hash",
        "target_label",
        "approval_ref_hash",
        "source_reference_hash",
        "chat_guid_hash",
    )
