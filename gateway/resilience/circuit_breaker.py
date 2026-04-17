"""Hystrix-style circuit breaker.

Three states (CLOSED → OPEN → HALF_OPEN → CLOSED):

    CLOSED     normal operation — calls pass through
    OPEN       dependency failing — short-circuit with CircuitOpenError
    HALF_OPEN  probing — next call is a test; success→CLOSED, failure→OPEN

Thread-safe via asyncio.Lock. Time-based, no external clock dependency.

Usage:
    breaker = CircuitBreaker(name="brain_planner", failure_threshold=3,
                             window_seconds=60, open_seconds=300)
    try:
        result = await breaker.call(lambda: some_async_call())
    except CircuitOpenError:
        # route to fallback / DLQ
        ...
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when a call is short-circuited because the breaker is OPEN."""

    def __init__(self, name: str, open_since: float):
        self.name = name
        self.open_since = open_since
        super().__init__(f"Circuit '{name}' is OPEN since t={open_since:.0f}")


@dataclass
class CircuitSnapshot:
    name: str
    state: CircuitState
    failure_count: int
    opened_at: float
    last_failure_at: float
    last_success_at: float


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        window_seconds: float = 60.0,
        open_seconds: float = 300.0,
    ):
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        self._name = name
        self._failure_threshold = failure_threshold
        self._window = window_seconds
        self._open_duration = open_seconds
        self._state = CircuitState.CLOSED
        self._failures: list[float] = []
        self._opened_at: float = 0.0
        self._last_failure_at: float = 0.0
        self._last_success_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return self._name

    async def _transition_if_needed(self, now: float) -> None:
        if self._state == CircuitState.OPEN:
            if now - self._opened_at >= self._open_duration:
                self._state = CircuitState.HALF_OPEN
                log.info("circuit[%s] OPEN -> HALF_OPEN after cooldown", self._name)

    def _prune_window(self, now: float) -> None:
        cutoff = now - self._window
        self._failures = [t for t in self._failures if t >= cutoff]

    async def _record_success(self, now: float) -> None:
        self._last_success_at = now
        if self._state == CircuitState.HALF_OPEN:
            log.info("circuit[%s] HALF_OPEN -> CLOSED (probe success)", self._name)
            self._state = CircuitState.CLOSED
            self._failures = []
            self._opened_at = 0.0

    async def _record_failure(self, now: float) -> None:
        self._last_failure_at = now
        self._failures.append(now)
        self._prune_window(now)

        if self._state == CircuitState.HALF_OPEN:
            log.warning("circuit[%s] HALF_OPEN -> OPEN (probe failed)", self._name)
            self._state = CircuitState.OPEN
            self._opened_at = now
            return

        if len(self._failures) >= self._failure_threshold:
            log.warning(
                "circuit[%s] CLOSED -> OPEN (%d failures in %.0fs window)",
                self._name,
                len(self._failures),
                self._window,
            )
            self._state = CircuitState.OPEN
            self._opened_at = now

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Execute fn() under circuit breaker protection."""
        now = time.monotonic()
        async with self._lock:
            await self._transition_if_needed(now)
            if self._state == CircuitState.OPEN:
                raise CircuitOpenError(self._name, self._opened_at)

        try:
            result = await fn()
        except Exception:
            async with self._lock:
                await self._record_failure(time.monotonic())
            raise
        else:
            async with self._lock:
                await self._record_success(time.monotonic())
            return result

    async def snapshot(self) -> CircuitSnapshot:
        async with self._lock:
            await self._transition_if_needed(time.monotonic())
            return CircuitSnapshot(
                name=self._name,
                state=self._state,
                failure_count=len(self._failures),
                opened_at=self._opened_at,
                last_failure_at=self._last_failure_at,
                last_success_at=self._last_success_at,
            )

    async def force_open(self) -> None:
        """Manual trip — ops override for testing or emergency."""
        async with self._lock:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            log.warning("circuit[%s] FORCED OPEN", self._name)

    async def force_close(self) -> None:
        """Manual reset — ops override."""
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failures = []
            self._opened_at = 0.0
            log.info("circuit[%s] FORCED CLOSED", self._name)
