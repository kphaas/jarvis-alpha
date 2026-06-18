#!/usr/bin/env python3
"""Cheap read-only smoke for Alpha Settings without printing PI or secrets."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shlex
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://jarvis-brain.tail40ed36.ts.net:8186"
DEFAULT_ENDPOINT_URL = "https://jarvis-endpoint.tail40ed36.ts.net:4100/settings"
DEFAULT_TOKEN_SSH_TARGET = "jarvisbrain@jarvis-brain.tail40ed36.ts.net"


@dataclass(frozen=True)
class SmokeCheck:
    ok: bool
    status: str
    detail: str
    metadata: dict[str, object]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("SETTINGS_SMOKE_BASE_URL")
        or os.getenv("ALPHA_BASE_URL")
        or DEFAULT_BASE_URL,
    )
    parser.add_argument(
        "--endpoint-url",
        default=os.getenv("SETTINGS_SMOKE_ENDPOINT_URL", DEFAULT_ENDPOINT_URL),
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("SETTINGS_SMOKE_PROFILE", "ken"),
    )
    parser.add_argument(
        "--token",
        default=os.getenv("SETTINGS_SMOKE_TOKEN"),
        help="Explicit bearer token. If omitted, the script generates a smoke token.",
    )
    parser.add_argument(
        "--token-ssh-target",
        default=os.getenv(
            "SETTINGS_SMOKE_TOKEN_SSH_TARGET",
            DEFAULT_TOKEN_SSH_TARGET,
        ),
        help=(
            "SSH target used to generate a target-side smoke token when "
            "SETTINGS_SMOKE_TOKEN is not set."
        ),
    )
    parser.add_argument(
        "--allow-missing-home-location",
        action="store_true",
        default=os.getenv("SETTINGS_SMOKE_ALLOW_MISSING_HOME_LOCATION", "0") == "1",
        help="Allow /v1/settings/web-agent to be healthy before home location exists.",
    )
    parser.add_argument(
        "--skip-endpoint",
        action="store_true",
        default=os.getenv("SETTINGS_SMOKE_SKIP_ENDPOINT", "0") == "1",
        help="Skip the public Endpoint /settings route check.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    token = args.token or _smoke_token(
        profile=args.profile,
        base_url=base_url,
        token_ssh_target=args.token_ssh_target,
    )

    results: dict[str, object] = {}

    health = _call_json("GET", base_url, "/health", token)
    results["brain_health"] = _check_brain_health(health)

    identity = _call_json("GET", base_url, "/v1/settings/identity", token)
    results["identity_settings"] = _check_identity_settings(identity)

    web_agent = _call_json("GET", base_url, "/v1/settings/web-agent", token)
    results["web_agent_settings"] = _check_web_agent_settings(
        web_agent,
        require_home_location=not args.allow_missing_home_location,
    )

    if not args.skip_endpoint:
        page = _call_text(args.endpoint_url)
        results["endpoint_settings_route"] = _check_endpoint_settings_route(page)

    checks = {
        name: asdict(check)
        for name, check in results.items()
        if isinstance(check, SmokeCheck)
    }
    failures = [
        name
        for name, check in results.items()
        if isinstance(check, SmokeCheck) and not check.ok
    ]
    if failures:
        _emit({"status": "failed", "failed_checks": failures, "checks": checks})
        return 2

    _emit({"status": "passed", "checks": checks})
    return 0


def _check_brain_health(payload: dict[str, object]) -> SmokeCheck:
    status = str(payload.get("status", "missing"))
    ok = status == "ok"
    return SmokeCheck(
        ok=ok,
        status="ok" if ok else "failed",
        detail="Brain health is ok." if ok else "Brain health is not ok.",
        metadata={"health_status": status},
    )


def _check_identity_settings(payload: dict[str, object]) -> SmokeCheck:
    profiles_payload = payload.get("profiles")
    relationships_payload = payload.get("relationships")
    personal_data_payload = payload.get("personal_data")
    profiles = profiles_payload if isinstance(profiles_payload, list) else []
    relationships = (
        relationships_payload if isinstance(relationships_payload, list) else []
    )
    personal_data = (
        personal_data_payload if isinstance(personal_data_payload, dict) else {}
    )
    classification = personal_data.get("storage_classification")
    ok = (
        bool(profiles)
        and isinstance(relationships_payload, list)
        and classification == "alpha_db_personal_settings"
    )
    profiles_with_personal_data = [
        profile
        for profile in profiles
        if isinstance(profile, dict) and isinstance(profile.get("personal_data"), dict)
    ]
    home_address = personal_data.get("home_address")
    return SmokeCheck(
        ok=ok,
        status="ok" if ok else "failed",
        detail="Identity settings contract is present."
        if ok
        else "Identity settings contract is incomplete.",
        metadata={
            "profile_count": len(profiles),
            "relationship_count": len(relationships),
            "profiles_with_personal_data_count": len(profiles_with_personal_data),
            "storage_classification": classification,
            "home_address_present": isinstance(home_address, dict),
        },
    )


def _check_web_agent_settings(
    payload: dict[str, object],
    *,
    require_home_location: bool,
) -> SmokeCheck:
    location_payload = payload.get("home_location")
    location = location_payload if isinstance(location_payload, dict) else None
    classification = payload.get("storage_classification")
    location_present = location is not None
    coordinate_pair_present = bool(
        location
        and location.get("latitude") is not None
        and location.get("longitude") is not None
    )
    ok = classification == "alpha_db_personal_settings" and (
        not require_home_location or (location_present and coordinate_pair_present)
    )
    return SmokeCheck(
        ok=ok,
        status="ok" if ok else "failed",
        detail="Web-agent settings contract is present."
        if ok
        else "Web-agent settings contract is incomplete.",
        metadata={
            "storage_classification": classification,
            "home_location_present": location_present,
            "home_location_coordinates_present": coordinate_pair_present,
            "home_location_city_present": bool(location and location.get("city")),
            "home_location_region_present": bool(location and location.get("region")),
            "home_location_postal_code_present": bool(
                location and location.get("postal_code")
            ),
        },
    )


def _check_endpoint_settings_route(page: str) -> SmokeCheck:
    ok = '<div id="root"' in page or "<div id='root'" in page
    return SmokeCheck(
        ok=ok,
        status="ok" if ok else "failed",
        detail="Endpoint Settings route serves the React app."
        if ok
        else "Endpoint Settings route did not serve the React app.",
        metadata={"react_root_present": ok, "response_bytes": len(page.encode())},
    )


def _smoke_token(
    *,
    profile: str,
    base_url: str,
    token_ssh_target: str | None,
) -> str:
    token = os.getenv("SETTINGS_SMOKE_TOKEN")
    if token:
        return token

    if _is_local_base_url(base_url):
        return _local_smoke_token(profile=profile)

    if token_ssh_target:
        generated = subprocess.check_output(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "StrictHostKeyChecking=no",
                token_ssh_target,
                "cd ~/jarvis-alpha && .venv/bin/python scripts/gen_test_token.py "
                f"{shlex.quote(profile)}",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if not generated:
            raise RuntimeError("target token generation returned no token")
        return generated

    raise RuntimeError(
        "set SETTINGS_SMOKE_TOKEN or SETTINGS_SMOKE_TOKEN_SSH_TARGET for settings smoke"
    )


def _local_smoke_token(*, profile: str) -> str:
    repo_root = Path(__file__).resolve().parents[1]
    python_bin = os.getenv("PYTHON_BIN", str(repo_root / ".venv/bin/python"))
    generated = subprocess.check_output(
        [python_bin, str(repo_root / "scripts/gen_test_token.py"), profile],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
    if not generated:
        raise RuntimeError("test token generation returned no token")
    return generated


def _is_local_base_url(base_url: str) -> bool:
    return (
        "://localhost" in base_url
        or "://127.0.0.1" in base_url
        or "://[::1]" in base_url
    )


def _call_json(
    method: str,
    base_url: str,
    path: str,
    token: str,
) -> dict[str, object]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(
            request,
            context=ssl._create_unverified_context(),
            timeout=20,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {detail}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{method} {path} returned non-object JSON")
    return payload


def _call_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"Accept": "text/html"})
    try:
        with urllib.request.urlopen(
            request,
            context=ssl._create_unverified_context(),
            timeout=20,
        ) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"GET {url} failed: HTTP {exc.code} {detail}") from exc


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
