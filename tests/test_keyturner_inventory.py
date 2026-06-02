from __future__ import annotations

import json
from pathlib import Path

from brain.services.key_rotation import KEY_FORMAT_RULES


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
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_TUNNEL_TOKEN",
        "MATTERMOST_BOT_TOKEN",
        "MATTERMOST_WEBHOOK_URL_SECURITY_ALERTS",
        "PUSHOVER_APP_TOKEN",
        "JARVIS_FAMILY_SMOKE_PIN",
    }

    missing = expected - set(secrets)
    assert missing == set()
    assert all(secrets[name]["managed_by"] == "keyturner" for name in expected)
