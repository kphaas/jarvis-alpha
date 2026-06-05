#!/usr/bin/env python3
"""Generate a review-only Postgres owner split SQL plan for Alpha."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.postgres_owner_inventory import (  # noqa: E402
    DEFAULT_PSQL_BIN,
    CommandResult,
    parse_detail,
    parse_rows,
    run_psql,
)

DEFAULT_OWNER_ROLE = "jarvis_alpha_owner"
DEFAULT_MIGRATOR_ROLE = "jarvis_alpha_migrator"


@dataclass(frozen=True)
class PlannedObject:
    kind: str
    identity: str
    owner: str
    detail: dict[str, str | bool | int]


@dataclass(frozen=True)
class OwnerPlan:
    database: str
    source: str
    owner_role: str
    migrator_role: str
    objects: list[PlannedObject]


PLAN_QUERIES: list[tuple[str, str]] = [
    (
        "database",
        """
SELECT 'database',
       quote_ident(d.datname),
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
       quote_ident(n.nspname),
       pg_get_userbyid(n.nspowner),
       'acl=' || COALESCE(array_to_string(n.nspacl, ','), '')
FROM pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
ORDER BY n.nspname;
""".strip(),
    ),
    (
        "extension",
        """
SELECT 'extension',
       quote_ident(e.extname),
       pg_get_userbyid(e.extowner),
       'schema=' || COALESCE(n.nspname, '')
FROM pg_extension e
LEFT JOIN pg_namespace n ON n.oid = e.extnamespace
ORDER BY e.extname;
""".strip(),
    ),
    (
        "relation",
        """
WITH extension_members AS (
    SELECT objid
    FROM pg_depend
    WHERE deptype = 'e'
)
SELECT 'relation',
       CASE c.relkind
         WHEN 'S' THEN 'SEQUENCE '
         WHEN 'v' THEN 'VIEW '
         WHEN 'm' THEN 'MATERIALIZED VIEW '
         WHEN 'f' THEN 'FOREIGN TABLE '
         ELSE 'TABLE '
       END || format('%I.%I', n.nspname, c.relname),
       pg_get_userbyid(c.relowner),
       'relkind=' || c.relkind::text
         || ',rls=' || c.relrowsecurity::text
         || ',force_rls=' || c.relforcerowsecurity::text
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
  AND NOT EXISTS (
      SELECT 1 FROM extension_members e WHERE e.objid = c.oid
  )
ORDER BY n.nspname, c.relname;
""".strip(),
    ),
    (
        "function",
        """
WITH extension_members AS (
    SELECT objid
    FROM pg_depend
    WHERE deptype = 'e'
)
SELECT 'function',
       format('%I.%I(%s)',
              n.nspname,
              p.proname,
              pg_get_function_identity_arguments(p.oid)),
       pg_get_userbyid(p.proowner),
       'security_definer=' || p.prosecdef::text
         || ',volatile=' || p.provolatile::text
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND NOT EXISTS (
      SELECT 1 FROM extension_members e WHERE e.objid = p.oid
  )
ORDER BY n.nspname, p.proname, pg_get_function_identity_arguments(p.oid);
""".strip(),
    ),
    (
        "role",
        """
SELECT 'role',
       quote_ident(r.rolname),
       r.rolname,
       'super=' || r.rolsuper::text
         || ',bypassrls=' || r.rolbypassrls::text
         || ',createdb=' || r.rolcreatedb::text
         || ',createrole=' || r.rolcreaterole::text
         || ',login=' || r.rolcanlogin::text
FROM pg_roles r
WHERE r.rolname IN ('jarvisbrain', 'postgres')
   OR r.rolname LIKE 'jarvis_alpha_%'
   OR r.rolsuper
ORDER BY r.rolname;
""".strip(),
    ),
]


def collect_plan_objects(
    *,
    psql_bin: str,
    db: str,
    user: str,
    host: str,
    ssh_target: str | None,
) -> list[PlannedObject]:
    objects: list[PlannedObject] = []
    for expected_kind, query in PLAN_QUERIES:
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
                f"{expected_kind} plan query failed: "
                f"{(result.stderr or result.stdout).strip()}"
            )
        objects.extend(_objects_from_result(result))
    return objects


def _objects_from_result(result: CommandResult) -> list[PlannedObject]:
    objects: list[PlannedObject] = []
    for parsed in parse_rows(result.stdout):
        if len(parsed) < 4:
            continue
        objects.append(
            PlannedObject(
                kind=parsed[0],
                identity=parsed[1],
                owner=parsed[2],
                detail=parse_detail(parsed[3]),
            )
        )
    return objects


def build_owner_plan(args: argparse.Namespace) -> OwnerPlan:
    objects = collect_plan_objects(
        psql_bin=args.psql_bin,
        db=args.db,
        user=args.user,
        host=args.host,
        ssh_target=args.ssh_target,
    )
    source = f"ssh:{args.ssh_target}" if args.ssh_target else f"local:{args.host}"
    return OwnerPlan(
        database=args.db,
        source=source,
        owner_role=args.owner_role,
        migrator_role=args.migrator_role,
        objects=objects,
    )


def render_review_sql(plan: OwnerPlan) -> str:
    counts = _counts(plan.objects)
    lines = [
        "-- Alpha Postgres owner split plan",
        "-- Generated by scripts/postgres_owner_plan.py.",
        f"-- Catalog source: {plan.source}.",
        "--",
        "-- REVIEW ONLY: mutating statements are commented out on purpose.",
        "-- Do not remove comments or apply this to Brain until Phase 3 is reviewed.",
        "--",
        "-- Phase 2 intent:",
        "-- 1. Define least-privilege owner and migrator roles.",
        "-- 2. Prepare explicit ownership transfer statements.",
        "-- 3. Keep extension-member objects out of individual ALTER statements.",
        "-- 4. Leave jarvisbrain demotion for a separate Phase 3 execution PR.",
        "--",
        "-- Inventory counts:",
    ]
    for key in sorted(counts):
        lines.append(f"-- - {key}: {counts[key]}")

    lines.extend(
        [
            "",
            "\\set ON_ERROR_STOP on",
            "",
            "-- Read-only safety precheck.",
            "SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolcanlogin",
            "FROM pg_roles",
            "WHERE rolname IN (",
            f"  '{plan.owner_role}',",
            f"  '{plan.migrator_role}',",
            "  'jarvisbrain',",
            "  'postgres'",
            ") OR rolsuper",
            "ORDER BY rolname;",
            "",
            "-- Role bootstrap. Keep passwords out of source control.",
            "-- DO $$",
            "-- BEGIN",
            f"--   IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{plan.owner_role}') THEN",
            f"--     CREATE ROLE {plan.owner_role} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;",
            "--   END IF;",
            f"--   IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{plan.migrator_role}') THEN",
            f"--     CREATE ROLE {plan.migrator_role} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;",
            "--   END IF;",
            "-- END",
            "-- $$;",
            f"-- GRANT {plan.owner_role} TO {plan.migrator_role};",
            "",
            "-- Ownership transfer statements.",
        ]
    )
    for statement in ownership_statements(plan, include_security_definer=True):
        lines.append(f"-- {statement}")

    lines.extend(
        [
            "",
            "-- Phase 3 final demotion candidate. Do not run in Phase 2.",
            "-- ALTER ROLE jarvisbrain NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;",
            "",
            "-- Post-change verification query.",
            "SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolcanlogin",
            "FROM pg_roles",
            "WHERE rolname IN ('jarvisbrain', 'jarvis_alpha_owner', 'jarvis_alpha_migrator')",
            "ORDER BY rolname;",
            "",
        ]
    )
    return "\n".join(lines)


def render_phase3a_apply_sql(plan: OwnerPlan) -> str:
    counts = _counts(plan.objects)
    lines = [
        "-- Alpha Postgres owner split Phase 3A apply plan",
        "-- Generated by scripts/postgres_owner_plan.py.",
        f"-- Catalog source: {plan.source}.",
        "--",
        "-- Phase 3A executes only role bootstrap and non-SECURITY-DEFINER ownership prep.",
        "-- SECURITY DEFINER transfers and jarvisbrain demotion remain commented pending canaries.",
        "--",
        "-- Required operator gates before running:",
        "-- 1. PR #239 reviewed and merged.",
        "-- 2. Fresh Brain backup completed.",
        "-- 3. Alpha health/readiness green immediately before apply.",
        "-- 4. SECURITY DEFINER canary plan reviewed for Phase 3B.",
        "",
        "\\set ON_ERROR_STOP on",
        "",
        "BEGIN;",
        "",
        "DO $$",
        "BEGIN",
        "  IF NOT EXISTS (",
        "      SELECT 1 FROM pg_roles",
        "      WHERE rolname <> 'jarvisbrain' AND rolsuper",
        "  ) THEN",
        "    RAISE EXCEPTION 'Refusing owner split: no non-jarvisbrain superuser recovery role exists';",
        "  END IF;",
        "",
        "  IF NOT EXISTS (",
        "      SELECT 1 FROM pg_roles",
        "      WHERE rolname = 'jarvisbrain' AND rolsuper AND NOT rolbypassrls",
        "  ) THEN",
        "    RAISE EXCEPTION 'Refusing owner split: jarvisbrain is not in expected pre-Phase 3 state';",
        "  END IF;",
        "END",
        "$$;",
        "",
        "DO $$",
        "BEGIN",
        f"  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{plan.owner_role}') THEN",
        f"    CREATE ROLE {plan.owner_role} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;",
        "  END IF;",
        f"  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{plan.migrator_role}') THEN",
        f"    CREATE ROLE {plan.migrator_role} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;",
        "  END IF;",
        "END",
        "$$;",
        "",
        f"GRANT {plan.owner_role} TO {plan.migrator_role};",
        "",
        "-- Non-SECURITY-DEFINER ownership prep.",
    ]
    for statement in ownership_statements(plan, include_security_definer=False):
        lines.append(statement)

    lines.extend(["", "-- Held for Phase 3B: SECURITY DEFINER ownership changes."])
    for statement in ownership_statements(plan, include_only_security_definer=True):
        lines.append(f"-- {statement}")

    lines.extend(
        [
            "",
            "-- Held for Phase 3B: demote jarvisbrain after canaries pass.",
            "-- ALTER ROLE jarvisbrain NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;",
            "",
            "COMMIT;",
            "",
            "-- Post-change verification.",
            "SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolcanlogin",
            "FROM pg_roles",
            f"WHERE rolname IN ('jarvisbrain', '{plan.owner_role}', '{plan.migrator_role}')",
            "ORDER BY rolname;",
            "",
            "SELECT pg_get_userbyid(datdba) AS database_owner",
            "FROM pg_database",
            f"WHERE datname = '{plan.database}';",
            "",
            "-- Expected Phase 3A counts from source inventory:",
        ]
    )
    for key in sorted(counts):
        lines.append(f"-- - {key}: {counts[key]}")
    lines.append("")
    return "\n".join(lines)


def render_phase3a_rollback_sql(plan: OwnerPlan) -> str:
    lines = [
        "-- Alpha Postgres owner split Phase 3A rollback",
        "-- Generated by scripts/postgres_owner_plan.py.",
        f"-- Catalog source: {plan.source}.",
        "--",
        "-- Restores Phase 3A ownership prep back to jarvisbrain.",
        "-- Does not drop roles until ownership is restored.",
        "",
        "\\set ON_ERROR_STOP on",
        "",
        "BEGIN;",
        "",
        "ALTER ROLE jarvisbrain SUPERUSER NOBYPASSRLS CREATEDB CREATEROLE;",
        "",
    ]
    for statement in ownership_statements(
        plan,
        target_owner="jarvisbrain",
        include_security_definer=False,
        source_owner="jarvisbrain",
    ):
        lines.append(statement)
    lines.extend(
        [
            "",
            f"REVOKE {plan.owner_role} FROM {plan.migrator_role};",
            f"DROP ROLE IF EXISTS {plan.migrator_role};",
            f"DROP ROLE IF EXISTS {plan.owner_role};",
            "",
            "COMMIT;",
            "",
        ]
    )
    return "\n".join(lines)


def render_phase3b_secdef_apply_sql(plan: OwnerPlan) -> str:
    lines = [
        "-- Alpha Postgres owner split Phase 3B SECURITY DEFINER apply",
        "-- Generated by scripts/postgres_owner_plan.py.",
        f"-- Catalog source: {plan.source}.",
        "--",
        "-- Moves canary-passing SECURITY DEFINER functions to jarvis_alpha_owner.",
        "-- Extension-owned pgaudit C event triggers are excluded by the catalog query.",
        "-- This file does not demote jarvisbrain.",
        "",
        "\\set ON_ERROR_STOP on",
        "",
        "BEGIN;",
        "",
        "DO $$",
        "BEGIN",
        f"  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{plan.owner_role}') THEN",
        f"    RAISE EXCEPTION 'Missing owner role: {plan.owner_role}';",
        "  END IF;",
        "",
        "  IF NOT EXISTS (",
        "      SELECT 1 FROM pg_roles",
        "      WHERE rolname = 'jarvisbrain' AND rolsuper AND NOT rolbypassrls",
        "  ) THEN",
        "    RAISE EXCEPTION 'jarvisbrain is not in expected pre-Phase 3B state';",
        "  END IF;",
        "END",
        "$$;",
        "",
        "-- Canary-passing SECURITY DEFINER ownership transfer.",
    ]
    lines.extend(ownership_statements(plan, include_only_security_definer=True))
    lines.extend(
        [
            "",
            "COMMIT;",
            "",
            "-- Post-change verification.",
            "SELECT pg_get_userbyid(p.proowner) AS owner, count(*)",
            "FROM pg_proc p",
            "JOIN pg_namespace n ON n.oid = p.pronamespace",
            "WHERE p.prosecdef",
            "  AND n.nspname = 'public'",
            "GROUP BY 1",
            "ORDER BY 1;",
            "",
        ]
    )
    return "\n".join(lines)


def render_phase3b_secdef_rollback_sql(plan: OwnerPlan) -> str:
    lines = [
        "-- Alpha Postgres owner split Phase 3B SECURITY DEFINER rollback",
        "-- Generated by scripts/postgres_owner_plan.py.",
        f"-- Catalog source: {plan.source}.",
        "--",
        "-- Restores canary-passing SECURITY DEFINER functions to jarvisbrain.",
        "-- Extension-owned pgaudit C event triggers were not changed by Phase 3B.",
        "",
        "\\set ON_ERROR_STOP on",
        "",
        "BEGIN;",
        "",
    ]
    lines.extend(
        ownership_statements(
            plan,
            target_owner="jarvisbrain",
            include_only_security_definer=True,
        )
    )
    lines.extend(
        [
            "",
            "COMMIT;",
            "",
            "-- Post-rollback verification.",
            "SELECT pg_get_userbyid(p.proowner) AS owner, count(*)",
            "FROM pg_proc p",
            "JOIN pg_namespace n ON n.oid = p.pronamespace",
            "WHERE p.prosecdef",
            "  AND n.nspname = 'public'",
            "GROUP BY 1",
            "ORDER BY 1;",
            "",
        ]
    )
    return "\n".join(lines)


def ownership_statements(
    plan: OwnerPlan,
    *,
    target_owner: str | None = None,
    include_security_definer: bool = True,
    include_only_security_definer: bool = False,
    source_owner: str = "jarvisbrain",
) -> list[str]:
    owner = target_owner or plan.owner_role
    statements: list[str] = []
    for obj in plan.objects:
        if obj.kind == "role" or obj.owner != source_owner:
            continue
        is_security_definer = (
            obj.kind == "function" and obj.detail.get("security_definer") is True
        )
        if include_only_security_definer and not is_security_definer:
            continue
        if not include_security_definer and is_security_definer:
            continue
        if obj.kind == "extension":
            continue
        if obj.kind == "database":
            statements.append(f"ALTER DATABASE {obj.identity} OWNER TO {owner};")
        elif obj.kind == "schema":
            statements.append(f"ALTER SCHEMA {obj.identity} OWNER TO {owner};")
        elif obj.kind == "relation":
            statements.append(f"ALTER {obj.identity} OWNER TO {owner};")
        elif obj.kind == "function":
            statements.append(f"ALTER FUNCTION {obj.identity} OWNER TO {owner};")
    return statements


def _counts(objects: list[PlannedObject]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for obj in objects:
        counts[obj.kind] = counts.get(obj.kind, 0) + 1
        if obj.owner == "jarvisbrain":
            counts[f"{obj.kind}_owned_by_jarvisbrain"] = (
                counts.get(f"{obj.kind}_owned_by_jarvisbrain", 0) + 1
            )
        if obj.kind == "function" and obj.detail.get("security_definer") is True:
            counts["security_definer_functions"] = (
                counts.get("security_definer_functions", 0) + 1
            )
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a review-only Alpha Postgres owner split SQL plan"
    )
    parser.add_argument("--db", default=os.getenv("POSTGRES_OWNER_DB", "jarvis_alpha"))
    parser.add_argument(
        "--user", default=os.getenv("POSTGRES_OWNER_USER", "jarvisbrain")
    )
    parser.add_argument("--host", default=os.getenv("POSTGRES_OWNER_HOST", "localhost"))
    parser.add_argument("--psql-bin", default=os.getenv("PSQL_BIN", DEFAULT_PSQL_BIN))
    parser.add_argument(
        "--ssh-target",
        default=os.getenv("POSTGRES_OWNER_SSH_TARGET"),
        help="Optional SSH target for Brain catalog queries.",
    )
    parser.add_argument("--owner-role", default=DEFAULT_OWNER_ROLE)
    parser.add_argument("--migrator-role", default=DEFAULT_MIGRATOR_ROLE)
    parser.add_argument(
        "--mode",
        choices=(
            "review",
            "phase3a-apply",
            "phase3a-rollback",
            "phase3b-secdef-apply",
            "phase3b-secdef-rollback",
        ),
        default="review",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = build_owner_plan(args)
    if args.mode == "phase3a-apply":
        rendered = render_phase3a_apply_sql(plan)
    elif args.mode == "phase3a-rollback":
        rendered = render_phase3a_rollback_sql(plan)
    elif args.mode == "phase3b-secdef-apply":
        rendered = render_phase3b_secdef_apply_sql(plan)
    elif args.mode == "phase3b-secdef-rollback":
        rendered = render_phase3b_secdef_rollback_sql(plan)
    else:
        rendered = render_review_sql(plan)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
