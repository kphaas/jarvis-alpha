from __future__ import annotations

import urllib.error

import scripts.power_sampler as power_sampler


class _FakeResponse:
    def read(self):
        return b""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_power_sampler_adds_bearer_service_token(monkeypatch):
    seen = {}
    monkeypatch.setenv("ALPHA_SERVICE_TOKEN", "node-service-token")
    monkeypatch.setenv("JARVIS_ALPHA_BRAIN_URL", "https://brain.example")
    monkeypatch.setattr(power_sampler, "BRAIN_URL", "https://brain.example")

    def fake_urlopen(req, context=None, timeout=60):
        seen["url"] = req.full_url
        seen["authorization"] = req.get_header("Authorization")
        seen["content_type"] = req.get_header("Content-type")
        return _FakeResponse()

    monkeypatch.setattr(power_sampler.urllib.request, "urlopen", fake_urlopen)

    power_sampler.post_reading(12.5, 4.0, "psutil")

    assert seen["url"] == "https://brain.example/v1/metrics/power"
    assert seen["authorization"] == "Bearer node-service-token"
    assert seen["content_type"] == "application/json"


def test_power_sampler_does_not_print_or_crash_without_token(monkeypatch, capsys):
    monkeypatch.delenv("ALPHA_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("ALPHA_BRAIN_SERVICE_TOKEN", raising=False)
    monkeypatch.setattr(power_sampler, "_read_secret_file", lambda name: "")

    def fake_urlopen(req, context=None, timeout=60):
        assert req.get_header("Authorization") is None
        raise urllib.error.HTTPError(
            req.full_url,
            401,
            "unauthorized",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(power_sampler.urllib.request, "urlopen", fake_urlopen)

    power_sampler.post_reading(12.5, 4.0, "psutil")

    out = capsys.readouterr().out
    assert "post_reading error:" in out
    assert "ALPHA_SERVICE_TOKEN" not in out
    assert "ALPHA_BRAIN_SERVICE_TOKEN" not in out
