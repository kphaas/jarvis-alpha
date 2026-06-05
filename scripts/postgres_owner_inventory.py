#!/usr/bin/env python3
"""Read-only ownership inventory for the Alpha Postgres role split plan."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PSQL_BIN = "/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql"
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
    ".ruff_cache",
}
TEXT_SUFFIXES = {
    ".cfg",
    ".conf",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".sql",
    ".toml",
    ".tsx",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}
STATIC_SCAN_EXCLUDED_FILES = {
    "scripts/postgres_owner_inventory.py",
    "tests/test_postgres_owner_inventory.py",
}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class CatalogRow:
    kind: str
    name: str
    owner: str
    detail: dict[str, str | bool | int]


@dataclass(frozen=True)
class StaticReference:
    file: str
    line: int
    token: str
    text: str


@dataclass(frozen=True)
class Inventory:
    database: str
    generated_by: str
    rows: list[CatalogRow]
    static_references: list[StaticReference]
    summary: dict[str, int]


def run_psql(
    query: str,
    *,
    psql_bin: str,
    db: str,
    user: str,
    host: str,
    ssh_target: str | None = None,
    timeout: int = 45,
) -> CommandResult:
    psql_args = [
        psql_bin,
        "-h",
        host,
        "-U",
        user,
        "-d",
        db,
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-t",
        "-A",
        "-F",
        "|",
        "-c",
        query,
    ]
    if ssh_target:
        remote_command = (
            "set -a; "
            "source ~/jarvis/.secrets >/dev/null 2>&1 || true; "
            "set +a; "
            'if [ -n "${POSTGRES_PASSWORD:-}" ]; then '
            'export PGPASSWORD="$POSTGRES_PASSWORD"; '
            "fi; "
            f"{shlex.join(psql_args)}"
        )
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", ssh_target, remote_command],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)

    env = os.environ.copy()
    password = env.get("POSTGRES_PASSWORD") or env.get("PGPASSWORD")
    if password:
        env["PGPASSWORD"] = password
    proc = subprocess.run(
        psql_args,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )
    return CommandResult(proc.returncode, proc.stdout, proc.stderr)


def parse_rows(output: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in output.splitlines():
        clean = line.strip()
        if clean:
            rows.append([part.strip() for part in clean.split("|")])
    return rows


def _bool(value: str) -> bool:
    return value.lower() in {"t", "true", "1", "yes"}


def collect_catalog(
    *,
    psql_bin: str,
    db: str,
    user: str,
    host: str,
    ssh_target: str | None = None,
) -> list[CatalogRow]:
    queries: list[tuple[str, str]] = [
        (
            "database",
            """
SELECT 'database',
       d.datname,
       pg_get_userbyid(d.datdba),
       'allow_connections=' || d.datallowconn::text
FROM pg_database d
WHERE d.datname = current_database();
""".strip(),
        ),
        (
            "schema",
            """
SELECT 'schema',
       n.nspname,
       pg_get_userbyid(n.nspowner),
       'acl=' || COALESCE(array_to_string(n.nspacl, ','), '')
FROM pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
ORDER BY n.nspname;
""".strip(),
        ),
        (
            "relation",
            """
SELECT 'relation',
       n.nspname || '.' || c.relname,
       pg_get_userbyid(c.relowner),
       'relkind=' || c.relkind::text
         || ',rls=' || c.relrowsecurity::text
         || ',force_rls=' || c.relforcerowsecurity::text
         || ',policies=' || COALESCE(p.policy_count, 0)::text
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN (
    SELECT polrelid, COUNT(*) AS policy_count
    FROM pg_policy
    GROUP BY polrelid
) p ON p.polrelid = c.oid
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
ORDER BY n.nspname, c.relname;
""".strip(),
        ),
        (
            "function",
            """
SELECT 'function',
       n.nspname || '.' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')',
       pg_get_userbyid(p.proowner),
       'security_definer=' || p.prosecdef::text
         || ',volatile=' || p.provolatile::text
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
ORDER BY n.nspname, p.proname, pg_get_function_identity_arguments(p.oid);
""".strip(),
        ),
        (
            "extension",
            """
SELECT 'extension',
       e.extname,
       pg_get_userbyid(e.extowner),
       'schema=' || COALESCE(n.nspname, '')
FROM pg_extension e
LEFT JOIN pg_namespace n ON n.oid = e.extnamespace
ORDER BY e.extname;
""".strip(),
        ),
        (
            "role",
            """
SELECT 'role',
       r.rolname,
       r.rolname,
       'oid=' || r.oid::text
         || ',super=' || r.rolsuper::text
         || ',bypassrls=' || r.rolbypassrls::text
         || ',createdb=' || r.rolcreatedb::text
         || ',createrole=' || r.rolcreaterole::text
         || ',login=' || r.rolcanlogin::text
FROM pg_roles r
WHERE r.rolname LIKE 'jarvis%'
   OR r.rolsuper
ORDER BY r.rolname;
""".strip(),
        ),
    ]
    rows: list[CatalogRow] = []
    for expected_kind, query in queries:
        result = run_psql(
            query,
            psql_bin=psql_bin,
            db=db,
            user=user,
            host=host,
            ssh_target=ssh_target,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"{expected_kind} inventory query failed: "
                f"{(result.stderr or result.stdout).strip()}"
            )
        for parsed in parse_rows(result.stdout):
            if len(parsed) < 4:
                continue
            rows.append(
                CatalogRow(
                    kind=parsed[0],
                    name=parsed[1],
                    owner=parsed[2],
                    detail=parse_detail(parsed[3]),
                )
            )
    return rows


def parse_detail(raw: str) -> dict[str, str | bool | int]:
    detail: dict[str, str | bool | int] = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        clean_value = value.strip()
        if clean_value.lower() in {"true", "false", "t", "f"}:
            detail[key.strip()] = _bool(clean_value)
        elif clean_value.isdigit():
            detail[key.strip()] = int(clean_value)
        else:
            detail[key.strip()] = clean_value
    return detail


def should_scan(path: Path) -> bool:
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return False
    return path.is_file() and path.suffix in TEXT_SUFFIXES


def static_references(repo_root: Path) -> list[StaticReference]:
    tokens = ("-U jarvisbrain", "OWNER TO jarvisbrain", "TO jarvisbrain", "jarvisbrain")
    refs: list[StaticReference] = []
    for path in sorted(repo_root.rglob("*")):
        relative_parts = path.relative_to(repo_root).parts
        if len(relative_parts) >= 2 and relative_parts[:2] == ("docs", "reports"):
            continue
        rel = path.relative_to(repo_root).as_posix()
        if rel in STATIC_SCAN_EXCLUDED_FILES:
            continue
        if not should_scan(path):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            for token in tokens:
                if token in line:
                    refs.append(
                        StaticReference(
                            file=rel,
                            line=line_number,
                            token=token,
                            text=line.strip()[:240],
                        )
                    )
                    break
    return refs


def summarize(rows: list[CatalogRow], refs: list[StaticReference]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for row in rows:
        summary[f"{row.kind}_count"] = summary.get(f"{row.kind}_count", 0) + 1
        if row.owner == "jarvisbrain":
            summary[f"{row.kind}_owned_by_jarvisbrain"] = (
                summary.get(f"{row.kind}_owned_by_jarvisbrain", 0) + 1
            )
        if row.kind == "function" and row.detail.get("security_definer") is True:
            summary["security_definer_function_count"] = (
                summary.get("security_definer_function_count", 0) + 1
            )
            if row.owner == "jarvisbrain":
                summary["security_definer_functions_owned_by_jarvisbrain"] = (
                    summary.get("security_definer_functions_owned_by_jarvisbrain", 0)
                    + 1
                )
    summary["static_reference_count"] = len(refs)
    summary["static_u_jarvisbrain_count"] = sum(
        1 for ref in refs if ref.token == "-U jarvisbrain"
    )
    return dict(sorted(summary.items()))


def build_inventory(args: argparse.Namespace) -> Inventory:
    rows = collect_catalog(
        psql_bin=args.psql_bin,
        db=args.db,
        user=args.user,
        host=args.host,
        ssh_target=args.ssh_target,
    )
    refs = static_references(args.repo_root)
    return Inventory(
        database=args.db,
        generated_by="scripts/postgres_owner_inventory.py",
        rows=rows,
        static_references=refs,
        summary=summarize(rows, refs),
    )


def render_json(inventory: Inventory) -> str:
    return json.dumps(asdict(inventory), indent=2, sort_keys=True) + "\n"


def _rows_by_kind(rows: list[CatalogRow], kind: str) -> list[CatalogRow]:
    return [row for row in rows if row.kind == kind]


def render_markdown(inventory: Inventory) -> str:
    lines = [
        "# Alpha Postgres Ownership Inventory",
        "",
        "Generated by `scripts/postgres_owner_inventory.py`.",
        f"Catalog source: `{inventory.generated_by}`.",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|---|---:|",
    ]
    for key, value in inventory.summary.items():
        lines.append(f"| `{key}` | {value} |")

    lines.extend(
        [
            "",
            "## Owner Concentration",
            "",
            "| Kind | Name | Owner | Detail |",
            "|---|---|---|---|",
        ]
    )
    for row in inventory.rows:
        if row.owner != "jarvisbrain":
            continue
        detail = ", ".join(f"{k}={v}" for k, v in row.detail.items())
        lines.append(f"| {row.kind} | `{row.name}` | `{row.owner}` | {detail} |")

    lines.extend(
        [
            "",
            "## SECURITY DEFINER Functions",
            "",
            "| Function | Owner | Detail |",
            "|---|---|---|",
        ]
    )
    for row in _rows_by_kind(inventory.rows, "function"):
        if row.detail.get("security_definer") is not True:
            continue
        detail = ", ".join(f"{k}={v}" for k, v in row.detail.items())
        lines.append(f"| `{row.name}` | `{row.owner}` | {detail} |")

    lines.extend(
        [
            "",
            "## Extensions",
            "",
            "| Extension | Owner | Detail |",
            "|---|---|---|",
        ]
    )
    for row in _rows_by_kind(inventory.rows, "extension"):
        detail = ", ".join(f"{k}={v}" for k, v in row.detail.items())
        lines.append(f"| `{row.name}` | `{row.owner}` | {detail} |")

    lines.extend(
        [
            "",
            "## Static `jarvisbrain` References",
            "",
            "| File | Line | Token | Text |",
            "|---|---:|---|---|",
        ]
    )
    for ref in inventory.static_references:
        text = ref.text.replace("|", "\\|")
        lines.append(f"| `{ref.file}` | {ref.line} | `{ref.token}` | {text} |")

    lines.extend(
        [
            "",
            "## Phase 2 Implications",
            "",
            "- Create `jarvis_alpha_owner` and `jarvis_alpha_migrator` only after this inventory is reviewed.",
            "- Generate explicit `ALTER ... OWNER TO jarvis_alpha_owner` statements; do not use broad `REASSIGN OWNED` on live Alpha.",
            "- Treat SECURITY DEFINER function ownership as the highest-risk part of Phase 3.",
            "- Replace day-to-day `-U jarvisbrain` tooling after owner and migrator roles exist.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Alpha Postgres ownership inventory"
    )
    parser.add_argument("--db", default=os.getenv("POSTGRES_OWNER_DB", "jarvis_alpha"))
    parser.add_argument(
        "--user", default=os.getenv("POSTGRES_OWNER_USER", "jarvisbrain")
    )
    parser.add_argument("--host", default=os.getenv("POSTGRES_OWNER_HOST", "localhost"))
    parser.add_argument(
        "--ssh-target",
        default=os.getenv("POSTGRES_OWNER_SSH_TARGET"),
        help=(
            "Optional SSH target for running catalog psql queries on Brain. "
            "Static code scanning still runs locally."
        ),
    )
    parser.add_argument("--psql-bin", default=os.getenv("PSQL_BIN", DEFAULT_PSQL_BIN))
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inventory = build_inventory(args)
    if args.ssh_target:
        inventory = Inventory(
            database=inventory.database,
            generated_by=f"ssh:{args.ssh_target}",
            rows=inventory.rows,
            static_references=inventory.static_references,
            summary=inventory.summary,
        )
    rendered = (
        render_json(inventory) if args.format == "json" else render_markdown(inventory)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
