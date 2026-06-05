from __future__ import annotations

from argparse import Namespace

from scripts import postgres_secdef_canary as canary


def test_render_canary_transaction_rolls_back_owner_transfer():
    sql = canary.render_canary_transaction(
        identity="public.example()",
        target_owner="jarvis_alpha_owner",
        setup_sql="SELECT 1",
        canary_sql="SELECT public.example()",
        nonce="abc123",
    )

    assert "BEGIN;" in sql
    assert "ALTER FUNCTION public.example() OWNER TO jarvis_alpha_owner;" in sql
    assert "SELECT public.example();" in sql
    assert "ROLLBACK;" in sql
    assert "COMMIT;" not in sql


def test_render_canary_transaction_replaces_nonce_without_formatting_json():
    sql = canary.render_canary_transaction(
        identity="public.example()",
        target_owner="jarvis_alpha_owner",
        setup_sql="",
        canary_sql='SELECT \'{"nonce":"__NONCE__"}\'::jsonb',
        nonce="abc123",
    )

    assert '{"nonce":"abc123"}' in sql


def test_run_canaries_passes_known_function_and_skips_pgaudit(monkeypatch):
    functions = [
        canary.SecdefFunction(
            "public.bump_memory_access(p_ids uuid[])",
            "jarvisbrain",
            "plpgsql",
        ),
        canary.SecdefFunction(
            "public.pgaudit_sql_drop()",
            "jarvisbrain",
            "c",
        ),
    ]

    def fake_collect_secdef_functions(**kwargs):
        return functions

    def fake_run_psql(query, **kwargs):
        assert "ALTER FUNCTION public.bump_memory_access" in query
        assert "ROLLBACK;" in query
        return canary.CommandResult(0, "ok\n", "")

    monkeypatch.setattr(
        canary, "collect_secdef_functions", fake_collect_secdef_functions
    )
    monkeypatch.setattr(canary, "run_psql", fake_run_psql)

    report = canary.run_canaries(
        Namespace(
            psql_bin="psql",
            db="jarvis_alpha",
            user="jarvisbrain",
            host="localhost",
            ssh_target=None,
            target_owner="jarvis_alpha_owner",
            timeout=45,
        )
    )

    assert report.summary["pass"] == 1
    assert report.summary["skipped"] == 1
    assert canary.has_blockers(report) is True


def test_uncovered_live_secdef_function_blocks_report(monkeypatch):
    def fake_collect_secdef_functions(**kwargs):
        return [
            canary.SecdefFunction(
                "public.new_uncovered_function()",
                "jarvisbrain",
                "plpgsql",
            )
        ]

    monkeypatch.setattr(
        canary, "collect_secdef_functions", fake_collect_secdef_functions
    )

    report = canary.run_canaries(
        Namespace(
            psql_bin="psql",
            db="jarvis_alpha",
            user="jarvisbrain",
            host="localhost",
            ssh_target="brain",
            target_owner="jarvis_alpha_owner",
            timeout=45,
        )
    )

    uncovered = [
        result
        for result in report.results
        if result.identity == "public.new_uncovered_function()"
    ]
    assert uncovered[0].status == "uncovered"
    assert canary.has_blockers(report) is True


def test_render_markdown_documents_demotion_gate():
    report = canary.CanaryReport(
        database="jarvis_alpha",
        source="test",
        target_owner="jarvis_alpha_owner",
        generated_by="test",
        results=[
            canary.CanaryResult(
                identity="public.bump_memory_access(p_ids uuid[])",
                status="pass",
                owner_before="jarvisbrain",
                language="plpgsql",
                detail="ok",
                note="",
            )
        ],
        summary={"pass": 1, "total": 1},
    )

    markdown = canary.render_markdown(report)

    assert "rolls the transaction back" in markdown
    assert "This report does not demote `jarvisbrain`" in markdown
