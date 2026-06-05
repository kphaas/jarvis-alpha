from brain.agents.manual_run import manual_run_eligibility
from brain.agents.porchlight import DEFAULT_PORCHLIGHT_INTERVAL_SECONDS
from brain.agents.chatops_smoke import format_chatops_smoke_message
from brain.agents.network_watchdog import (
    client_keys,
    firmware_drift,
    network_events_from_snapshot,
    quarantine_recommendation,
    wan_failover_health,
)
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


def test_sweep_detects_wan_degraded_and_new_clients():
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


def test_sweep_does_not_alert_new_clients_without_baseline():
    events = network_events_from_snapshot(
        {
            "wan": {"wan_status": "up"},
            "clients": {"clients": [{"mac": "aa:bb:cc:00:00:01"}]},
            "health": {"status": "ok"},
        },
        {},
    )

    assert events == []


def test_sweep_detects_unifi_tls_pin_drift():
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


def test_sweep_debounces_repeated_degraded_health_and_tls_pin():
    snapshot = {
        "wan": {"wan_status": "unknown"},
        "clients": {"clients": []},
        "health": {
            "status": "degraded",
            "errors": ["offline_devices:1"],
            "tls": {
                "verification": "ca_cert",
                "public_key_pin_configured": False,
            },
        },
    }

    events = network_events_from_snapshot(
        snapshot,
        {
            "last_wan_status": "unknown",
            "last_health_signature": "degraded|offline_devices:1",
            "last_tls_public_key_pin_configured": False,
        },
    )

    assert events == []


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


def test_sweep_quarantine_recommendation_is_read_only():
    recommendation = quarantine_recommendation(
        {"clients": [{"mac": "aa"}, {"mac": "bb"}]},
        {"last_client_keys": ["aa"]},
    )

    assert recommendation["status"] == "review"
    assert recommendation["unknown_client_keys"] == ["bb"]
    assert recommendation["mutates_network"] is False


def test_sweep_detects_firmware_drift_and_emits_once():
    drift = firmware_drift(
        {
            "devices": [
                {
                    "name": "Office AP",
                    "kind": "ap",
                    "version": "1.0",
                    "upgradeable": True,
                    "target_version": "1.1",
                }
            ]
        }
    )
    events = network_events_from_snapshot(
        {
            "wan": {"wan_status": "up"},
            "clients": {"clients": []},
            "health": {"status": "ok"},
            "firmware_drift": drift,
        },
        {},
    )

    assert drift["status"] == "warn"
    assert [event.event_type for event in events] == ["network.firmware_drift"]


def test_sweep_wan_failover_warns_when_secondary_absent():
    result = wan_failover_health({"wan_status": "up"})
    events = network_events_from_snapshot(
        {
            "wan": {"wan_status": "up"},
            "clients": {"clients": []},
            "health": {"status": "ok"},
            "wan_failover_health": result,
        },
        {},
    )

    assert result["status"] == "warn"
    assert [event.event_type for event in events] == ["network.wan_failover_health"]
    assert events[0].severity == "warning"


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


def test_agent_manual_run_route_passes_to_route_local_guard():
    classes = classify_route("POST", "/v1/agents/chatops_smoke/run")

    assert classes == ["write", "security_write"]
    assert determine_risk_tier(classes) == "T2"


def test_agent_enable_disable_routes_remain_admin_classified():
    enable_classes = classify_route("POST", "/v1/agents/chatops_smoke/enable")
    disable_classes = classify_route("POST", "/v1/agents/chatops_smoke/disable")

    assert "admin" in enable_classes
    assert determine_risk_tier(enable_classes) == "T5"
    assert "admin" in disable_classes
    assert determine_risk_tier(disable_classes) == "T5"


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
            "agent_id": "sweep",
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


def test_porchlight_default_schedule_is_daily():
    assert DEFAULT_PORCHLIGHT_INTERVAL_SECONDS == 86400
