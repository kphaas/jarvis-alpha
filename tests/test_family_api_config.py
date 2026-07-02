from __future__ import annotations

import pytest

from brain.services.family_api import FamilyApiConfigError, family_api_base_url


def test_family_api_base_url_requires_https_tailnet_host(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_FAMILY_API_URL", "https://family.invalid")

    with pytest.raises(FamilyApiConfigError) as exc:
        family_api_base_url()

    assert exc.value.code == "family_api_url_invalid"


def test_family_api_base_url_accepts_mesh_host(monkeypatch) -> None:
    monkeypatch.setenv(
        "JARVIS_FAMILY_API_URL",
        "https://jarvis-brain.tail40ed36.ts.net:8187/",
    )

    assert family_api_base_url() == "https://jarvis-brain.tail40ed36.ts.net:8187"
