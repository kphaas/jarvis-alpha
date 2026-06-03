from gateway.routes import unifi


def _secret_loader(values: dict[str, str]):
    def _load(key: str) -> str:
        try:
            return values[key]
        except KeyError as exc:
            raise KeyError(key) from exc

    return _load


def test_unifi_tls_config_pins_cert_for_ip_controller(monkeypatch):
    monkeypatch.setattr(unifi, "_tls_config_cache", None)
    monkeypatch.setattr(
        unifi,
        "get_secret",
        _secret_loader(
            {
                "UNIFI_BASE_URL": "https://192.168.1.1",
                "UNIFI_CA_CERT_PATH": "/Users/gate/jarvis/unifi-controller-ca.pem",
                "UNIFI_TLS_SERVER_NAME": "unifi.local",
                "UNIFI_CONNECT_HOST": "192.168.1.1",
                "UNIFI_PINNED_PUBKEY_SHA256": "abc123=",
            }
        ),
    )

    tls = unifi._unifi_tls_config()

    assert tls.request_base_url == "https://unifi.local:443"
    assert "--cacert" in tls.curl_args
    assert "/Users/gate/jarvis/unifi-controller-ca.pem" in tls.curl_args
    assert "--pinnedpubkey" in tls.curl_args
    assert "sha256//abc123=" in tls.curl_args
    assert "--connect-to" in tls.curl_args
    assert "unifi.local:443:192.168.1.1:443" in tls.curl_args
    assert tls.verification == "ca_cert+public_key_pin"


def test_unifi_tls_config_requires_ca_cert(monkeypatch):
    monkeypatch.setattr(unifi, "_tls_config_cache", None)
    monkeypatch.setattr(
        unifi,
        "get_secret",
        _secret_loader({"UNIFI_BASE_URL": "https://192.168.1.1"}),
    )

    try:
        unifi._unifi_tls_config()
    except RuntimeError as exc:
        assert "UNIFI_CA_CERT_PATH" in str(exc)
    else:
        raise AssertionError("expected UniFi TLS config to require a CA cert path")


def test_unifi_curl_uses_verified_tls_args(monkeypatch):
    monkeypatch.setattr(unifi, "_tls_config_cache", None)
    monkeypatch.setattr(
        unifi,
        "get_secret",
        _secret_loader(
            {
                "UNIFI_BASE_URL": "https://192.168.1.1",
                "UNIFI_CA_CERT_PATH": "/tmp/unifi.pem",
                "UNIFI_TLS_SERVER_NAME": "unifi.local",
                "UNIFI_CONNECT_HOST": "192.168.1.1",
            }
        ),
    )
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs

        class Proc:
            returncode = 0
            stdout = "{}"
            stderr = ""

        return Proc()

    monkeypatch.setattr(unifi.subprocess, "run", fake_run)

    unifi._curl(["https://unifi.local:443/"])

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert "-k" not in cmd
    assert "-sk" not in cmd
    assert "--insecure" not in cmd
    assert "--cacert" in cmd
    assert "--connect-to" in cmd
