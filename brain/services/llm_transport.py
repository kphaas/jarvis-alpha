"""LLM transport — Brain → Gateway /v1/cloud/call via curl.

JARVIS invariant: never httpx against Tailscale TLS.
Reuses existing Gateway cost pipeline — cost tracking happens automatically
on Gateway side via cost_emitter.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess

log = logging.getLogger(__name__)


class GatewayTransportError(Exception):
    pass


def _gateway_url() -> str:
    base = os.environ.get(
        "ALPHA_GATEWAY_URL",
        "https://jarvis-gateway.tail40ed36.ts.net:8283",
    )
    return f"{base}/v1/cloud/call"


def _service_token() -> str:
    tok = os.environ.get("ALPHA_BRAIN_SERVICE_TOKEN", "").strip()
    if not tok:
        raise GatewayTransportError(
            "ALPHA_BRAIN_SERVICE_TOKEN not set in environment — cannot call Gateway"
        )
    return tok


def _post_sync(
    url: str, payload: dict, token: str, timeout_s: int = 60
) -> tuple[int, str]:
    args = [
        "curl",
        "-sk",
        "-m",
        str(timeout_s),
        "-X",
        "POST",
        "-H",
        "Content-Type: application/json",
        "-H",
        f"Authorization: Bearer {token}",
        "-d",
        json.dumps(payload),
        url,
    ]
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout_s + 5
        )
        return result.returncode, result.stdout
    except subprocess.TimeoutExpired:
        return 124, '{"error":"timeout"}'
    except Exception as e:
        return 1, json.dumps({"error": str(e)})


async def call_gateway_cloud(
    provider: str,
    model: str,
    system_prompt: str,
    user_message: str,
    max_tokens: int = 2000,
    temperature: float = 0.3,
    timeout_s: int = 60,
) -> str:
    """POST to Gateway /v1/cloud/call, return LLM text output.

    Raises GatewayTransportError on any failure.
    """
    payload = {
        "provider": provider,
        "model": model,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    url = _gateway_url()
    token = _service_token()

    rc, body = await asyncio.to_thread(_post_sync, url, payload, token, timeout_s)

    if rc != 0:
        log.error("llm_transport curl rc=%d body=%s", rc, body[:500])
        raise GatewayTransportError(f"curl failed rc={rc}: {body[:200]}")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as e:
        raise GatewayTransportError(f"Gateway returned non-JSON: {body[:200]}") from e

    if "error" in parsed:
        raise GatewayTransportError(f"Gateway error: {parsed['error']}")

    text = parsed.get("content") or parsed.get("text") or parsed.get("completion")
    if not isinstance(text, str):
        raise GatewayTransportError(
            f"Gateway response missing text field: {list(parsed.keys())}"
        )

    log.info(
        "llm_transport success provider=%s model=%s response_len=%d",
        provider,
        model,
        len(text),
    )
    return text
