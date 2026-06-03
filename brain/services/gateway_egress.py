"""Brain → Gateway egress proxy helpers.

Brain must not call public internet hosts directly. For non-LLM public APIs,
Brain sends a small authorized request to Gateway and Gateway performs the
internet call.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from typing import Any


class GatewayEgressError(RuntimeError):
    pass


def _gateway_base() -> str:
    return os.environ.get(
        "ALPHA_GATEWAY_URL",
        "https://jarvis-gateway.tail40ed36.ts.net:8283",
    ).rstrip("/")


def _service_token() -> str:
    for name in ("GATEWAY_TOKEN", "ALPHA_BRAIN_SERVICE_TOKEN", "ALPHA_SERVICE_TOKEN"):
        token = os.environ.get(name, "").strip()
        if token:
            return token
    raise GatewayEgressError("Gateway service token is not configured")


def call_gateway_proxy_sync(
    path: str,
    payload: dict[str, Any],
    *,
    timeout_s: int = 60,
) -> dict[str, Any]:
    url = f"{_gateway_base()}/v1/cloud/{path.lstrip('/')}"
    args = [
        "curl",
        "-sS",
        "-m",
        str(timeout_s),
        "-X",
        "POST",
        "-H",
        "Content-Type: application/json",
        "-H",
        f"Authorization: Bearer {_service_token()}",
        "-d",
        json.dumps(payload),
        url,
    ]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_s + 5,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GatewayEgressError(f"Gateway proxy timed out after {timeout_s}s") from exc
    except OSError as exc:
        raise GatewayEgressError(f"Gateway proxy failed to run curl: {exc}") from exc

    body = proc.stdout.strip()
    if proc.returncode != 0:
        raise GatewayEgressError(
            f"Gateway proxy curl rc={proc.returncode}: {body[:200]}"
        )
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise GatewayEgressError(
            f"Gateway proxy returned non-JSON: {body[:200]}"
        ) from exc
    if isinstance(parsed, dict) and "detail" in parsed:
        raise GatewayEgressError(f"Gateway proxy error: {parsed['detail']}")
    if not isinstance(parsed, dict):
        raise GatewayEgressError("Gateway proxy returned non-object JSON")
    return parsed


async def call_gateway_proxy(
    path: str,
    payload: dict[str, Any],
    *,
    timeout_s: int = 60,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        call_gateway_proxy_sync,
        path,
        payload,
        timeout_s=timeout_s,
    )
