"""P4 removal control-plane status reader.

This module assembles hash-only, count-only readiness metadata for the privacy
console. It does not decrypt payloads or contact brokers, search providers, or
public-record systems.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg

from jarvis_common.logging_config import get_logger

logger = get_logger("privacy_scrub.removal_control")


@dataclass(frozen=True, slots=True)
class RemovalLane:
    code: str
    label: str
    status: str
    north_star: str
    current_state: str
    next_step: str
    evidence_key: str
    metric: int


@dataclass(frozen=True, slots=True)
class RemovalLens:
    code: str
    label: str
    status: str
    summary: str
    checkpoints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RemovalBenchmark:
    provider: str
    capability: str
    alpha_gap: str
    control: str


@dataclass(frozen=True, slots=True)
class RemovalControlCounts:
    targets_total: int
    broker_targets: int
    public_record_targets: int
    authorizations_active: int
    adapter_profiles: int
    adapter_profiles_recurring: int
    evidence_items: int
    monitor_runs: int
    monitor_runs_due: int
    search_deindex_items: int
    public_record_triage_items: int
    approved_actions_open: int
    approved_actions_terminal: int


@dataclass(frozen=True, slots=True)
class RemovalControlSummary:
    generated_at: datetime
    mode: str
    outbound_enabled: bool
    counts: RemovalControlCounts
    lanes: tuple[RemovalLane, ...]
    lenses: tuple[RemovalLens, ...]
    benchmarks: tuple[RemovalBenchmark, ...]


class PrivacyRemovalControlRepository:
    """Read P4 readiness metadata through an RLS-bound connection."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def summary(self) -> RemovalControlSummary:
        target_counts = await self._target_counts()
        authorizations_active = await self._count(
            "public.alpha_privacy_authorizations",
            "status = 'active'",
        )
        adapter_row = await self._conn.fetchrow(
            """
            SELECT
                COUNT(*)::INT AS total,
                COUNT(*) FILTER (WHERE supports_recurring_monitor)::INT AS recurring
            FROM public.alpha_privacy_adapter_profiles
            """
        )
        monitor_row = await self._conn.fetchrow(
            """
            SELECT
                COUNT(*)::INT AS total,
                COUNT(*) FILTER (
                    WHERE status = 'scheduled'
                      AND scheduled_for <= NOW()
                )::INT AS due
            FROM public.alpha_privacy_monitor_runs
            """
        )
        action_row = await self._conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE status IN ('approved', 'sent')
                )::INT AS open_count,
                COUNT(*) FILTER (
                    WHERE status IN ('confirmed', 'failed', 'rejected', 'expired')
                )::INT AS terminal_count
            FROM public.alpha_privacy_actions
            """
        )
        counts = RemovalControlCounts(
            targets_total=sum(target_counts.values()),
            broker_targets=target_counts.get("data_broker", 0),
            public_record_targets=target_counts.get("public_record", 0),
            authorizations_active=authorizations_active,
            adapter_profiles=int(adapter_row["total"] if adapter_row else 0),
            adapter_profiles_recurring=int(
                adapter_row["recurring"] if adapter_row else 0
            ),
            evidence_items=await self._count("public.alpha_privacy_evidence_items"),
            monitor_runs=int(monitor_row["total"] if monitor_row else 0),
            monitor_runs_due=int(monitor_row["due"] if monitor_row else 0),
            search_deindex_items=await self._count(
                "public.alpha_privacy_search_deindex_items"
            ),
            public_record_triage_items=await self._count(
                "public.alpha_privacy_public_record_triage"
            ),
            approved_actions_open=int(action_row["open_count"] if action_row else 0),
            approved_actions_terminal=int(
                action_row["terminal_count"] if action_row else 0
            ),
        )
        logger.info(
            "privacy_removal_control_summary targets=%d adapters=%d monitors=%d",
            counts.targets_total,
            counts.adapter_profiles,
            counts.monitor_runs,
        )
        return RemovalControlSummary(
            generated_at=datetime.now(UTC),
            mode="manual_control_plane",
            outbound_enabled=False,
            counts=counts,
            lanes=_lanes(counts),
            lenses=_lenses(counts),
            benchmarks=_benchmarks(),
        )

    async def _target_counts(self) -> dict[str, int]:
        rows = await self._conn.fetch(
            """
            SELECT category, COUNT(*)::INT AS count
            FROM public.alpha_privacy_targets_cache
            GROUP BY category
            """
        )
        return {str(row["category"]): int(row["count"]) for row in rows}

    async def _count(self, table: str, where: str | None = None) -> int:
        query = f"SELECT COUNT(*)::INT AS count FROM {table}"
        if where:
            query = f"{query} WHERE {where}"
        row = await self._conn.fetchrow(query)
        return int(row["count"] if row else 0)


def _lanes(counts: RemovalControlCounts) -> tuple[RemovalLane, ...]:
    return (
        RemovalLane(
            code="P4-A",
            label="Discovery coverage",
            status=_ready(counts.targets_total > 0),
            north_star="Broad broker and open-web review coverage",
            current_state=f"{counts.targets_total} local targets registered",
            next_step="Add approved source probes behind explicit outbound approval",
            evidence_key="target_registry",
            metric=counts.targets_total,
        ),
        RemovalLane(
            code="P4-B",
            label="Authorization vault",
            status=_ready(counts.authorizations_active > 0),
            north_star="Signed agent authorization before broker handling",
            current_state=f"{counts.authorizations_active} active authorizations",
            next_step="Capture encrypted signed authorization payloads per subject",
            evidence_key="authorization_payload_hash",
            metric=counts.authorizations_active,
        ),
        RemovalLane(
            code="P4-C",
            label="Broker adapters",
            status=_ready(counts.adapter_profiles > 0),
            north_star="Per-broker difficulty, SLA, and handoff rules",
            current_state=f"{counts.adapter_profiles} adapter profiles",
            next_step="Fill broker-specific instructions and compliance history",
            evidence_key="adapter_profile",
            metric=counts.adapter_profiles,
        ),
        RemovalLane(
            code="P4-D",
            label="Evidence dashboard",
            status=_ready(counts.evidence_items > 0),
            north_star="Reports with site detail, status, and proof hashes",
            current_state=f"{counts.evidence_items} evidence items",
            next_step="Attach before/after proof to each approved action",
            evidence_key="evidence_payload_hash",
            metric=counts.evidence_items,
        ),
        RemovalLane(
            code="P4-E",
            label="Recurring monitor",
            status=_ready(counts.monitor_runs > 0),
            north_star="Reliable recheck cadence for reappearing listings",
            current_state=f"{counts.monitor_runs} local monitor runs",
            next_step="Schedule approved recurrence after authorization is active",
            evidence_key="monitor_report_hash",
            metric=counts.monitor_runs_due,
        ),
        RemovalLane(
            code="P4-F",
            label="Search deindex",
            status=_ready(counts.search_deindex_items > 0),
            north_star="Separate search-result deindex path and follow-up",
            current_state=f"{counts.search_deindex_items} deindex candidates",
            next_step="Queue outdated-content and exposed-data review items",
            evidence_key="search_result_digest",
            metric=counts.search_deindex_items,
        ),
        RemovalLane(
            code="P4-G",
            label="Public-record triage",
            status=_ready(counts.public_record_triage_items > 0),
            north_star="Public-record copies separated from court/legal process",
            current_state=f"{counts.public_record_triage_items} triage items",
            next_step="Classify broker copies versus legal-review-only records",
            evidence_key="triage_payload_hash",
            metric=counts.public_record_triage_items,
        ),
    )


def _lenses(counts: RemovalControlCounts) -> tuple[RemovalLens, ...]:
    return (
        RemovalLens(
            code="product",
            label="Product coverage",
            status=_ready(counts.targets_total >= 1 and counts.adapter_profiles >= 1),
            summary="Coverage, adapters, and custom handling are visible in one console.",
            checkpoints=(
                f"{counts.broker_targets} broker targets",
                f"{counts.public_record_targets} public-record targets",
                f"{counts.adapter_profiles_recurring} recurring-capable profiles",
            ),
        ),
        RemovalLens(
            code="legal",
            label="Legal safety",
            status=_ready(counts.authorizations_active >= 1),
            summary="Sensitive action paths remain blocked until authorization exists.",
            checkpoints=(
                f"{counts.authorizations_active} active authorization records",
                "Public-record legal review is a separate lane",
                "Outbound work remains disabled",
            ),
        ),
        RemovalLens(
            code="security",
            label="Security/privacy",
            status="ready",
            summary="P4 storage uses RLS, encrypted payloads, and digest-only UI proof.",
            checkpoints=(
                "FORCE RLS tables",
                "No SQL decrypt helper",
                "Payload hashes instead of plaintext in the console",
            ),
        ),
        RemovalLens(
            code="operations",
            label="Operations/evidence",
            status=_ready(
                counts.evidence_items >= 1
                or counts.approved_actions_open >= 1
                or counts.approved_actions_terminal >= 1
            ),
            summary="Operator work is measurable through action state and evidence counts.",
            checkpoints=(
                f"{counts.approved_actions_open} open approved actions",
                f"{counts.approved_actions_terminal} terminal actions",
                f"{counts.evidence_items} evidence records",
            ),
        ),
    )


def _benchmarks() -> tuple[RemovalBenchmark, ...]:
    return (
        RemovalBenchmark(
            provider="Incogni",
            capability="Authorization plus broad broker coverage",
            alpha_gap="Signed authorization storage exists, but live broker coverage is still local-only.",
            control="P4-B and P4-C establish vault and adapter metadata.",
        ),
        RemovalBenchmark(
            provider="Incogni",
            capability="Recurring 60/90-day style follow-up",
            alpha_gap="Cadence is modeled locally; no scheduled outbound broker work is active.",
            control="P4-E stores recurrence metadata and due-state counts.",
        ),
        RemovalBenchmark(
            provider="DeleteMe",
            capability="Privacy reports with found, removed, and resurfaced status",
            alpha_gap="Reports are hash-only today and need before/after proof attachment.",
            control="P4-D adds evidence storage and dashboard counters.",
        ),
        RemovalBenchmark(
            provider="DeleteMe",
            capability="Custom removal help from the dashboard",
            alpha_gap="Custom/manual items need adapter profiles and approval handoff.",
            control="P4-C and P4-F separate custom broker and search-result work.",
        ),
    )


def _ready(condition: bool) -> str:
    return "ready" if condition else "needs_input"
