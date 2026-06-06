"""Treat raw web content as untrusted data, never as instructions."""

from __future__ import annotations

import re

from brain.services.internet_scout.models import SanitizedContent

DEFAULT_MAX_TEXT_CHARS = 12_000
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
PROMPT_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_prior_instructions",
        re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.I),
    ),
    ("system_prompt_reference", re.compile(r"\bsystem\s+prompt\b", re.I)),
    ("developer_message_reference", re.compile(r"\bdeveloper\s+message\b", re.I)),
    ("tool_call_instruction", re.compile(r"\b(call|invoke|use)\s+.*\btool\b", re.I)),
    ("secret_exfiltration", re.compile(r"\b(secrets?|api\s*keys?|tokens?)\b", re.I)),
)


def sanitize_untrusted_text(
    text: str,
    *,
    max_chars: int = DEFAULT_MAX_TEXT_CHARS,
) -> SanitizedContent:
    cleaned = CONTROL_CHAR_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    truncated = len(cleaned) > max_chars
    if truncated:
        cleaned = cleaned[:max_chars]

    markers = [
        marker
        for marker, pattern in PROMPT_INJECTION_PATTERNS
        if pattern.search(cleaned)
    ]
    return SanitizedContent(
        text=cleaned,
        truncated=truncated,
        risk_markers=markers,
        trusted_instructions=False,
    )
