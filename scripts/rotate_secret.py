#!/usr/bin/env python3
import argparse
import getpass
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "scripts" / "secrets_rotation.json"
NODE_MAP_PATH = REPO_ROOT / "scripts" / "node_ssh_map.json"
LOG_PATH = REPO_ROOT / "logs" / "secret_rotation.log"
BRAIN_SSH_FOR_DB = "jarvisbrain@jarvis-brain.tail40ed36.ts.net"
PSQL_PATH = "/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql"

APPLY_HELPER = """
import sys, os, stat, tempfile, pathlib
key = sys.argv[1]
path_str = sys.argv[2]
value = sys.stdin.read().rstrip("\\n")
path = pathlib.Path(path_str).expanduser()
if not path.exists():
    sys.exit(f"ERR: .secrets not found at {path}")
lines = path.read_text().splitlines()
new_lines = []
found = False
for line in lines:
    if line.startswith(f"{key}="):
        new_lines.append(f"{key}={value}")
        found = True
    else:
        new_lines.append(line)
if not found:
    new_lines.append(f"{key}={value}")
with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, prefix=".secrets.tmp.") as tmp:
    tmp.write("\\n".join(new_lines) + "\\n")
    tmp_path = tmp.name
os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
os.rename(tmp_path, path)
print("OK")
"""


def load_config(secret_name) -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    with NODE_MAP_PATH.open("r", encoding="utf-8") as f:
        node_map = json.load(f)

    secret_cfg = cfg.get("secrets", {}).get(secret_name)
    if not secret_cfg:
        sys.exit(f"Unknown secret: {secret_name}")

    resolved_nodes = {}
    for node in secret_cfg.get("nodes", []):
        node_info = node_map.get(node)
        if not node_info:
            sys.exit(f"Unknown node in config: {node}")
        resolved_nodes[node] = node_info

    merged = dict(secret_cfg)
    merged["name"] = secret_name
    merged["nodes"] = list(secret_cfg.get("nodes", []))
    merged["resolved_nodes"] = resolved_nodes
    merged["restarts"] = list(secret_cfg.get("restarts", []))
    merged["verify"] = dict(secret_cfg.get("verify", {"type": "none"}))
    return merged


def sha_prefix(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def remote_hash(ssh_target, secrets_path, key) -> str | None:
    cmd = (
        f"grep '^{key}=' '{secrets_path}' | cut -d= -f2- | tr -d '\\n' | "
        "shasum -a 256 | cut -c1-12"
    )
    result = subprocess.run(
        ["ssh", ssh_target, cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def backup_secrets_file(node, node_info) -> str:
    _ = node
    today = datetime.utcnow().strftime("%Y%m%d")
    path = node_info["secrets_path"]
    bak_path = f"{path}.bak.{today}"
    cmd = f"cp -n '{path}' '{bak_path}' || true"
    subprocess.run(["ssh", node_info["ssh_target"], cmd], check=True)
    return bak_path


def rollback_secrets_file(node, node_info, bak_path):
    _ = node
    path = node_info["secrets_path"]
    cmd = f"cp '{bak_path}' '{path}'"
    subprocess.run(["ssh", node_info["ssh_target"], cmd], check=True)


def update_remote_secret(node, node_info, key, value):
    _ = node
    ssh_target = node_info["ssh_target"]
    secrets_path = node_info["secrets_path"]
    remote_tmp = f"/tmp/apply_secret_{os.getpid()}.py"

    stage1 = subprocess.run(
        ["ssh", ssh_target, f"cat > '{remote_tmp}'"],
        input=APPLY_HELPER,
        text=True,
        check=False,
    )
    if stage1.returncode != 0:
        raise RuntimeError(f"failed to upload helper to {ssh_target}")

    try:
        stage2 = subprocess.run(
            ["ssh", ssh_target, "python3", remote_tmp, key, secrets_path],
            input=value,
            text=True,
            capture_output=True,
            check=False,
        )
        if stage2.returncode != 0 or "OK" not in stage2.stdout:
            stderr = stage2.stderr.strip() or stage2.stdout.strip() or "unknown error"
            raise RuntimeError(f"remote update failed on {ssh_target}: {stderr}")
    finally:
        subprocess.run(
            ["ssh", ssh_target, f"rm -f '{remote_tmp}'"],
            check=False,
        )


def restart_service(node_info, service_label, health_url) -> bool:
    ssh_target = node_info["ssh_target"]
    kick_cmd = f'launchctl kickstart -k "gui/$(id -u)/{service_label}"'
    kicked = subprocess.run(["ssh", ssh_target, kick_cmd], check=False)
    if kicked.returncode != 0:
        return False

    time.sleep(4)
    if health_url:
        probe = subprocess.run(
            ["curl", "-sk", "--max-time", "5", health_url],
            capture_output=True,
            text=True,
            check=False,
        )
        return probe.returncode == 0 and bool(probe.stdout.strip())

    stat_cmd = f"launchctl list | grep '{service_label}' | awk '{{print $1}}'"
    stat = subprocess.run(
        ["ssh", ssh_target, stat_cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    out = stat.stdout.strip()
    return out.isdigit() and int(out) > 0


def verify_github_api(value, expect_login) -> bool:
    result = subprocess.run(
        [
            "curl",
            "-s",
            "-H",
            f"Authorization: token {value}",
            "https://api.github.com/user",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return False
    return payload.get("login") == expect_login


def record_to_db(
    secret_name,
    rotation_days,
    nodes_updated,
    services_restarted,
    verify_status,
    value_hash,
) -> str:
    rotated_by = f"{getpass.getuser()}@{socket.gethostname()}"

    def esc(s):
        return str(s).replace("'", "''")

    nodes_sql = "ARRAY[" + ",".join(f"'{esc(n)}'" for n in nodes_updated) + "]::text[]"
    services_sql = (
        "ARRAY[" + ",".join(f"'{esc(s)}'" for s in services_restarted) + "]::text[]"
    )
    sql = (
        "INSERT INTO alpha_secret_rotations "
        "(secret_name, rotated_by, rotation_days, nodes_updated, services_restarted, verify_status, value_hash) "
        f"VALUES ('{esc(secret_name)}', '{esc(rotated_by)}', {int(rotation_days)}, {nodes_sql}, {services_sql}, "
        f"'{esc(verify_status)}', '{value_hash}') "
        "RETURNING id::text || ' next_due_at=' || to_char(next_due_at, 'YYYY-MM-DD\"T\"HH24:MI:SSOF');"
    )

    result = subprocess.run(
        [
            "ssh",
            BRAIN_SSH_FOR_DB,
            f'{PSQL_PATH} -d jarvis_alpha -U jarvisbrain -t -c "{sql}"',
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def log_to_file(msg):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.utcnow().isoformat()} {msg}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Rotate a configured secret across nodes."
    )
    parser.add_argument("secret_name")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    secret_name = args.secret_name
    config = load_config(secret_name)
    services_list = [f"{r['service']}@{r['node']}" for r in config["restarts"]]
    verify_type = config["verify"].get("type", "none")

    if config.get("requires_alter_role"):
        services = ", ".join(r["service"] for r in config.get("restarts", []))
        print(
            f"ERROR: {secret_name} rotation requires ALTER USER on Postgres.",
            file=sys.stderr,
        )
        print(
            "       DB-level rotation is not supported in v1 (track as TD-134).",
            file=sys.stderr,
        )
        print("       For now, rotate manually:", file=sys.stderr)
        print(
            "         1. ssh jarvisbrain@jarvis-brain.tail40ed36.ts.net",
            file=sys.stderr,
        )
        print(
            f"         2. psql -d {config.get('db_name', '?')} -c \"ALTER USER {config.get('db_role', '?')} WITH PASSWORD '<new>';\"",
            file=sys.stderr,
        )
        print(
            "         3. Update .secrets on brain (manually, with 600 perms)",
            file=sys.stderr,
        )
        print(f"         4. Restart: {services}", file=sys.stderr)
        print(
            "         5. Insert row into alpha_secret_rotations manually",
            file=sys.stderr,
        )
        sys.exit(2)

    print(f"Secret: {args.secret_name}")
    print(f"Nodes: {', '.join(config['nodes'])}")
    print(
        f"Services to restart: {', '.join(services_list) if services_list else '(none)'}"
    )
    print(f"Verify type: {verify_type}")
    sys.stdout.flush()

    if args.dry_run:
        print("Dry-run only; no changes made.")
        sys.stdout.flush()
        return

    value = getpass.getpass("Paste new value (hidden): ")
    if not value:
        print("ERROR: empty value", file=sys.stderr)
        sys.exit(1)

    if not args.yes:
        confirm = input(
            f"Confirm rotate {args.secret_name} on {len(config['nodes'])} nodes? [y/N]: "
        )
        if confirm not in ("y", "Y"):
            print("Aborted.")
            sys.exit(1)

    expected_hash = sha_prefix(value)
    updated_nodes = []
    backups = {}
    services_restarted = []
    verify_status = "skipped"

    try:
        for node in config["nodes"]:
            node_info = config["resolved_nodes"][node]
            backups[node] = backup_secrets_file(node, node_info)
            update_remote_secret(node, node_info, args.secret_name, value)
            actual = remote_hash(
                node_info["ssh_target"], node_info["secrets_path"], args.secret_name
            )
            if actual != expected_hash:
                raise RuntimeError(
                    f"hash mismatch on {node}: expected={expected_hash} got={actual}"
                )
            updated_nodes.append(node)
            print(f"  {node:<8} \u2713 updated (hash={actual})")
            sys.stdout.flush()

        for restart in config["restarts"]:
            node = restart["node"]
            service = restart["service"]
            health_url = restart.get("health_url")
            ok = restart_service(config["resolved_nodes"][node], service, health_url)
            mark = "\u2713" if ok else "\u2717"
            print(f"  restart {service} on {node} {mark}")
            sys.stdout.flush()
            if ok:
                services_restarted.append(f"{service}@{node}")

        if not args.skip_verify and verify_type == "github_api":
            ok = verify_github_api(value, config["verify"].get("expect_login"))
            verify_status = "passed" if ok else "failed"
            print(f"Verify: github_api {verify_status}")
            sys.stdout.flush()
        elif args.skip_verify:
            verify_status = "skipped"
            print("Verify: skipped by flag")
            sys.stdout.flush()
        elif verify_type == "none":
            verify_status = "skipped"
            print("Verify: none")
            sys.stdout.flush()
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        for node in updated_nodes:
            try:
                rollback_secrets_file(
                    node, config["resolved_nodes"][node], backups[node]
                )
                print(f"  rolled back {node}")
                sys.stdout.flush()
            except Exception as rb_err:
                print(f"  rollback failed on {node}: {rb_err}", file=sys.stderr)
        try:
            record_to_db(
                args.secret_name,
                config["rotation_days"],
                updated_nodes,
                services_restarted,
                "failed",
                expected_hash,
            )
        except Exception:
            pass
        sys.exit(1)

    db_result = record_to_db(
        args.secret_name,
        config["rotation_days"],
        updated_nodes,
        services_restarted,
        verify_status,
        expected_hash,
    )
    log_to_file(
        f"ROTATED secret={args.secret_name} hash={expected_hash} nodes={','.join(updated_nodes)} db={db_result}"
    )
    print(f"Done. db={db_result}")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
