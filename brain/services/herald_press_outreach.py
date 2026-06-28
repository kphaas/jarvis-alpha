from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable


MAX_WEEKLY_PRESS_DRAFTS = 5
DEFAULT_PRESS_KIT_URL = "https://at-0.com/press/"

_WHITESPACE = re.compile(r"\s+")
_BANNED_HYPE = re.compile(
    r"\b(revolutionary|game-changing|next-gen|disruptive|magic)\b",
    re.IGNORECASE,
)
_WRONG_NAME = re.compile(r"\b(AT-0|ATO|At0|at0)\b")
_UNSUBSTANTIATED_CLAIM = re.compile(
    r"\b("
    r"trillion|million users|billion users|guaranteed|hipaa-compliant|"
    r"soc 2|bank-grade|publicly available|fully autonomous|cure"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PressTarget:
    name: str
    outlet: str
    beat: str
    public_profile_url: str
    angle: str


@dataclass(frozen=True, slots=True)
class PressPitchDraft:
    subject: str
    body_text: str
    target_summary: str
    content_hash: str
    safety_flags: tuple[str, ...]
    proof_points: tuple[str, ...]


def create_press_pitch_draft(
    *,
    target: PressTarget,
    proof_points: Iterable[str],
    press_kit_url: str = DEFAULT_PRESS_KIT_URL,
    max_chars: int = 2200,
) -> PressPitchDraft:
    clean_target = clean_press_target(target)
    clean_points = clean_proof_points(proof_points)
    clean_press_kit_url = _clean_url(press_kit_url)
    subject = _fit(
        f"AT0 private AI proof kit for {clean_target.outlet}",
        max_chars=96,
    )
    body = _fit(
        _pitch_body(
            target=clean_target,
            proof_points=clean_points,
            press_kit_url=clean_press_kit_url,
        ),
        max_chars=max_chars,
    )
    flags = list(_safety_flags(subject, body))
    flags.extend(
        (
            "draft_only_no_send",
            "human_review_required",
            "fact_check_required",
            "source_revalidation_required",
        )
    )
    return PressPitchDraft(
        subject=subject,
        body_text=body,
        target_summary=(
            f"{clean_target.name} / {clean_target.outlet} / {clean_target.beat}"
        ),
        content_hash=hash_press_pitch(subject=subject, body_text=body),
        safety_flags=tuple(dict.fromkeys(flags)),
        proof_points=clean_points,
    )


def select_weekly_press_batch(
    targets: Iterable[PressTarget],
    *,
    limit: int = MAX_WEEKLY_PRESS_DRAFTS,
) -> tuple[PressTarget, ...]:
    if limit < 1:
        raise ValueError("weekly_press_limit_too_low")
    if limit > MAX_WEEKLY_PRESS_DRAFTS:
        raise ValueError("weekly_press_limit_exceeded")

    selected: list[PressTarget] = []
    seen: set[str] = set()
    for target in targets:
        clean = clean_press_target(target)
        key = f"{clean.outlet.lower()}::{clean.name.lower()}"
        if key in seen:
            continue
        seen.add(key)
        selected.append(clean)
        if len(selected) >= limit:
            break
    return tuple(selected)


def create_weekly_press_pitch_batch(
    *,
    targets: Iterable[PressTarget],
    proof_points: Iterable[str],
    limit: int = MAX_WEEKLY_PRESS_DRAFTS,
) -> tuple[PressPitchDraft, ...]:
    selected = select_weekly_press_batch(targets, limit=limit)
    clean_points = clean_proof_points(proof_points)
    return tuple(
        create_press_pitch_draft(target=target, proof_points=clean_points)
        for target in selected
    )


def clean_press_target(target: PressTarget) -> PressTarget:
    return PressTarget(
        name=_clean_text(target.name, field="name", min_chars=2, max_chars=80),
        outlet=_clean_text(target.outlet, field="outlet", min_chars=2, max_chars=80),
        beat=_clean_text(target.beat, field="beat", min_chars=8, max_chars=180),
        public_profile_url=_clean_url(target.public_profile_url),
        angle=_clean_text(target.angle, field="angle", min_chars=8, max_chars=220),
    )


def clean_proof_points(proof_points: Iterable[str]) -> tuple[str, ...]:
    clean: list[str] = []
    for point in proof_points:
        value = _clean_text(point, field="proof_point", min_chars=8, max_chars=180)
        if value not in clean:
            clean.append(value)
    if len(clean) < 2:
        raise ValueError("press_pitch_requires_two_proof_points")
    return tuple(clean[:5])


def hash_press_pitch(*, subject: str, body_text: str) -> str:
    return hashlib.sha256(f"{subject}\n\n{body_text}".encode("utf-8")).hexdigest()


def _pitch_body(
    *,
    target: PressTarget,
    proof_points: tuple[str, ...],
    press_kit_url: str,
) -> str:
    first_name = target.name.split()[0]
    proof_lines = "\n".join(f"- {point}" for point in proof_points)
    return (
        f"Hi {first_name},\n\n"
        f"I am reaching out because your public beat is {target.beat}. "
        f"The narrow story angle for {target.outlet}: {target.angle}.\n\n"
        "AT0 is private AI infrastructure from Ken Haas, built around "
        "owner-controlled memory, domain-separated agents, and human approval "
        "for high-stakes actions.\n\n"
        "What can be shown now:\n"
        f"{proof_lines}\n\n"
        f"Press kit: {press_kit_url}\n\n"
        "This is a draft-only pitch for human review. No claim here depends on "
        "public availability, customer metrics, partnerships, medical advice, "
        "financial orders, legal advice, or autonomous high-stakes sends.\n\n"
        "Would this fit your coverage?"
    )


def _safety_flags(subject: str, body_text: str) -> tuple[str, ...]:
    text = f"{subject}\n{body_text}"
    flags: list[str] = []
    if _BANNED_HYPE.search(text):
        flags.append("hype_language")
    if _WRONG_NAME.search(text):
        flags.append("brand_name_violation")
    if _UNSUBSTANTIATED_CLAIM.search(text):
        flags.append("unsubstantiated_claim_review")
    return tuple(flags)


def _clean_text(
    value: str,
    *,
    field: str,
    min_chars: int,
    max_chars: int,
) -> str:
    clean = _WHITESPACE.sub(" ", value.strip())
    if len(clean) < min_chars:
        raise ValueError(f"{field}_too_short")
    return clean[:max_chars]


def _clean_url(value: str) -> str:
    clean = _WHITESPACE.sub("", value.strip())
    if not clean.startswith("https://"):
        raise ValueError("public_source_url_must_be_https")
    return clean[:500]


def _fit(text: str, *, max_chars: int) -> str:
    clean = text.strip()
    if len(clean) <= max_chars:
        return clean
    suffix = "..."
    return clean[: max(0, max_chars - len(suffix))].rstrip() + suffix
