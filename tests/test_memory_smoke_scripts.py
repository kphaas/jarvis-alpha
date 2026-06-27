from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SMOKE = REPO_ROOT / "scripts" / "run_smoke.sh"
MEMORY_SECDEF_SMOKE = REPO_ROOT / "scripts" / "smoke_memory_secdef.sh"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "jarvisalpha_deploy.sh"
MEMORY_GRAPH_SMOKE = REPO_ROOT / "scripts" / "smoke_memory_graph.py"
PUBLIC_REVOKE_MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260618_154500_semantic_memory_secdef_public_revoke.sql"
)
OWNER_GRANT_MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260618_155500_semantic_memory_secdef_owner_grant.sql"
)


def _script_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_memory_graph_smoke():
    spec = importlib.util.spec_from_file_location(
        "smoke_memory_graph_test_module",
        MEMORY_GRAPH_SMOKE,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_memory_smoke_scripts_have_clean_bash_syntax() -> None:
    for script in (RUN_SMOKE, MEMORY_SECDEF_SMOKE):
        result = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{script.name}: {result.stderr}"


def test_rls_smoke_uses_owner_auth_and_set_role_for_smoke_role() -> None:
    source = _script_text(RUN_SMOKE)

    assert 'source "${SECRETS_FILE}"' in source
    assert 'export PGPASSWORD="${POSTGRES_PASSWORD}"' in source
    assert 'OWNER_PSQL_ARGS=(-h localhost -d "${DB_NAME}" -U "${OWNER_ROLE}")' in source
    assert '-c "SET ROLE ${SMOKE_ROLE};"' in source
    assert '-U "${SMOKE_ROLE}"' not in source


def test_memory_secdef_smoke_checks_current_memory_functions() -> None:
    source = _script_text(MEMORY_SECDEF_SMOKE)

    assert "save_semantic_memory_with_provenance" in source
    assert "review_semantic_memory" in source
    assert "jarvis_alpha_owner" in source
    assert "aclexplode(COALESCE(proacl, acldefault('f', proowner)))" in source
    assert "acl.grantee = 0" in source
    assert "memory_secdef_smoke" in source
    assert "ALPHA_WRITER_DB_PASSWORD" in source
    assert "source = 'semantic_memory_review'\n     OR" not in source


def test_deploy_runs_memory_core_smoke_as_post_deploy_gate() -> None:
    source = _script_text(DEPLOY_SCRIPT)

    assert "smoke_memory_core.py" in source
    assert "JARVIS_ALPHA_SKIP_MEMORY_CORE_SMOKE" in source
    assert 'MEMORY_CORE_SMOKE_BASE_URL="$settings_base_url"' in source
    assert 'MEMORY_CORE_SMOKE_DB_SSH_TARGET="$BRAIN"' in source


def test_deploy_runs_memory_graph_smoke_as_post_deploy_gate() -> None:
    source = _script_text(DEPLOY_SCRIPT)

    assert "smoke_memory_graph.py" in source
    assert "JARVIS_ALPHA_SKIP_MEMORY_GRAPH_SMOKE" in source
    assert 'MEMORY_GRAPH_SMOKE_BASE_URL="$settings_base_url"' in source
    assert 'MEMORY_GRAPH_SMOKE_TOKEN_SSH_TARGET="$BRAIN"' in source


def test_memory_graph_smoke_does_not_print_tokens_or_raw_payloads() -> None:
    source = _script_text(MEMORY_GRAPH_SMOKE)

    assert "token" not in " ".join(
        line.strip() for line in source.splitlines() if line.strip().startswith('{"')
    )
    assert "payload_redacted" in source
    assert "/v1/memory/admin/graph/health" in source
    assert "/v1/memory/admin/graph/proposals?state=open&limit=5" in source


def test_memory_graph_smoke_validates_temporal_contract_values() -> None:
    smoke = _load_memory_graph_smoke()

    valid = smoke._temporal_contract(
        [{"temporal_state": "active", "retrieval_state": "current"}],
        [{"temporal_state": "stale", "retrieval_state": "needs_refresh"}],
    )
    assert valid["has_fields"] is True
    assert valid["valid_retrieval_states"] is True
    assert valid["retrieval_states"] == ["current", "needs_refresh"]

    invalid_state = smoke._temporal_contract(
        [{"temporal_state": "active", "retrieval_state": "unknown"}],
        [],
    )
    assert invalid_state["has_fields"] is True
    assert invalid_state["valid_retrieval_states"] is False

    missing_field = smoke._temporal_contract(
        [{"temporal_state": "active"}],
        [],
    )
    assert missing_field["has_fields"] is False


def test_semantic_memory_public_execute_revoke_migration_is_guarded() -> None:
    source = _script_text(PUBLIC_REVOKE_MIGRATION)

    assert (
        "REVOKE EXECUTE ON FUNCTION public.save_semantic_memory_with_provenance"
        in source
    )
    assert "REVOKE EXECUTE ON FUNCTION public.review_semantic_memory" in source
    assert "acl.grantee = 0" in source
    assert "semantic memory SECDEF public revoke postcheck failed" in source


def test_semantic_memory_owner_grant_migration_is_guarded() -> None:
    source = _script_text(OWNER_GRANT_MIGRATION)

    assert "TO jarvis_alpha_owner" in source
    assert "has_function_privilege('jarvis_alpha_owner'" in source
    assert "acl.grantee = 0" in source
    assert "semantic memory SECDEF owner grant postcheck failed" in source
