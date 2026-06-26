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
_SELF_TRAIT_TEXT = re.compile(
    r"\b(i am|i'm|im|i consider myself|people describe me as|my default is)\s+"
    r"(a\s+|an\s+|the\s+)?[a-z][a-z -]{2,80}\b",
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
_KNOWN_PEOPLE_BY_ALIAS = {
    "ken": "ken",
    "kenneth": "ken",
    "sweta": "sweta",
    "ryleigh": "ryleigh",
    "sloane": "sloane",
    "meagan": "meagan",
}
_KNOWN_PEOPLE = tuple(sorted(set(_KNOWN_PEOPLE_BY_ALIAS.values())))
_PROPER_NOUN_STOPWORDS = {
    "ask",
    "at",
    "alpha",
    "memory",
    "project",
    "trip",
    "key",
    "spark",
    "helm",
    "dream",
    "buddy",
}
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
    extraction_tags: tuple[str, ...] = field(default_factory=tuple)
    extracted_entities: tuple[str, ...] = field(default_factory=tuple)
    extracted_phrases: tuple[str, ...] = field(default_factory=tuple)
    extracted_traits: tuple[str, ...] = field(default_factory=tuple)
    extracted_projects: tuple[str, ...] = field(default_factory=tuple)
    extracted_locations: tuple[str, ...] = field(default_factory=tuple)
    temporal_kind: str | None = None
    currentness_policy: str | None = None
    review_reasons: tuple[str, ...] = field(default_factory=tuple)


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
        graph_payload = _graph_node_payload(
            note=clean,
            principal_id=principal_id,
            target_label=target_label,
        )
        return SparkMemoryRoutePlan(
            status="routable",
            destination="temporal_graph",
            note=clean,
            reason="people/project/relationship fact changes over time",
            risk="reviewed_write",
            review_lane="memory_graph_reviewed_write",
            confidence=0.78,
            graph_payload=graph_payload,
            extraction_tags=tuple(graph_payload["properties"]["extraction_tags"]),
            extracted_entities=tuple(graph_payload["properties"]["people"]),
            extracted_projects=tuple(graph_payload["properties"]["projects"]),
            extracted_locations=tuple(graph_payload["properties"]["locations"]),
            temporal_kind=str(graph_payload["properties"]["temporal_kind"]),
            currentness_policy=str(graph_payload["properties"]["currentness_policy"]),
            review_reasons=(
                "temporal_fact_changes_over_time",
                "operator_review_required",
            ),
        )
    if (has_target_context or _has_named_target(clean)) and _TARGET_TEXT.search(clean):
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
            extraction_tags=("target", _target_kind(clean)),
            extracted_entities=tuple(_extract_people(clean)),
            extracted_locations=tuple(_extract_locations(clean)),
            review_reasons=("selected_recipient_context_required",),
        )
    if _PERSONALITY_TEXT.search(clean) or _SELF_TRAIT_TEXT.search(clean):
        personality_kind = _personality_kind(lowered)
        return SparkMemoryRoutePlan(
            status="routable",
            destination="spark_personality",
            note=clean,
            reason="voice/style/value learning belongs in Spark personality memory",
            risk="high_visibility",
            review_lane="spark_personality_memory_review",
            confidence=0.74,
            personality_kind=personality_kind,
            extraction_tags=("personality", personality_kind),
            extracted_entities=("self",),
            extracted_phrases=tuple(_extract_phrases(clean)),
            extracted_traits=tuple(_extract_self_traits(clean)),
            review_reasons=("operator_review_required",),
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
        extraction_tags=("semantic", str(category)),
        extracted_entities=tuple(_extract_people(clean)),
        extracted_locations=tuple(_extract_locations(clean)),
        review_reasons=(
            ("high_visibility_health_or_child_fact",)
            if sensitive
            else ("semantic_review_lane",)
        ),
    )


def _should_route_graph(note: str) -> bool:
    if _HEALTH_OR_CHILD_TEXT.search(note):
        return False
    person_hits = _extract_people(note)
    return bool(_GRAPH_TEXT.search(note) and len(person_hits) >= 2)


def _has_named_target(note: str) -> bool:
    return bool(_extract_people(note))


def _graph_node_payload(
    *,
    note: str,
    principal_id: str,
    target_label: str | None,
) -> dict[str, Any]:
    people = _extract_people(note)
    entity_resolution = _entity_resolution_metadata(note, people)
    raw_entity_keys = entity_resolution.get("entity_keys")
    entity_keys = (
        [key for key in raw_entity_keys if isinstance(key, str)]
        if isinstance(raw_entity_keys, list)
        else []
    )
    raw_unresolved_people = entity_resolution.get("unresolved_people")
    unresolved_people = (
        [person for person in raw_unresolved_people if isinstance(person, str)]
        if isinstance(raw_unresolved_people, list)
        else []
    )
    projects = _extract_projects(note)
    locations = _extract_locations(note)
    graph_kind = _graph_relationship_kind(note)
    temporal_kind = _graph_temporal_kind(note)
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
            "relationship_subjects": people,
            "entity_resolution": entity_resolution,
            "entity_keys": entity_keys,
            "unresolved_entities": unresolved_people,
            "needs_operator_entity_resolution": bool(unresolved_people),
            "conflict_group_key": _conflict_group_key(
                node_type=node_type,
                graph_kind=graph_kind,
                temporal_kind=temporal_kind,
                entity_keys=entity_keys,
            ),
            "projects": projects,
            "locations": locations,
            "graph_kind": graph_kind,
            "temporal_kind": temporal_kind,
            "currentness_policy": _currentness_policy(note),
            "refresh_prompt_after_days": _refresh_prompt_days(temporal_kind),
            "extraction_tags": _graph_extraction_tags(graph_kind, temporal_kind),
            "candidate_relationship": graph_kind,
            "requires_operator_resolution": True,
            "temporal_memory": True,
            "target_label": target_label,
            "source_note_hash": note_hash,
            "extraction_summary": _graph_extraction_summary(
                people=people,
                projects=projects,
                locations=locations,
                temporal_kind=temporal_kind,
            ),
            "review_prompt": "Confirm this temporal fact is current before execution.",
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
        or _SELF_TRAIT_TEXT.search(lowered_note)
    ):
        return "value"
    if "style" in lowered_note:
        return "style"
    return "preference"


def _graph_relationship_kind(note: str) -> str:
    if re.search(r"\b(trip|travel|flight|hotel|vacation)\b", note, re.I):
        return "planning_trip"
    if re.search(r"\b(project|working with|collaborating|collaboration)\b", note, re.I):
        return "project_collaboration"
    if re.search(r"\b(married|dating|partner|relationship|custody)\b", note, re.I):
        return "relationship_state"
    return "people_relationship"


def _extract_people(note: str) -> list[str]:
    lowered = note.casefold()
    non_people = {
        item.casefold()
        for item in [*_extract_locations(note), *_extract_projects(note)]
    }
    people: list[str] = []
    for alias, canonical in _KNOWN_PEOPLE_BY_ALIAS.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            people.append(canonical)
    for proper_name in re.findall(r"\b([A-Z][a-z]{1,32})\b", note):
        normalized = proper_name.casefold()
        if normalized in _PROPER_NOUN_STOPWORDS or normalized in non_people:
            continue
        people.append(_KNOWN_PEOPLE_BY_ALIAS.get(normalized, normalized))
    return _dedupe_fragments(people, max_length=48)


def _entity_resolution_metadata(note: str, people: list[str]) -> dict[str, object]:
    known = [person for person in people if person in _KNOWN_PEOPLE]
    unresolved = [person for person in people if person not in _KNOWN_PEOPLE]
    return {
        "strategy": "known_aliases_plus_name_candidates",
        "known_people": known,
        "unresolved_people": unresolved,
        "entity_keys": [_entity_key(person) for person in people],
        "candidate_count": len(people),
        "needs_operator_resolution": bool(unresolved),
        "source_note_hash": hashlib.sha256(note.encode("utf-8")).hexdigest(),
    }


def _entity_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"person:{normalized}:{digest}" if normalized else f"person:unknown:{digest}"


def _conflict_group_key(
    *,
    node_type: str,
    graph_kind: str,
    temporal_kind: str,
    entity_keys: list[str],
) -> str:
    subject_key = (
        "|".join(sorted(_entity_group_key(key) for key in entity_keys)) or "unresolved"
    )
    return f"{node_type}:{graph_kind}:{temporal_kind}:{subject_key}"


def _entity_group_key(entity_key: str) -> str:
    parts = entity_key.split(":")
    if len(parts) >= 2 and parts[0] == "person" and parts[1]:
        return f"person:{parts[1]}"
    return entity_key


def _extract_phrases(note: str) -> list[str]:
    patterns = (
        r"\b(?:key\s+)?(?:phrase|phrasing|say)\s+(?:i\s+use\s*)?:\s*([^.;!?]{2,80})",
        r"\b(?:a\s+)?(?:key\s+)?phrase\s+i\s+use\s+is\s+([^.;!?]{2,80})",
        r"\bmy\s+(?:key\s+)?phrase\s+is\s+([^.;!?]{2,80})",
        r"\bi\s+(?:often\s+|usually\s+)?say\s+([^.;!?]{2,80})",
    )
    for pattern in patterns:
        phrase_match = re.search(pattern, note, re.IGNORECASE)
        if not phrase_match:
            continue
        phrase = _clean_fragment(phrase_match.group(1), max_length=80)
        return [phrase] if phrase else []
    return []


def _extract_self_traits(note: str) -> list[str]:
    trait_match = re.search(
        r"\b(?:i am|i'm|im|i consider myself|people describe me as|my default is)\s+"
        r"(?:a\s+|an\s+|the\s+)?([a-z][a-z -]{2,80})",
        note,
        re.IGNORECASE,
    )
    if not trait_match:
        return []
    trait = _clean_fragment(trait_match.group(1), max_length=80)
    return [trait] if trait else []


def _extract_projects(note: str) -> list[str]:
    project_matches = re.findall(
        r"\b(?:on|for|the)\s+([A-Za-z0-9][A-Za-z0-9 -]{1,72}\s+project)\b",
        note,
        re.IGNORECASE,
    )
    project_matches = [
        match[4:] if match.casefold().startswith("the ") else match
        for match in project_matches
    ]
    return _dedupe_fragments(project_matches, max_length=80)


def _extract_locations(note: str) -> list[str]:
    location_matches = re.findall(
        r"\b(?:trip|travel|flight|vacation)\s+(?:to|in|for)\s+([A-Z][A-Za-z .'-]{1,60})",
        note,
    )
    return _dedupe_fragments(location_matches, max_length=64)


def _graph_temporal_kind(note: str) -> str:
    if re.search(r"\b(trip|travel|flight|hotel|vacation)\b", note, re.I):
        return "planned_event"
    if re.search(r"\b(project|working with|collaborating|collaboration)\b", note, re.I):
        return "project_state"
    if re.search(r"\b(married|dating|partner|relationship|custody)\b", note, re.I):
        return "relationship_state"
    return "people_state"


def _currentness_policy(note: str) -> str:
    if re.search(r"\b(used to|previously|formerly|was|were)\b", note, re.I):
        return "historical_needs_confirmation"
    if re.search(r"\b(planning|plans?|working|collaborating|dating)\b", note, re.I):
        return "candidate_current"
    return "confirm_current"


def _refresh_prompt_days(temporal_kind: str) -> int:
    if temporal_kind == "planned_event":
        return 30
    if temporal_kind == "project_state":
        return 60
    return 90


def _graph_extraction_tags(graph_kind: str, temporal_kind: str) -> list[str]:
    return ["temporal_graph", graph_kind, temporal_kind, "operator_review_required"]


def _graph_extraction_summary(
    *,
    people: list[str],
    projects: list[str],
    locations: list[str],
    temporal_kind: str,
) -> dict[str, object]:
    return {
        "people_count": len(people),
        "project_count": len(projects),
        "location_count": len(locations),
        "temporal_kind": temporal_kind,
    }


def _dedupe_fragments(values: list[str], *, max_length: int) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        fragment = _clean_fragment(value, max_length=max_length)
        key = fragment.casefold()
        if fragment and key not in seen:
            cleaned.append(fragment)
            seen.add(key)
    return cleaned


def _clean_fragment(value: str, *, max_length: int) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip().strip("\"'.,;:!?"))
    if len(cleaned) > max_length:
        cleaned = cleaned[: max_length - 3].rstrip() + "..."
    return cleaned


def _target_required_metadata() -> tuple[str, ...]:
    return (
        "approval_id",
        "target_ref_hash",
        "target_label",
        "approval_ref_hash",
        "source_reference_hash",
        "chat_guid_hash",
    )
