"""Unit tests for CircuitBreaker — state transitions, thresholds, probes."""

import asyncio
import pytest

from gateway.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)


async def _ok():
    return "ok"


async def _fail():
    raise RuntimeError("boom")


async def test_closed_initial_state():
    b = CircuitBreaker("t1", failure_threshold=3)
    snap = await b.snapshot()
    assert snap.state == CircuitState.CLOSED
    assert snap.failure_count == 0


async def test_success_keeps_closed():
    b = CircuitBreaker("t2")
    result = await b.call(_ok)
    assert result == "ok"
    snap = await b.snapshot()
    assert snap.state == CircuitState.CLOSED


async def test_threshold_opens_circuit():
    b = CircuitBreaker("t3", failure_threshold=3)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await b.call(_fail)
    snap = await b.snapshot()
    assert snap.state == CircuitState.OPEN


async def test_open_short_circuits_calls():
    b = CircuitBreaker("t4", failure_threshold=2)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await b.call(_fail)
    with pytest.raises(CircuitOpenError):
        await b.call(_ok)


async def test_open_transitions_to_half_open_after_cooldown():
    b = CircuitBreaker("t5", failure_threshold=1, open_seconds=0.1)
    with pytest.raises(RuntimeError):
        await b.call(_fail)
    await asyncio.sleep(0.15)
    snap = await b.snapshot()
    assert snap.state == CircuitState.HALF_OPEN


async def test_half_open_success_returns_to_closed():
    b = CircuitBreaker("t6", failure_threshold=1, open_seconds=0.1)
    with pytest.raises(RuntimeError):
        await b.call(_fail)
    await asyncio.sleep(0.15)
    result = await b.call(_ok)
    assert result == "ok"
    snap = await b.snapshot()
    assert snap.state == CircuitState.CLOSED


async def test_half_open_failure_reopens():
    b = CircuitBreaker("t7", failure_threshold=1, open_seconds=0.1)
    with pytest.raises(RuntimeError):
        await b.call(_fail)
    await asyncio.sleep(0.15)
    with pytest.raises(RuntimeError):
        await b.call(_fail)
    snap = await b.snapshot()
    assert snap.state == CircuitState.OPEN


async def test_window_prunes_old_failures():
    b = CircuitBreaker("t8", failure_threshold=3, window_seconds=0.1)
    with pytest.raises(RuntimeError):
        await b.call(_fail)
    with pytest.raises(RuntimeError):
        await b.call(_fail)
    await asyncio.sleep(0.15)
    with pytest.raises(RuntimeError):
        await b.call(_fail)
    snap = await b.snapshot()
    assert snap.state == CircuitState.CLOSED


async def test_force_open_and_close():
    b = CircuitBreaker("t9")
    await b.force_open()
    snap = await b.snapshot()
    assert snap.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        await b.call(_ok)
    await b.force_close()
    result = await b.call(_ok)
    assert result == "ok"


async def test_failure_threshold_validation():
    with pytest.raises(ValueError):
        CircuitBreaker("bad", failure_threshold=0)
