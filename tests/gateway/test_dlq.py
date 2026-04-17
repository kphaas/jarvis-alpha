"""Unit tests for DeadLetterQueue — FIFO, eviction, flush, persistence."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from gateway.resilience.dlq import DeadLetterQueue


@pytest.fixture
async def dlq(tmp_path):
    db = tmp_path / "test_dlq.db"
    q = DeadLetterQueue(db_path=db, queue_name="test_queue", max_size=3)
    yield q


async def test_enqueue_and_drain(dlq):
    id1 = await dlq.enqueue({"goal": "one"}, reason="test")
    id2 = await dlq.enqueue({"goal": "two"}, reason="test")
    items = await dlq.drain(limit=10)
    assert len(items) == 2
    assert items[0].payload == {"goal": "one"}
    assert items[1].payload == {"goal": "two"}
    assert items[0].id == id1
    assert items[1].id == id2


async def test_fifo_eviction_fires_callback(tmp_path):
    evicted = []

    async def on_evict(item):
        evicted.append(item)

    db = tmp_path / "test_evict.db"
    q = DeadLetterQueue(db_path=db, queue_name="q1", max_size=2, on_evict=on_evict)

    await q.enqueue({"goal": "a"}, reason="brain_down")
    await q.enqueue({"goal": "b"}, reason="brain_down")
    await q.enqueue({"goal": "c"}, reason="brain_down")

    size = await q.size()
    assert size == 2
    assert len(evicted) == 1
    assert evicted[0]["payload"] == {"goal": "a"}


async def test_mark_flushed_removes_items(dlq):
    id1 = await dlq.enqueue({"goal": "one"}, reason="t")
    id2 = await dlq.enqueue({"goal": "two"}, reason="t")
    removed = await dlq.mark_flushed([id1])
    assert removed == 1
    remaining = await dlq.drain(10)
    assert len(remaining) == 1
    assert remaining[0].id == id2


async def test_bump_attempts(dlq):
    id1 = await dlq.enqueue({"goal": "one"}, reason="t")
    await dlq.bump_attempts([id1])
    await dlq.bump_attempts([id1])
    items = await dlq.drain(10)
    assert items[0].attempts == 2


async def test_queue_isolation(tmp_path):
    db = tmp_path / "shared.db"
    q1 = DeadLetterQueue(db_path=db, queue_name="queue_a", max_size=100)
    q2 = DeadLetterQueue(db_path=db, queue_name="queue_b", max_size=100)
    await q1.enqueue({"x": 1}, reason="t")
    await q2.enqueue({"x": 2}, reason="t")
    a_items = await q1.drain(10)
    b_items = await q2.drain(10)
    assert len(a_items) == 1
    assert len(b_items) == 1
    assert a_items[0].payload == {"x": 1}
    assert b_items[0].payload == {"x": 2}


async def test_persistence_across_instances(tmp_path):
    db = tmp_path / "persist.db"
    q1 = DeadLetterQueue(db_path=db, queue_name="q", max_size=100)
    await q1.enqueue({"goal": "persist me"}, reason="t")

    q2 = DeadLetterQueue(db_path=db, queue_name="q", max_size=100)
    items = await q2.drain(10)
    assert len(items) == 1
    assert items[0].payload == {"goal": "persist me"}


async def test_drain_does_not_delete(dlq):
    await dlq.enqueue({"x": 1}, reason="t")
    await dlq.drain(10)
    again = await dlq.drain(10)
    assert len(again) == 1


async def test_empty_queue(dlq):
    items = await dlq.drain(10)
    assert items == []
    size = await dlq.size()
    assert size == 0
