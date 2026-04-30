"""Dream Mode cost cap service with pessimistic row locking.

Contract:
    await check_and_reserve(scope, scope_key, amount_usd) -> CapResult

Uses SELECT ... FOR UPDATE inside a transaction to prevent TOCTOU races
when multiple concurrent steps check budget at the same time.

Windows:
    per_step:       single step (no persistent counter, checked inline)
    per_session:    keyed by goal_id, window = session start to now
    per_night:      keyed by date (YYYY-MM-DD), 23:30 to 04:00 next day
    per_week:       keyed by ISO week, 7-day rolling
    per_model_day:  keyed by provider+date
"""

import asyncpg
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class CapResult:
    allowed: bool
    scope: str
    scope_key: str
    spent_usd: Decimal
    limit_usd: Decimal
    remaining_usd: Decimal
    reason: str


class DreamCostCapService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def get_limit(self, scope: str) -> Decimal:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('rls.role', 'platform_admin', true)"
                )
                row = await conn.fetchrow(
                    "SELECT limit_usd FROM alpha_dream_cost_caps WHERE scope = $1",
                    scope,
                )
        if not row:
            raise ValueError(f"No cap configured for scope={scope}")
        return Decimal(str(row["limit_usd"]))

    def _window(self, scope: str, now: datetime) -> tuple[datetime, datetime]:
        if scope == "per_night":
            # 23:30 today to 04:00 tomorrow
            if now.hour < 12:
                start = (now - timedelta(days=1)).replace(
                    hour=23, minute=30, second=0, microsecond=0
                )
                end = now.replace(hour=4, minute=0, second=0, microsecond=0)
            else:
                start = now.replace(hour=23, minute=30, second=0, microsecond=0)
                end = (now + timedelta(days=1)).replace(
                    hour=4, minute=0, second=0, microsecond=0
                )
            return start, end
        if scope == "per_week":
            start = (now - timedelta(days=7)).replace(microsecond=0)
            end = now.replace(microsecond=0)
            return start, end
        if scope == "per_model_day":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            return start, end
        if scope == "per_session":
            # Sessions cap by scope_key (goal_id) — window is effectively open
            start = datetime(2020, 1, 1, tzinfo=timezone.utc)
            end = datetime(2100, 1, 1, tzinfo=timezone.utc)
            return start, end
        raise ValueError(f"Unsupported scope for windowing: {scope}")

    async def check_and_reserve(
        self,
        scope: str,
        scope_key: str,
        amount_usd: Decimal,
        now: Optional[datetime] = None,
    ) -> CapResult:
        """Check budget and atomically increment counter. Pessimistic lock.

        Returns ALLOWED CapResult if spend + amount <= limit, else BLOCKED.
        If ALLOWED, counter is already incremented — caller does not need to update.
        If BLOCKED, counter unchanged.
        """
        now = now or datetime.now(timezone.utc)
        limit = await self.get_limit(scope)

        # per_step is stateless
        if scope == "per_step":
            if amount_usd <= limit:
                return CapResult(
                    allowed=True,
                    scope=scope,
                    scope_key=scope_key,
                    spent_usd=amount_usd,
                    limit_usd=limit,
                    remaining_usd=limit - amount_usd,
                    reason="per_step OK",
                )
            return CapResult(
                allowed=False,
                scope=scope,
                scope_key=scope_key,
                spent_usd=amount_usd,
                limit_usd=limit,
                remaining_usd=Decimal(0),
                reason=f"per_step exceeds cap: {amount_usd} > {limit}",
            )

        window_start, window_end = self._window(scope, now)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('rls.role', 'platform_admin', true)"
                )

                # INSERT ON CONFLICT DO NOTHING then SELECT FOR UPDATE
                await conn.execute(
                    """
                    INSERT INTO alpha_dream_cost_counters
                        (scope, scope_key, window_start, window_end, spent_usd)
                    VALUES ($1, $2, $3, $4, 0)
                    ON CONFLICT (scope, scope_key, window_start) DO NOTHING
                    """,
                    scope,
                    scope_key,
                    window_start,
                    window_end,
                )

                row = await conn.fetchrow(
                    """
                    SELECT id, spent_usd FROM alpha_dream_cost_counters
                    WHERE scope = $1 AND scope_key = $2 AND window_start = $3
                    FOR UPDATE
                    """,
                    scope,
                    scope_key,
                    window_start,
                )

                spent = Decimal(str(row["spent_usd"]))
                new_total = spent + amount_usd

                if new_total > limit:
                    return CapResult(
                        allowed=False,
                        scope=scope,
                        scope_key=scope_key,
                        spent_usd=spent,
                        limit_usd=limit,
                        remaining_usd=max(Decimal(0), limit - spent),
                        reason=f"{scope} cap exceeded: {spent} + {amount_usd} > {limit}",
                    )

                await conn.execute(
                    """
                    UPDATE alpha_dream_cost_counters
                    SET spent_usd = $1, updated_at = now()
                    WHERE id = $2
                    """,
                    new_total,
                    row["id"],
                )

                return CapResult(
                    allowed=True,
                    scope=scope,
                    scope_key=scope_key,
                    spent_usd=new_total,
                    limit_usd=limit,
                    remaining_usd=limit - new_total,
                    reason="reserved",
                )
