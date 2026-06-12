from __future__ import annotations

import json
import re
from pathlib import Path

from brain.services.key_rotation import KEY_FORMAT_RULES
from scripts.service_identity import TOKEN_LIFETIME_DAYS


def test_keyturner_inventory_covers_rotatable_provider_keys():
    config = json.loads(
        Path("scripts/secrets_rotation.json").read_text(encoding="utf-8")
    )
    secrets = config["secrets"]

    for key_name in KEY_FORMAT_RULES:
        assert key_name in secrets
        assert secrets[key_name]["managed_by"] == "keyturner"
        assert secrets[key_name]["rotation_path"] == "security_tab_gateway_proxy"


def test_keyturner_inventory_covers_security_operational_keys():
    config = json.loads(
        Path("scripts/secrets_rotation.json").read_text(encoding="utf-8")
    )
    secrets = config["secrets"]
    expected = {
        "ALPHA_BUDDY_TOKEN",
        "ALPHA_BRAIN_SERVICE_TOKEN",
        "ALPHA_SERVICE_TOKEN_GATEWAY",
        "ALPHA_SERVICE_TOKEN_ENDPOINT",
        "ALPHA_SERVICE_TOKEN_SANDBOX",
        "ALPHA_GMAIL_REFRESH_TOKEN",
        "ALPHA_GMAIL_CLIENT_SECRET",
        "ALPHA_SWEEP_REPORT_SECRET",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_TUNNEL_TOKEN",
        "MATTERMOST_BOT_TOKEN",
        "MATTERMOST_WEBHOOK_URL_SECURITY_ALERTS",
        "PUSHOVER_APP_TOKEN",
        "JARVIS_FAMILY_SMOKE_PIN",
        "JARVIS_FAMILY_EXTERNAL_SMOKE_PIN",
    }

    missing = expected - set(secrets)
    assert missing == set()
    assert all(secrets[name]["managed_by"] == "keyturner" for name in expected)


def test_service_token_lifetime_matches_keyturner_rotation_policy():
    config = json.loads(
        Path("scripts/secrets_rotation.json").read_text(encoding="utf-8")
    )
    secrets = config["secrets"]
    service_tokens = {
        "ALPHA_BUDDY_TOKEN",
        "ALPHA_BRAIN_SERVICE_TOKEN",
        "ALPHA_SERVICE_TOKEN_GATEWAY",
        "ALPHA_SERVICE_TOKEN_ENDPOINT",
        "ALPHA_SERVICE_TOKEN_SANDBOX",
    }

    assert TOKEN_LIFETIME_DAYS == 7
    assert {name: secrets[name]["rotation_days"] for name in service_tokens} == {
        name: TOKEN_LIFETIME_DAYS for name in service_tokens
    }


def test_keyturner_reconcile_migration_covers_current_config():
    config = json.loads(
        Path("scripts/secrets_rotation.json").read_text(encoding="utf-8")
    )
    configured = set(config["secrets"])
    migrations = [
        path.read_text(encoding="utf-8")
        for path in sorted(
            Path("brain/db/migrations").glob("*keyturner*rotation*reconcile*.sql")
        )
    ]
    assert migrations

    inventoried: set[str] = set()
    postflight_expected: set[str] = set()
    for migration in migrations:
        inventory_match = re.search(
            r"inventory\(secret_name.*?\)\s+AS\s+\(\s+VALUES(?P<body>.*?)\)\s*INSERT",
            migration,
            re.DOTALL,
        )
        assert inventory_match is not None
        inventoried.update(
            re.findall(r"\('([A-Z0-9_]+)'", inventory_match.group("body"))
        )

        expected_match = re.search(
            r"VALUES(?P<body>.*?)\)\s+AS expected\(secret_name\)",
            migration,
            re.DOTALL,
        )
        assert expected_match is not None
        postflight_expected.update(
            re.findall(r"\('([A-Z0-9_]+)'\)", expected_match.group("body"))
        )

    assert inventoried == configured
    assert postflight_expected == configured
    assert all("value_hash" in migration for migration in migrations)
    assert all("'skipped'" in migration for migration in migrations)
    assert all("keyturner@reconcile" in migration for migration in migrations)
