import json
import os
from datetime import UTC, datetime

import pytest

from brain.privacy.redaction import (
    redact_contact_tokens,
    redact_mapping_for_log,
    redact_message_body,
    stable_hash,
)
from brain.privacy.vip_groups import VipGroupsConfigError, load_vip_groups
from brain.routes.chatops import _network_text, parse_alpha_command


def test_redaction_hashes_are_deterministic_without_raw_body():
    body = "Email ken@example.com or call 404-555-1212 about the appointment."

    redacted = redact_message_body(body, namespace="test")

    assert redacted == redact_message_body(body, namespace="test")
    assert redacted["body_redacted"] is True
    assert redacted["body_hash"].startswith("sha256:")
    assert body not in json.dumps(redacted)


def test_redaction_removes_contact_tokens_from_log_payload():
    payload = {
        "subject": "From ken@example.com",
        "body": "Private note for 404-555-1212",
        "count": 3,
    }

    redacted = redact_mapping_for_log(payload, namespace="test")

    assert "ken@example.com" not in json.dumps(redacted)
    assert "404-555-1212" not in json.dumps(redacted)
    assert "[email:" in redacted["subject"]
    assert redacted["body"]["body_hash"] == stable_hash(
        "Private note for 404-555-1212", namespace="test"
    )
    assert redacted["count"] == 3


def test_contact_redaction_handles_email_and_phone():
    redacted = redact_contact_tokens(
        "me@example.com / (404) 555-1212", namespace="test"
    )

    assert "me@example.com" not in redacted
    assert "404" not in redacted
    assert "[email:" in redacted
    assert "[phone:" in redacted


def test_vip_groups_loader_fails_closed_without_decryptor(tmp_path):
    path = tmp_path / "vip_groups.enc"
    path.write_bytes(b"encrypted")
    os.chmod(path, 0o600)

    with pytest.raises(VipGroupsConfigError, match="decryptor"):
        load_vip_groups(path=path)


def test_vip_groups_loader_rejects_group_readable_secret(tmp_path):
    path = tmp_path / "vip_groups.enc"
    path.write_bytes(b"encrypted")
    os.chmod(path, 0o644)

    with pytest.raises(VipGroupsConfigError, match="group/world"):
        load_vip_groups(path=path, decrypt=lambda raw: raw.decode())


def test_vip_groups_loader_validates_group_policy(tmp_path):
    path = tmp_path / "vip_groups.enc"
    path.write_bytes(b"encrypted")
    os.chmod(path, 0o600)
    plaintext = json.dumps(
        {
            "version": "v0.9",
            "groups": [
                {
                    "id": "family",
                    "label": "Family",
                    "members": ["ken", {"canonical_id": "wife"}],
                    "policy": {"tier": "T1", "max_per_hour": "unlimited"},
                },
                {
                    "id": "ex_meagan",
                    "label": "Ex",
                    "members": ["meagan"],
                    "policy": {
                        "tier": "T2",
                        "draft_only": True,
                        "flag_for_review": True,
                    },
                },
            ],
        }
    )

    config = load_vip_groups(path=path, decrypt=lambda _raw: plaintext)

    assert config.version == "v0.9"
    assert config.policy_for_contact("KEN").tier == "T1"
    meagan_policy = config.policy_for_contact("meagan")
    assert meagan_policy is not None
    assert meagan_policy.tier == "T2"
    assert meagan_policy.draft_only is True


def test_mattermost_network_command_parser():
    parsed = parse_alpha_command("network")

    assert parsed.name == "network"
    assert parsed.args == ()


@pytest.mark.asyncio
async def test_mattermost_network_text_is_summary_only():
    conn = _FakeNetworkConn()

    body = await _network_text(conn)

    assert "**Alpha Network**" in body
    assert "Sweep: `off`" in body
    assert "client baseline `2`" in body
    assert "network.new_client" in body
    assert "aa:bb:cc:dd:ee:ff" not in body
    assert "192.168." not in body


class _FakeNetworkConn:
    async def fetchrow(self, query: str, *args):
        if "FROM public.alpha_agents" in query:
            return {
                "agent_id": "sweep",
                "display_name": "Sweep",
                "status": "active",
                "enabled": False,
                "cadence": "30s",
                "metadata": json.dumps(
                    {
                        "last_wan_status": "up",
                        "last_health_status": "degraded",
                        "last_client_keys": [
                            "aa:bb:cc:dd:ee:ff",
                            "192.168.40.25",
                        ],
                    }
                ),
            }
        if "FROM public.alpha_agent_runs" in query:
            return {
                "status": "succeeded",
                "trigger_type": "scheduled",
                "started_at": None,
                "completed_at": datetime(2026, 5, 26, 10, 0, tzinfo=UTC),
                "error_text": None,
                "created_at": datetime(2026, 5, 26, 10, 0, tzinfo=UTC),
            }
        raise AssertionError(query)

    async def fetch(self, query: str, *args):
        if "FROM public.alpha_agent_events" in query:
            return [
                {
                    "event_type": "network.new_client",
                    "severity": "info",
                    "title": "New network client detected",
                    "notification_status": "sent",
                    "created_at": datetime(2026, 5, 26, 10, 0, tzinfo=UTC),
                }
            ]
        raise AssertionError(query)
