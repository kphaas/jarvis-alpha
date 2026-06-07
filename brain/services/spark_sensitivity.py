"""Runtime sensitivity scanner for Spark draft contexts.

This module may inspect runtime-only message bodies, but it returns only topic
labels and policy outcomes. It must not return text excerpts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal

SparkSensitivity = Literal[
    "relationship",
    "minor",
    "family",
    "legal",
    "medical",
    "financial",
    "security",
    "custody",
]


@dataclass(frozen=True, slots=True)
class SparkSensitivityScan:
    detected_topics: tuple[SparkSensitivity, ...]
    blocked_topics: tuple[SparkSensitivity, ...]
    warnings: tuple[str, ...]

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_topics)


_BLOCKING_TOPICS: set[SparkSensitivity] = {
    "legal",
    "medical",
    "financial",
    "security",
    "custody",
    "minor",
}

_PATTERNS: dict[SparkSensitivity, tuple[re.Pattern[str], ...]] = {
    "legal": (
        re.compile(r"\b(attorney|lawyer|lawsuit|subpoena|liable|litigation)\b", re.I),
        re.compile(r"\b(court|legal|contract|settlement|restraining order)\b", re.I),
    ),
    "custody": (
        re.compile(r"\b(custody|parenting plan|visitation|child support)\b", re.I),
        re.compile(r"\b(court order|co-?parent|divorce decree)\b", re.I),
    ),
    "medical": (
        re.compile(r"\b(doctor|hospital|diagnosis|prescription|medication)\b", re.I),
        re.compile(r"\b(therapy|therapist|medical|symptom|treatment)\b", re.I),
    ),
    "financial": (
        re.compile(r"\b(bank|account|wire|invoice|payment|salary|tax)\b", re.I),
        re.compile(r"\b(stock|trade|trading|crypto|loan|debt|mortgage)\b", re.I),
        re.compile(r"(?<!\w)\$\s?\d"),
    ),
    "security": (
        re.compile(r"\b(password|passcode|token|api key|secret|credential)\b", re.I),
        re.compile(r"\b(mfa|2fa|login|social security|ssn)\b", re.I),
    ),
    "minor": (
        re.compile(r"\b(minor|child|children|kid|kids|daughter|son)\b", re.I),
        re.compile(r"\b(school|teacher|daycare|pickup|drop-?off)\b", re.I),
    ),
    "family": (re.compile(r"\b(mother|father|mom|dad|sibling|family)\b", re.I),),
    "relationship": (
        re.compile(r"\b(girlfriend|boyfriend|partner|relationship)\b", re.I),
    ),
}


def scan_spark_draft_sensitivity(
    *,
    texts: Iterable[str],
    protected_topics: Iterable[SparkSensitivity],
    relationship_marked: bool,
    relationship_approved: bool,
) -> SparkSensitivityScan:
    """Detect sensitive topic labels and decide which ones block drafting."""

    haystack = "\n".join(text for text in texts if text).strip()
    protected = set(protected_topics)
    detected: set[SparkSensitivity] = set()

    if relationship_marked:
        detected.add("relationship")

    for topic, patterns in _PATTERNS.items():
        if topic not in protected:
            continue
        if any(pattern.search(haystack) for pattern in patterns):
            detected.add(topic)

    blocked: set[SparkSensitivity] = set()
    for topic in detected:
        if topic == "relationship":
            if not relationship_approved:
                blocked.add(topic)
            continue
        if topic in _BLOCKING_TOPICS and topic in protected:
            blocked.add(topic)

    warnings = tuple(
        f"sensitivity_detected_{topic}"
        for topic in sorted(detected)
        if topic not in blocked
    )
    return SparkSensitivityScan(
        detected_topics=tuple(sorted(detected)),
        blocked_topics=tuple(sorted(blocked)),
        warnings=warnings,
    )
