from __future__ import annotations

from argparse import Namespace

from scripts import postgres_owner_plan as plan


def test_ownership_statements_are_explicit_and_skip_roles():
    owner_plan = plan.OwnerPlan(
        database="jarvis_alpha",
        source="test",
        owner_role="jarvis_alpha_owner",
        migrator_role="jarvis_alpha_migrator",
        objects=[
            plan.PlannedObject("database", "jarvis_alpha", "jarvisbrain", {}),
            plan.PlannedObject("schema", "public", "jarvisbrain", {}),
            plan.PlannedObject("extension", "pgcrypto", "jarvisbrain", {}),
            plan.PlannedObject(
                "relation", "TABLE public.alpha_users", "jarvisbrain", {}
            ),
            plan.PlannedObject(
                "function",
                "public.record_event(p_body text)",
                "jarvisbrain",
                {"security_definer": True},
            ),
            plan.PlannedObject("role", "jarvisbrain", "jarvisbrain", {}),
            plan.PlannedObject("relation", "TABLE public.already_ok", "other", {}),
        ],
    )

    statements = plan.ownership_statements(owner_plan)

    assert statements == [
        "ALTER DATABASE jarvis_alpha OWNER TO jarvis_alpha_owner;",
        "ALTER SCHEMA public OWNER TO jarvis_alpha_owner;",
        "ALTER TABLE public.alpha_users OWNER TO jarvis_alpha_owner;",
        (
            "ALTER FUNCTION public.record_event(p_body text) "
            "OWNER TO jarvis_alpha_owner;"
        ),
    ]


def test_render_review_sql_comments_mutating_statements():
    owner_plan = plan.OwnerPlan(
        database="jarvis_alpha",
        source="ssh:brain",
        owner_role="jarvis_alpha_owner",
        migrator_role="jarvis_alpha_migrator",
        objects=[
            plan.PlannedObject("database", "jarvis_alpha", "jarvisbrain", {}),
            plan.PlannedObject(
                "function",
                "public.secdef()",
                "jarvisbrain",
                {"security_definer": True},
            ),
        ],
    )

    sql = plan.render_review_sql(owner_plan)

    assert "REVIEW ONLY" in sql
    assert "--     CREATE ROLE jarvis_alpha_owner" in sql
    assert "-- ALTER DATABASE jarvis_alpha OWNER TO jarvis_alpha_owner;" in sql
    assert "-- ALTER FUNCTION public.secdef() OWNER TO jarvis_alpha_owner;" in sql
    assert "-- ALTER ROLE jarvisbrain NOSUPERUSER" in sql
    assert "\nALTER DATABASE jarvis_alpha" not in sql
    assert "\nALTER ROLE jarvisbrain NOSUPERUSER" not in sql


def test_phase3a_apply_holds_security_definer_and_demote_steps():
    owner_plan = plan.OwnerPlan(
        database="jarvis_alpha",
        source="ssh:brain",
        owner_role="jarvis_alpha_owner",
        migrator_role="jarvis_alpha_migrator",
        objects=[
            plan.PlannedObject("database", "jarvis_alpha", "jarvisbrain", {}),
            plan.PlannedObject(
                "function",
                "public.secdef()",
                "jarvisbrain",
                {"security_definer": True},
            ),
            plan.PlannedObject(
                "function",
                "public.normal()",
                "jarvisbrain",
                {"security_definer": False},
            ),
        ],
    )

    sql = plan.render_phase3a_apply_sql(owner_plan)

    assert "BEGIN;" in sql
    assert "COMMIT;" in sql
    assert "CREATE ROLE jarvis_alpha_owner" in sql
    assert "ALTER DATABASE jarvis_alpha OWNER TO jarvis_alpha_owner;" in sql
    assert "ALTER EXTENSION" not in sql
    assert "ALTER FUNCTION public.normal() OWNER TO jarvis_alpha_owner;" in sql
    assert "-- ALTER FUNCTION public.secdef() OWNER TO jarvis_alpha_owner;" in sql
    assert "-- ALTER ROLE jarvisbrain NOSUPERUSER" in sql
    assert "\nALTER ROLE jarvisbrain NOSUPERUSER" not in sql


def test_phase3a_rollback_restores_non_security_definer_ownership():
    owner_plan = plan.OwnerPlan(
        database="jarvis_alpha",
        source="ssh:brain",
        owner_role="jarvis_alpha_owner",
        migrator_role="jarvis_alpha_migrator",
        objects=[
            plan.PlannedObject("database", "jarvis_alpha", "jarvisbrain", {}),
            plan.PlannedObject(
                "function",
                "public.secdef()",
                "jarvisbrain",
                {"security_definer": True},
            ),
            plan.PlannedObject(
                "function",
                "public.normal()",
                "jarvisbrain",
                {"security_definer": False},
            ),
        ],
    )

    sql = plan.render_phase3a_rollback_sql(owner_plan)

    assert "ALTER ROLE jarvisbrain SUPERUSER" in sql
    assert "ALTER DATABASE jarvis_alpha OWNER TO jarvisbrain;" in sql
    assert "ALTER FUNCTION public.normal() OWNER TO jarvisbrain;" in sql
    assert "ALTER FUNCTION public.secdef() OWNER TO jarvisbrain;" not in sql
    assert "DROP ROLE IF EXISTS jarvis_alpha_migrator;" in sql


def test_phase3b_secdef_apply_only_moves_security_definer_functions():
    owner_plan = plan.OwnerPlan(
        database="jarvis_alpha",
        source="ssh:brain",
        owner_role="jarvis_alpha_owner",
        migrator_role="jarvis_alpha_migrator",
        objects=[
            plan.PlannedObject("database", "jarvis_alpha", "jarvis_alpha_owner", {}),
            plan.PlannedObject(
                "function",
                "public.secdef()",
                "jarvisbrain",
                {"security_definer": True},
            ),
            plan.PlannedObject(
                "function",
                "public.normal()",
                "jarvis_alpha_owner",
                {"security_definer": False},
            ),
        ],
    )

    sql = plan.render_phase3b_secdef_apply_sql(owner_plan)

    assert "ALTER FUNCTION public.secdef() OWNER TO jarvis_alpha_owner;" in sql
    assert "ALTER FUNCTION public.normal()" not in sql
    assert "ALTER DATABASE" not in sql
    assert "ALTER ROLE jarvisbrain NOSUPERUSER" not in sql
    assert "This file does not demote jarvisbrain" in sql


def test_phase3b_secdef_rollback_restores_security_definers_to_jarvisbrain():
    owner_plan = plan.OwnerPlan(
        database="jarvis_alpha",
        source="ssh:brain",
        owner_role="jarvis_alpha_owner",
        migrator_role="jarvis_alpha_migrator",
        objects=[
            plan.PlannedObject(
                "function",
                "public.secdef()",
                "jarvisbrain",
                {"security_definer": True},
            ),
            plan.PlannedObject(
                "function",
                "public.normal()",
                "jarvis_alpha_owner",
                {"security_definer": False},
            ),
        ],
    )

    sql = plan.render_phase3b_secdef_rollback_sql(owner_plan)

    assert "ALTER FUNCTION public.secdef() OWNER TO jarvisbrain;" in sql
    assert "ALTER FUNCTION public.normal()" not in sql
    assert "ALTER ROLE jarvisbrain" not in sql


def test_build_owner_plan_uses_catalog_queries(monkeypatch):
    outputs = {
        "FROM pg_database": "database|jarvis_alpha|jarvisbrain|allow_connections=true\n",
        "FROM pg_namespace": "schema|public|jarvisbrain|acl=\n",
        "FROM pg_extension": "extension|pgcrypto|jarvisbrain|schema=public\n",
        "FROM pg_class": (
            "relation|TABLE public.alpha_users|jarvisbrain|"
            "relkind=r,rls=true,force_rls=true\n"
        ),
        "FROM pg_proc": (
            "function|public.secdef()|jarvisbrain|security_definer=true,volatile=v\n"
        ),
        "FROM pg_roles": "role|jarvisbrain|jarvisbrain|super=true,login=true\n",
    }

    def fake_run_psql(query, **kwargs):
        for needle, output in outputs.items():
            if needle in query:
                return plan.CommandResult(0, output, "")
        raise AssertionError(query)

    monkeypatch.setattr(plan, "run_psql", fake_run_psql)

    owner_plan = plan.build_owner_plan(
        Namespace(
            psql_bin="psql",
            db="jarvis_alpha",
            user="jarvisbrain",
            host="localhost",
            ssh_target="jarvisbrain@example",
            owner_role="jarvis_alpha_owner",
            migrator_role="jarvis_alpha_migrator",
        )
    )

    assert owner_plan.source == "ssh:jarvisbrain@example"
    assert len(owner_plan.objects) == 6
    assert owner_plan.objects[4].detail["security_definer"] is True
