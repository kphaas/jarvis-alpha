"""Dream Mode Invariant Checker — allowlist-first HARD BLOCK layer.

Contract:
    check(proposed_change: ProposedChange) -> CheckResult

ProposedChange = dict with keys: path, diff, dream_step_id, goal_id
CheckResult = dataclass(allowed: bool, reason: str, rule: str)

Blocks applied in order (fail-fast):
    R1: Path must match an enabled allowed_path glob (allowlist)
    R2: No hardcoded IPv4/IPv6 addresses in diff
    R3: No secrets (ANTHROPIC_API_KEY=, PUSHOVER_, password= patterns)
    R4: No path traversal (..)
    R5: No writes under pki/, .secrets, migrations/, *.plist
    R6: No outbound network calls outside allowlist (requests.get, httpx, fetch, curl)
    R7: No new pip/npm imports not already in requirements
    R8: No SQL strings without params (crude check — flags f-string / %-format with SELECT/INSERT/UPDATE/DELETE)
    R9: No modifications to brain/middleware/*, scripts/service_identity.py

Every block writes a row to alpha_dream_blocked_writes.
"""

import asyncpg
import fnmatch
import logging
import re
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# Denylist paths — absolute blocks regardless of allowlist
DENY_PATH_PATTERNS = [
    "*pki/*",
    "*.secrets*",
    "*migrations/*",
    "*.plist",
    "brain/middleware/*",
    "scripts/service_identity.py",
]

# Secret patterns
SECRET_PATTERNS = [
    re.compile(r"ANTHROPIC_API_KEY\s*=\s*[\"']?sk-", re.IGNORECASE),
    re.compile(r"PUSHOVER_[A-Z_]+\s*=\s*[\"']?[a-z0-9]{20,}", re.IGNORECASE),
    re.compile(r"password\s*=\s*[\"'][^\"']{4,}", re.IGNORECASE),
    re.compile(r"api[_-]?key\s*=\s*[\"'][^\"']{10,}", re.IGNORECASE),
    re.compile(r"bearer\s+[a-z0-9_\-\.]{20,}", re.IGNORECASE),
]

# IP address patterns
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
IPV6_PATTERN = re.compile(r"\b(?:[a-f0-9]{1,4}:){7}[a-f0-9]{1,4}\b", re.IGNORECASE)

# Network call patterns (outside allowlist)
NETWORK_PATTERNS = [
    re.compile(r"requests\.(get|post|put|delete|patch)", re.IGNORECASE),
    re.compile(r"httpx\.(get|post|put|delete|patch|Client|AsyncClient)", re.IGNORECASE),
    re.compile(r"\bfetch\s*\(", re.IGNORECASE),
    re.compile(r"\bcurl\s", re.IGNORECASE),
    re.compile(r"urllib\.request", re.IGNORECASE),
]

# SQL injection crude check
SQL_FSTRING_PATTERN = re.compile(
    r"(f[\"'].*(SELECT|INSERT|UPDATE|DELETE).*\{)|(%\s*\(.*\).*(SELECT|INSERT|UPDATE|DELETE))",
    re.IGNORECASE,
)


@dataclass
class CheckResult:
    allowed: bool
    reason: str
    rule: str


@dataclass
class ProposedChange:
    path: str
    diff: str
    dream_step_id: Optional[str] = None
    goal_id: Optional[str] = None


class DreamInvariantChecker:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool
        self._allowed_cache: list[str] = []
        self._cache_loaded = False

    async def _load_allowlist(self) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('jarvis.role', 'platform_admin', true)"
                )
                rows = await conn.fetch(
                    "SELECT path_glob FROM alpha_dream_allowed_paths WHERE enabled = TRUE"
                )
        self._allowed_cache = [r["path_glob"] for r in rows]
        self._cache_loaded = True
        log.info(
            "dream_invariant_checker: loaded %d allowed paths", len(self._allowed_cache)
        )

    async def refresh_allowlist(self) -> None:
        """Call after SQL updates to alpha_dream_allowed_paths."""
        await self._load_allowlist()

    async def check(self, change: ProposedChange) -> CheckResult:
        if not self._cache_loaded:
            await self._load_allowlist()

        # R5 — Denylist (absolute)
        for deny in DENY_PATH_PATTERNS:
            if fnmatch.fnmatch(change.path, deny):
                return await self._block(
                    change, f"Path matches denylist pattern: {deny}", "R5_DENYLIST"
                )

        # R9 — Specific crown-jewel denies (belt-and-suspenders)
        if change.path.startswith("brain/middleware/"):
            return await self._block(
                change, "Cannot modify brain/middleware/*", "R9_MIDDLEWARE"
            )
        if change.path == "scripts/service_identity.py":
            return await self._block(
                change, "Cannot modify service_identity.py", "R9_SCOPES"
            )

        # R1 — Allowlist
        if not any(fnmatch.fnmatch(change.path, glob) for glob in self._allowed_cache):
            return await self._block(
                change,
                f"Path not in allowlist: {change.path}",
                "R1_NOT_ALLOWED",
            )

        # R4 — Path traversal
        if ".." in change.path:
            return await self._block(
                change, "Path contains .. (traversal)", "R4_TRAVERSAL"
            )

        # R2 — Hardcoded IPs
        if IPV4_PATTERN.search(change.diff) or IPV6_PATTERN.search(change.diff):
            return await self._block(
                change,
                "Diff contains hardcoded IP address — use node_addresses.py",
                "R2_HARDCODED_IP",
            )

        # R3 — Secrets
        for pattern in SECRET_PATTERNS:
            if pattern.search(change.diff):
                return await self._block(
                    change,
                    "Diff contains secret pattern — use get_secret()",
                    "R3_SECRET",
                )

        # R6 — Network calls
        for pattern in NETWORK_PATTERNS:
            if pattern.search(change.diff):
                return await self._block(
                    change,
                    "Diff contains outbound network call — must go via Gateway adapter",
                    "R6_NETWORK",
                )

        # R7 — New imports (crude: flags any new 'import' or 'from X import' lines)
        # Note: real dependency check done at Brain level against requirements.txt
        # Here we only flag suspicious third-party import names
        suspicious_imports = re.findall(
            r"^(?:\+\s*)?(?:from\s+(\w+)|import\s+(\w+))", change.diff, re.MULTILINE
        )
        blocked_libs = {"subprocess32", "paramiko", "fabric", "pyautogui", "keyring"}
        for mod1, mod2 in suspicious_imports:
            mod = mod1 or mod2
            if mod in blocked_libs:
                return await self._block(
                    change,
                    f"Diff imports blocked library: {mod}",
                    "R7_BLOCKED_IMPORT",
                )

        # R8 — SQL f-strings
        if SQL_FSTRING_PATTERN.search(change.diff):
            return await self._block(
                change,
                "Diff contains SQL with f-string or %-format — use parameterized queries",
                "R8_SQL_INJECTION",
            )

        return CheckResult(allowed=True, reason="All invariants passed", rule="OK")

    async def _block(
        self, change: ProposedChange, reason: str, rule: str
    ) -> CheckResult:
        try:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "SELECT set_config('jarvis.role', 'platform_admin', true)"
                    )
                    await conn.execute(
                        """
                        INSERT INTO alpha_dream_blocked_writes
                            (dream_step_id, goal_id, attempted_path, attempted_diff,
                             block_reason, block_rule)
                        VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6)
                        """,
                        change.dream_step_id,
                        change.goal_id,
                        change.path,
                        change.diff[:10000],  # cap stored diff at 10KB
                        reason,
                        rule,
                    )
        except Exception as e:
            log.error("dream_invariant_checker: failed to log block: %s", e)

        log.warning(
            "dream_invariant_checker BLOCK path=%s rule=%s reason=%s",
            change.path,
            rule,
            reason,
        )
        return CheckResult(allowed=False, reason=reason, rule=rule)
