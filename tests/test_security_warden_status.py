from brain.routes.security import _warden_hardening_state


def test_warden_hardening_state_uses_registry_metadata():
    result = _warden_hardening_state(
        {
            "metadata": {
                "active_network_hardening": "service_tls_cert_renewal",
                "next_network_hardening": "service_tls_cert_renewal",
            }
        },
        [
            {
                "agent_id": "sweep",
                "metadata": {"active_hardening": "service_tls_cert_renewal"},
            }
        ],
    )

    assert result == {
        "active_hardening": "service_tls_cert_renewal",
        "next_hardening": "service_tls_cert_renewal",
    }


def test_warden_hardening_state_falls_back_to_sweep_metadata():
    result = _warden_hardening_state(
        None,
        [
            {
                "agent_id": "sweep",
                "metadata": {"active_hardening": "service_tls_cert_renewal"},
            }
        ],
    )

    assert result == {
        "active_hardening": "service_tls_cert_renewal",
        "next_hardening": "service_tls_cert_renewal",
    }
