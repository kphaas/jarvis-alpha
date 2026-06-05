from __future__ import annotations

from argparse import Namespace

from scripts import postgres_owner_inventory as inventory


def test_parse_detail_coerces_bool_and_int_values():
    detail = inventory.parse_detail("relkind=r,rls=true,force_rls=false,policies=3")

    assert detail == {
        "relkind": "r",
        "rls": True,
        "force_rls": False,
        "policies": 3,
    }


def test_summarize_counts_jarvisbrain_and_security_definer_ownership():
    rows = [
        inventory.CatalogRow("database", "jarvis_alpha", "jarvisbrain", {}),
        inventory.CatalogRow(
            "function",
            "public.secdef()",
            "jarvisbrain",
            {"security_definer": True},
        ),
        inventory.CatalogRow(
            "function",
            "public.normal()",
            "jarvis_alpha_owner",
            {"security_definer": False},
        ),
    ]
    refs = [
        inventory.StaticReference(
            "scripts/apply_migrations.sh",
            1,
            "-U jarvisbrain",
            "psql -U jarvisbrain",
        )
    ]

    summary = inventory.summarize(rows, refs)

    assert summary["database_owned_by_jarvisbrain"] == 1
    assert summary["function_count"] == 2
    assert summary["function_owned_by_jarvisbrain"] == 1
    assert summary["security_definer_function_count"] == 1
    assert summary["security_definer_functions_owned_by_jarvisbrain"] == 1
    assert summary["static_u_jarvisbrain_count"] == 1


def test_static_references_skips_excluded_dirs(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run.sh").write_text(
        "psql -U jarvisbrain -d jarvis_alpha\n", encoding="utf-8"
    )
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("jarvisbrain\n", encoding="utf-8")
    (tmp_path / "docs" / "reports").mkdir(parents=True)
    (tmp_path / "docs" / "reports" / "inventory.md").write_text(
        "jarvisbrain generated report content\n", encoding="utf-8"
    )

    refs = inventory.static_references(tmp_path)

    assert len(refs) == 1
    assert refs[0].file == "scripts/run.sh"
    assert refs[0].token == "-U jarvisbrain"


def test_build_inventory_uses_catalog_and_static_scans(monkeypatch, tmp_path):
    (tmp_path / "script.sh").write_text("echo jarvisbrain\n", encoding="utf-8")

    outputs = {
        "FROM pg_database": "database|jarvis_alpha|jarvisbrain|allow_connections=true\n",
        "FROM pg_namespace": "schema|public|jarvisbrain|acl=\n",
        "FROM pg_class": (
            "relation|public.alpha_profiles|jarvisbrain|"
            "relkind=r,rls=true,force_rls=true,policies=2\n"
        ),
        "FROM pg_proc": (
            "function|public.record_event()|jarvisbrain|"
            "security_definer=true,volatile=v\n"
        ),
        "FROM pg_extension": "extension|pgcrypto|jarvisbrain|schema=public\n",
        "FROM pg_roles": (
            "role|jarvisbrain|jarvisbrain|"
            "oid=10,super=true,bypassrls=false,createdb=true,createrole=true,login=true\n"
        ),
    }

    def fake_run_psql(query, **kwargs):
        for needle, output in outputs.items():
            if needle in query:
                return inventory.CommandResult(0, output, "")
        raise AssertionError(query)

    monkeypatch.setattr(inventory, "run_psql", fake_run_psql)

    report = inventory.build_inventory(
        Namespace(
            psql_bin="psql",
            db="jarvis_alpha",
            user="jarvisbrain",
            host="localhost",
            ssh_target=None,
            repo_root=tmp_path,
        )
    )

    assert report.summary["relation_owned_by_jarvisbrain"] == 1
    assert report.summary["security_definer_functions_owned_by_jarvisbrain"] == 1
    assert report.summary["static_reference_count"] == 1


def test_run_psql_can_execute_catalog_query_over_ssh(monkeypatch):
    calls = []

    class FakeProcess:
        returncode = 0
        stdout = "role|jarvisbrain|jarvisbrain|super=true\n"
        stderr = ""

    def fake_subprocess_run(args, **kwargs):
        calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setenv("POSTGRES_PASSWORD", "local-secret-value")
    monkeypatch.setattr(inventory.subprocess, "run", fake_subprocess_run)

    result = inventory.run_psql(
        "SELECT 1",
        psql_bin="/opt/homebrew/bin/psql",
        db="jarvis_alpha",
        user="jarvisbrain",
        host="localhost",
        ssh_target="jarvisbrain@jarvis-brain.tail40ed36.ts.net",
    )

    assert result.returncode == 0
    assert calls
    args, kwargs = calls[0]
    assert args[:3] == [
        "ssh",
        "-o",
        "BatchMode=yes",
    ]
    assert args[3] == "jarvisbrain@jarvis-brain.tail40ed36.ts.net"
    assert "local-secret-value" not in " ".join(args)
    assert "source ~/jarvis/.secrets" in args[4]
    assert "-d jarvis_alpha" in args[4]
    assert kwargs["capture_output"] is True
    assert kwargs["check"] is False


def test_render_markdown_includes_phase_guidance():
    report = inventory.Inventory(
        database="jarvis_alpha",
        generated_by="test",
        rows=[
            inventory.CatalogRow(
                "extension",
                "pgcrypto",
                "jarvisbrain",
                {"schema": "public"},
            )
        ],
        static_references=[],
        summary={"extension_count": 1, "extension_owned_by_jarvisbrain": 1},
    )

    markdown = inventory.render_markdown(report)

    assert "# Alpha Postgres Ownership Inventory" in markdown
    assert "`pgcrypto`" in markdown
    assert "do not use broad `REASSIGN OWNED`" in markdown
