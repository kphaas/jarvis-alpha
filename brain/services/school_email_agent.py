from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from brain.db.pool import get_pool
from brain.services.family_school_client import FamilySchoolClient
from brain.services.gmail_client import GmailClient
from brain.services.school_email_bridge import (
    apply_rule_context,
    import_action,
    import_event,
)
from brain.services.school_email_parser import extract_school_items
from brain.services.school_email_repository import (
    message_exists,
    record_action_candidate,
    record_event_candidate,
    record_message,
)
from brain.services.school_email_rules import (
    MessageClient,
    dedupe_rules,
    message_rule_map,
    scan_rules,
)


@dataclass(frozen=True)
class SchoolEmailScanResult:
    messages_seen: int
    messages_new: int
    candidates_created: int
    candidates_existing: int
    event_candidates_created: int
    event_candidates_existing: int
    action_candidates_created: int
    action_candidates_existing: int
    events_imported: int
    actions_imported: int
    import_errors: int
    rules_loaded: int
    queries_run: int


@dataclass
class _Counters:
    messages_new: int = 0
    event_candidates_created: int = 0
    event_candidates_existing: int = 0
    action_candidates_created: int = 0
    action_candidates_existing: int = 0
    events_imported: int = 0
    actions_imported: int = 0
    import_errors: int = 0

    @property
    def candidates_created(self) -> int:
        return self.event_candidates_created + self.action_candidates_created

    @property
    def candidates_existing(self) -> int:
        return self.event_candidates_existing + self.action_candidates_existing


async def scan_school_email(
    *,
    client: MessageClient | None = None,
    family_client: FamilySchoolClient | None = None,
    query: str | None = None,
    max_results: int = 25,
    anchor: date | None = None,
    import_to_family: bool = True,
) -> SchoolEmailScanResult:
    gmail = client or GmailClient()
    family = family_client or FamilySchoolClient()
    rules = await scan_rules(query=query, family_client=family)
    message_rules, queries_run = await message_rule_map(
        gmail=gmail,
        rules=rules,
        max_results=max_results,
    )

    counters = _Counters()
    pool = get_pool()
    async with pool.acquire() as conn:
        for gmail_message_id, matched_rules in message_rules.items():
            unique_rules = dedupe_rules(matched_rules)
            existed = await message_exists(conn, gmail_message_id)
            message = await gmail.get_message(gmail_message_id)
            counters.messages_new += int(not existed)
            message_row_id = await record_message(conn, message, unique_rules[0])
            extraction = await extract_school_items(
                message,
                anchor=anchor,
                trusted_sender=any(rule.trusted_sender for rule in unique_rules),
            )
            for rule in unique_rules:
                await _persist_rule_items(
                    conn=conn,
                    family=family,
                    message=message,
                    message_row_id=message_row_id,
                    rule=rule,
                    extraction=extraction,
                    counters=counters,
                    import_to_family=import_to_family,
                )

    return SchoolEmailScanResult(
        messages_seen=len(message_rules),
        messages_new=counters.messages_new,
        candidates_created=counters.candidates_created,
        candidates_existing=counters.candidates_existing,
        event_candidates_created=counters.event_candidates_created,
        event_candidates_existing=counters.event_candidates_existing,
        action_candidates_created=counters.action_candidates_created,
        action_candidates_existing=counters.action_candidates_existing,
        events_imported=counters.events_imported,
        actions_imported=counters.actions_imported,
        import_errors=counters.import_errors,
        rules_loaded=len(rules),
        queries_run=queries_run,
    )


async def _persist_rule_items(
    *,
    conn,
    family: FamilySchoolClient,
    message,
    message_row_id: str,
    rule,
    extraction,
    counters: _Counters,
    import_to_family: bool,
) -> None:
    events, actions = apply_rule_context(extraction, rule)
    for event in events:
        persisted = await record_event_candidate(
            conn,
            message_row_id,
            message.gmail_message_id,
            event,
        )
        counters.event_candidates_created += int(persisted.created)
        counters.event_candidates_existing += int(not persisted.created)
        if import_to_family:
            try:
                imported = await import_event(
                    conn,
                    family,
                    persisted=persisted,
                    message=message,
                    candidate=event,
                    rule=rule,
                )
            except Exception:
                counters.import_errors += 1
            else:
                counters.events_imported += int(imported)
    for action in actions:
        persisted = await record_action_candidate(
            conn,
            message_row_id,
            message.gmail_message_id,
            action,
        )
        counters.action_candidates_created += int(persisted.created)
        counters.action_candidates_existing += int(not persisted.created)
        if import_to_family:
            try:
                imported = await import_action(
                    conn,
                    family,
                    persisted=persisted,
                    message=message,
                    candidate=action,
                    rule=rule,
                )
            except Exception:
                counters.import_errors += 1
            else:
                counters.actions_imported += int(imported)
