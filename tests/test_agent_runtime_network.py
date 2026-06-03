from brain.agents.manual_run import manual_run_eligibility
from brain.agents.chatops_smoke import format_chatops_smoke_message
from brain.agents.network_watchdog import client_keys, network_events_from_snapshot
from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.ports.network import NetworkClients, NetworkHealth, WanStatus


def test_unifi_payload_models_accept_gateway_shapes():
    wan = WanStatus.model_validate(
        {
            "wan_status": "up",
            "wan_down_mbps": 500.4,
            "latency_ms": 9,
            "gw_cpu_pct": 12.5,
        }
    )
    clients = NetworkClients.model_validate(
        {
            "client_count": 2,
            "wired_count": 1,
            "wireless_count": 1,
            "clients": [
                {"mac": "aa:bb:cc:00:00:01", "name": "switch", "is_wired": True}
            ],
        }
    )
    health = NetworkHealth.model_validate(
        {
            "reachable": True,
            "status": "ok",
            "wan_status": "up",
            "tls": {"verification": "ca_cert+public_key_pin"},
            "ap_count": 2,
            "switch_count": 1,
            "gateway_count": 1,
        }
    )

    assert wan.wan_status == "up"
    assert clients.clients[0].stable_key == "aa:bb:cc:00:00:01"
    assert health.ap_count == 2
    assert health.tls == {"verification": "ca_cert+public_key_pin"}


def test_network_watchdog_detects_wan_degraded_and_new_clients():
    snapshot = {
        "wan": {"wan_status": "unknown"},
        "clients": {
            "client_count": 2,
            "clients": [
                {"mac": "aa:bb:cc:00:00:01"},
                {"mac": "aa:bb:cc:00:00:02"},
            ],
        },
        "health": {"status": "ok", "errors": []},
    }

    events = network_events_from_snapshot(
        snapshot,
        {"last_client_keys": ["aa:bb:cc:00:00:01"]},
    )

    assert [event.event_type for event in events] == [
        "network.wan_degraded",
        "network.new_client",
    ]
    assert events[0].severity == "warning"


def test_network_watchdog_does_not_alert_new_clients_without_baseline():
    events = network_events_from_snapshot(
        {
            "wan": {"wan_status": "up"},
            "clients": {"clients": [{"mac": "aa:bb:cc:00:00:01"}]},
            "health": {"status": "ok"},
        },
        {},
    )

    assert events == []


def test_network_watchdog_detects_unifi_tls_pin_drift():
    events = network_events_from_snapshot(
        {
            "wan": {"wan_status": "up"},
            "clients": {"clients": []},
            "health": {
                "status": "ok",
                "tls": {
                    "verification": "ca_cert",
                    "public_key_pin_configured": False,
                },
            },
        },
        {},
    )

    assert [event.event_type for event in events] == ["network.unifi_tls_unpinned"]
    assert events[0].severity == "warning"


def test_client_keys_prefers_stable_mac_and_dedupes():
    assert client_keys(
        {
            "clients": [
                {"mac": "aa", "ip": "1.1.1.1"},
                {"mac": "aa", "ip": "1.1.1.2"},
                {"ip": "1.1.1.3"},
            ]
        }
    ) == ["1.1.1.3", "aa"]


def test_chatops_smoke_message_is_compact():
    message = format_chatops_smoke_message(
        {
            "enabled_agents": 4,
            "active_agents": 7,
            "pending_approvals": 1,
            "failed_notifications_24h": 0,
        }
    )

    assert "Agents 4/7 enabled" in message
    assert "pending approvals 1" in message


def test_unifi_health_route_is_read_classified():
    classes = classify_route("GET", "/v1/unifi/health-check")

    assert classes == ["read"]
    assert determine_risk_tier(classes) == "T1"


def test_agent_manual_run_route_is_admin_classified():
    classes = classify_route("POST", "/v1/agents/chatops_smoke/run")

    assert "admin" in classes
    assert determine_risk_tier(classes) == "T5"


def test_manual_run_requires_explicit_low_risk_enabled_opt_in():
    allowed = manual_run_eligibility(
        {
            "agent_id": "chatops_smoke",
            "status": "active",
            "enabled": True,
            "risk_tier": "T1",
            "metadata": {"manual_run_enabled": True},
        }
    )
    disabled = manual_run_eligibility(
        {
            "agent_id": "network_watchdog",
            "status": "active",
            "enabled": False,
            "risk_tier": "T1",
            "metadata": {"manual_run_enabled": True},
        }
    )
    unmapped = manual_run_eligibility(
        {
            "agent_id": "dream_mode",
            "status": "active",
            "enabled": True,
            "risk_tier": "T4",
            "metadata": {"manual_run_enabled": True},
        }
    )

    assert allowed.allowed is True
    assert disabled.reason == "agent_disabled"
    assert unmapped.reason == "manual_runner_not_registered"


def test_porchlight_manual_run_allowed_but_keyturner_is_approval_gated():
    porchlight = manual_run_eligibility(
        {
            "agent_id": "porchlight",
            "status": "active",
            "enabled": True,
            "risk_tier": "T2",
            "metadata": {"manual_run_enabled": True},
        }
    )
    keyturner = manual_run_eligibility(
        {
            "agent_id": "keyturner",
            "status": "active",
            "enabled": True,
            "risk_tier": "T4",
            "metadata": {"manual_run_enabled": False},
        }
    )

    assert porchlight.allowed is True
    assert keyturner.reason == "manual_runner_not_registered"
