"""Unit tests for DreamInvariantChecker — covers R1 through R9."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from brain.services.dream_invariant_checker import (
    DreamInvariantChecker,
    ProposedChange,
)


@pytest.fixture
def mock_pool():
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            {"path_glob": "brain/services/*.py"},
            {"path_glob": "tests/**/*.py"},
            {"path_glob": "tests/**/*.sql"},
        ]
    )
    conn.execute = AsyncMock()
    conn.transaction = MagicMock()
    conn.transaction.return_value.__aenter__ = AsyncMock()
    conn.transaction.return_value.__aexit__ = AsyncMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock()
    return pool


@pytest.fixture
async def checker(mock_pool):
    c = DreamInvariantChecker(mock_pool)
    await c._load_allowlist()
    return c


@pytest.mark.asyncio
async def test_allow_valid_service_write(checker):
    change = ProposedChange(
        path="brain/services/new_thing.py",
        diff="def hello():\n    return 'world'\n",
    )
    result = await checker.check(change)
    assert result.allowed is True
    assert result.rule == "OK"


@pytest.mark.asyncio
async def test_r1_block_not_in_allowlist(checker):
    change = ProposedChange(
        path="brain/routes/new_route.py",
        diff="def foo(): pass",
    )
    result = await checker.check(change)
    assert result.allowed is False
    assert result.rule == "R1_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_r2_block_hardcoded_ipv4(checker):
    change = ProposedChange(
        path="brain/services/x.py",
        diff="BRAIN = '100.64.166.22'",
    )
    result = await checker.check(change)
    assert result.allowed is False
    assert result.rule == "R2_HARDCODED_IP"


@pytest.mark.asyncio
async def test_r3_block_api_key(checker):
    change = ProposedChange(
        path="brain/services/x.py",
        diff='ANTHROPIC_API_KEY = "sk-ant-api03-xxxxxxxxxx"',
    )
    result = await checker.check(change)
    assert result.allowed is False
    assert result.rule == "R3_SECRET"


@pytest.mark.asyncio
async def test_r3_block_password(checker):
    change = ProposedChange(
        path="brain/services/x.py",
        diff='password = "hunter2hunter2"',
    )
    result = await checker.check(change)
    assert result.allowed is False
    assert result.rule == "R3_SECRET"


@pytest.mark.asyncio
async def test_r4_block_traversal(checker):
    change = ProposedChange(
        path="brain/services/../middleware/evil.py",
        diff="x = 1",
    )
    result = await checker.check(change)
    assert result.allowed is False
    # R5 catches middleware first; either is acceptable
    assert result.rule in ("R5_DENYLIST", "R4_TRAVERSAL", "R9_MIDDLEWARE")


@pytest.mark.asyncio
async def test_r5_block_pki(checker):
    change = ProposedChange(
        path="brain/pki/evil_key.pem",
        diff="-----BEGIN PRIVATE KEY-----",
    )
    result = await checker.check(change)
    assert result.allowed is False
    assert result.rule == "R5_DENYLIST"


@pytest.mark.asyncio
async def test_r5_block_migration(checker):
    change = ProposedChange(
        path="brain/db/migrations/20260418_bad.sql",
        diff="DROP TABLE users;",
    )
    result = await checker.check(change)
    assert result.allowed is False
    assert result.rule == "R5_DENYLIST"


@pytest.mark.asyncio
async def test_r5_block_plist(checker):
    change = ProposedChange(
        path="launchagents/com.evil.plist",
        diff="<plist></plist>",
    )
    result = await checker.check(change)
    assert result.allowed is False
    assert result.rule == "R5_DENYLIST"


@pytest.mark.asyncio
async def test_r6_block_requests_call(checker):
    change = ProposedChange(
        path="brain/services/x.py",
        diff="import requests\nrequests.get('https://evil.com')",
    )
    result = await checker.check(change)
    assert result.allowed is False
    assert result.rule == "R6_NETWORK"


@pytest.mark.asyncio
async def test_r6_block_httpx_call(checker):
    change = ProposedChange(
        path="brain/services/x.py",
        diff="import httpx\nhttpx.AsyncClient()",
    )
    result = await checker.check(change)
    assert result.allowed is False
    assert result.rule == "R6_NETWORK"


@pytest.mark.asyncio
async def test_r7_block_blocked_import(checker):
    change = ProposedChange(
        path="brain/services/x.py",
        diff="+import paramiko\n+ssh = paramiko.SSHClient()",
    )
    result = await checker.check(change)
    assert result.allowed is False
    assert result.rule == "R7_BLOCKED_IMPORT"


@pytest.mark.asyncio
async def test_r8_block_sql_fstring(checker):
    change = ProposedChange(
        path="brain/services/x.py",
        diff='query = f"SELECT * FROM users WHERE id = {user_id}"',
    )
    result = await checker.check(change)
    assert result.allowed is False
    assert result.rule == "R8_SQL_INJECTION"


@pytest.mark.asyncio
async def test_r9_block_middleware(checker):
    change = ProposedChange(
        path="brain/middleware/jwt_auth.py",
        diff="def validate(): return True",
    )
    result = await checker.check(change)
    assert result.allowed is False
    assert result.rule in ("R5_DENYLIST", "R9_MIDDLEWARE")


@pytest.mark.asyncio
async def test_r9_block_service_identity(checker):
    change = ProposedChange(
        path="scripts/service_identity.py",
        diff="DEFAULT_SCOPES = ['*']",
    )
    result = await checker.check(change)
    assert result.allowed is False
    assert result.rule in ("R5_DENYLIST", "R9_SCOPES")


@pytest.mark.asyncio
async def test_allow_test_file(checker):
    change = ProposedChange(
        path="tests/services/test_new.py",
        diff="def test_foo():\n    assert 1 == 1\n",
    )
    result = await checker.check(change)
    assert result.allowed is True
