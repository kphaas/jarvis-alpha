from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from brain.services.family_school_client import (
    FamilySchoolClient,
    FamilySchoolEmailRule,
)
from brain.services.gmail_client import GmailMessage

DEFAULT_SCHOOL_QUERY = '("Mount Pisgah" OR "MPCS" OR "Pisgah") newer_than:21d'
DEFAULT_LOOKBACK_DAYS = 1


class MessageClient(Protocol):
    async def list_message_ids(
        self, query: str, max_results: int = 25
    ) -> list[str]: ...

    async def get_message(self, message_id: str) -> GmailMessage: ...


@dataclass(frozen=True)
class SchoolEmailScanRule:
    id: str | None
    child_member_id: str | None
    child_name: str | None
    label: str
    sender_email: str
    rule_type: str
    query: str
    trusted_sender: bool


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _lookback_days() -> int:
    return max(1, _int_env("ALPHA_SCHOOL_EMAIL_LOOKBACK_DAYS", DEFAULT_LOOKBACK_DAYS))


def current_lookback_days() -> int:
    return _lookback_days()


def _sender_query(sender: str, lookback_days: int) -> str:
    value = sender.strip().lower()
    if "@" in value and not value.startswith("@"):
        sender_filter = f"from:{value}"
    else:
        sender_filter = f"from:({value.lstrip('@')})"
    return f"{sender_filter} newer_than:{lookback_days}d"


def _rule_from_family(
    rule: FamilySchoolEmailRule,
    *,
    lookback_days: int,
) -> SchoolEmailScanRule:
    return SchoolEmailScanRule(
        id=rule.id,
        child_member_id=rule.child_member_id,
        child_name=rule.child_name,
        label=rule.label,
        sender_email=rule.sender_email,
        rule_type=rule.rule_type,
        query=_sender_query(rule.sender_email, lookback_days),
        trusted_sender=True,
    )


async def scan_rules(
    *,
    query: str | None,
    family_client: FamilySchoolClient,
) -> list[SchoolEmailScanRule]:
    if query:
        return [
            SchoolEmailScanRule(
                id=None,
                child_member_id=None,
                child_name=None,
                label="Manual scan",
                sender_email="",
                rule_type="manual",
                query=query,
                trusted_sender=False,
            )
        ]

    lookback_days = _lookback_days()
    rules = [
        _rule_from_family(rule, lookback_days=lookback_days)
        for rule in await family_client.active_rules()
    ]
    if rules:
        return rules

    if (
        os.environ.get("ALPHA_SCHOOL_EMAIL_ALLOW_LEGACY_QUERY", "false").lower()
        == "true"
    ):
        legacy_query = os.environ.get("ALPHA_SCHOOL_EMAIL_QUERY", DEFAULT_SCHOOL_QUERY)
        return [
            SchoolEmailScanRule(
                id=None,
                child_member_id=None,
                child_name=None,
                label="Legacy Mount Pisgah scan",
                sender_email="",
                rule_type="legacy",
                query=legacy_query,
                trusted_sender=False,
            )
        ]
    return []


async def message_rule_map(
    *,
    gmail: MessageClient,
    rules: list[SchoolEmailScanRule],
    max_results: int,
) -> tuple[dict[str, list[SchoolEmailScanRule]], int]:
    message_rules: dict[str, list[SchoolEmailScanRule]] = {}
    rules_by_query: dict[str, list[SchoolEmailScanRule]] = {}
    for rule in rules:
        rules_by_query.setdefault(rule.query, []).append(rule)

    queries_run = 0
    for query, query_rules in rules_by_query.items():
        queries_run += 1
        for gmail_message_id in await gmail.list_message_ids(
            query,
            max_results=max_results,
        ):
            message_rules.setdefault(gmail_message_id, []).extend(query_rules)
    return message_rules, queries_run


def dedupe_rules(rules: list[SchoolEmailScanRule]) -> list[SchoolEmailScanRule]:
    deduped: dict[str, SchoolEmailScanRule] = {}
    for rule in rules:
        key = rule.child_member_id or rule.query
        deduped.setdefault(key, rule)
    return list(deduped.values())
