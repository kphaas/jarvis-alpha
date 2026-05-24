from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, time
from hashlib import sha256
from typing import Any

import httpx

from brain.services.gmail_client import GmailMessage

SCHOOL_TERMS = ("mount pisgah", "pisgah", "mpcs")
EVENT_TERMS = (
    "calendar",
    "conference",
    "concert",
    "deadline",
    "dismissal",
    "event",
    "field trip",
    "holiday",
    "meeting",
    "open house",
    "practice",
    "program",
    "school",
)
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
MONTH_PATTERN = "|".join(MONTHS)


@dataclass(frozen=True)
class SchoolEventCandidate:
    title: str
    event_date: date
    event_time: time | None
    end_time: time | None
    location: str | None
    notes: str | None
    confidence: float
    family_external_id: str


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _subject_title(subject: str | None) -> str:
    value = re.sub(r"(?i)^(re|fw|fwd):\s*", "", subject or "").strip()
    value = re.sub(r"(?i)\s*[-|]\s*mount pisgah.*$", "", value).strip()
    return value[:120] or "School event"


def _is_school_message(message: GmailMessage) -> bool:
    haystack = " ".join(
        [
            message.sender or "",
            message.subject or "",
            message.snippet or "",
            message.body_text,
        ]
    ).lower()
    return any(term in haystack for term in SCHOOL_TERMS)


def _parse_time(value: str) -> time | None:
    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m?\.?\b", value, re.I)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    meridiem = match.group(3).lower()
    if hour == 12:
        hour = 0
    if meridiem == "p":
        hour += 12
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _year_for(month: int, day: int, anchor: date) -> int:
    candidate = date(anchor.year, month, day)
    if (candidate - anchor).days < -120:
        return anchor.year + 1
    return anchor.year


def _extract_dates(text: str, anchor: date) -> list[date]:
    found: list[date] = []
    for match in re.finditer(
        rf"\b({MONTH_PATTERN})\s+(\d{{1,2}})(?:,\s*(\d{{4}}))?\b",
        text,
        re.I,
    ):
        month = MONTHS[match.group(1).lower()]
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else _year_for(month, day, anchor)
        try:
            found.append(date(year, month, day))
        except ValueError:
            continue

    for match in re.finditer(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text):
        month = int(match.group(1))
        day = int(match.group(2))
        if not 1 <= month <= 12:
            continue
        year_text = match.group(3)
        year = _year_for(month, day, anchor)
        if year_text:
            year = int(year_text)
            if year < 100:
                year += 2000
        try:
            found.append(date(year, month, day))
        except ValueError:
            continue
    return sorted(set(found))


def _location(text: str) -> str | None:
    match = re.search(r"\b(?:at|location:)\s+([A-Z][A-Za-z0-9 &'-]{3,80})", text)
    if not match:
        return None
    return match.group(1).strip(" .,\n")[:100]


def _external_id(message: GmailMessage, event_date: date, title: str) -> str:
    basis = f"{message.gmail_message_id}|{event_date.isoformat()}|{title.lower()}"
    digest = sha256(basis.encode("utf-8")).hexdigest()[:24]
    return f"alpha:gmail:mount-pisgah:{digest}"


def extract_school_events_deterministic(
    message: GmailMessage, anchor: date | None = None
) -> list[SchoolEventCandidate]:
    if not _is_school_message(message):
        return []
    anchor = anchor or date.today()
    text = _clean_text(
        "\n".join([message.subject or "", message.snippet or "", message.body_text])
    )
    dates = _extract_dates(text, anchor)
    if not dates:
        return []

    title = _subject_title(message.subject)
    event_time = _parse_time(text)
    location = _location(text)
    has_event_term = any(term in text.lower() for term in EVENT_TERMS)
    confidence = 0.68 + (0.12 if event_time else 0) + (0.1 if has_event_term else 0)
    confidence = min(confidence, 0.92)

    candidates: list[SchoolEventCandidate] = []
    for event_date in dates[:5]:
        candidates.append(
            SchoolEventCandidate(
                title=title,
                event_date=event_date,
                event_time=event_time,
                end_time=None,
                location=location,
                notes=(message.snippet or text[:240] or None),
                confidence=confidence,
                family_external_id=_external_id(message, event_date, title),
            )
        )
    return candidates


def _parse_llm_json(text: str) -> list[dict[str, Any]]:
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _candidate_from_llm(
    row: dict[str, Any], message: GmailMessage
) -> SchoolEventCandidate | None:
    try:
        event_date = date.fromisoformat(str(row["event_date"]))
    except (KeyError, ValueError, TypeError):
        return None
    event_time = None
    if row.get("event_time"):
        try:
            event_time = time.fromisoformat(str(row["event_time"])[:5])
        except ValueError:
            event_time = None
    title = _clean_text(str(row.get("title") or _subject_title(message.subject)))[:120]
    confidence = float(row.get("confidence") or 0.75)
    return SchoolEventCandidate(
        title=title or "School event",
        event_date=event_date,
        event_time=event_time,
        end_time=None,
        location=_clean_text(row.get("location"))[:100] or None,
        notes=_clean_text(row.get("notes"))[:300] or message.snippet,
        confidence=max(0.0, min(confidence, 0.98)),
        family_external_id=_external_id(message, event_date, title),
    )


async def extract_school_events(
    message: GmailMessage, anchor: date | None = None
) -> list[SchoolEventCandidate]:
    if os.environ.get("ALPHA_SCHOOL_EMAIL_USE_LLM", "true").lower() != "true":
        return extract_school_events_deterministic(message, anchor)
    if not _is_school_message(message):
        return []

    prompt = (
        "You are a local-only family calendar extraction agent. "
        "Return JSON only: an array of objects with title, event_date "
        "(YYYY-MM-DD), event_time (HH:MM or null), location, notes, confidence. "
        "Extract only Mount Pisgah school events, deadlines, no-school days, "
        "meetings, performances, sports, or parent action dates.\n\n"
        f"Subject: {message.subject or ''}\n"
        f"Sender: {message.sender or ''}\n"
        f"Snippet: {message.snippet or ''}\n"
        f"Body:\n{message.body_text[:6000]}"
    )
    model = os.environ.get("ALPHA_SCHOOL_EMAIL_MODEL", "llama3.1:8b")
    url = (
        os.environ.get("ALPHA_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        + "/api/generate"
    )
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(
                url,
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.0},
                },
            )
        if response.status_code < 400:
            rows = _parse_llm_json(str(response.json().get("response", "")))
            candidates = [
                candidate
                for row in rows
                if (candidate := _candidate_from_llm(row, message)) is not None
            ]
            if candidates:
                return candidates[:8]
    except Exception:
        pass
    return extract_school_events_deterministic(message, anchor)
