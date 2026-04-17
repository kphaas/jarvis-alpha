"""LLM transport — Brain → Gateway /v1/cloud/call via curl.

JARVIS invariant: never httpx against Tailscale TLS.
Reuses existing Gateway cost pipeline — cost tracking happens automatically
on Gateway side via cost_emitter.

Contract with Gateway /v1/cloud/call:
    Request:  {"provider": "<adapter-key>", "payload": {<provider-native args>}}
    Response: {"provider": "...", "result": {<provider-native response>}}

Provider names are mapped from canonical (anthropic/google/perplexity) to
Gateway's adapter registry keys (claude/gemini/perplexity).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess

log = logging.getLogger(__name__)


# Gateway adapter registry uses short family names, not provider names.
# Map canonical provider name → adapter key in gateway/routes/cloud_routes.py.
_GATEWAY_PROVIDER_MAP = {
    "anthropic": "claude",
    "google": "gemini",
    "perplexity": "perplexity",
}


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


def _extract_text(adapter_provider: str, result: dict) -> str:
    """Extract text content from provider-specific response shapes.

    Each provider's API returns a different structure. We normalize here
    so callers get plain text regardless of provider.
    """
    if adapter_provider == "claude":
        # Anthropic Messages API: {content: [{type: "text", text: "..."}], ...}
        content = result.get("content", [])
        if isinstance(content, list):
            parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return "".join(parts)
        return ""
    if adapter_provider == "gemini":
        # Google Gemini: {candidates: [{content: {parts: [{text: "..."}]}}]}
        candidates = result.get("candidates", [])
        if candidates and isinstance(candidates, list):
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                return parts[0].get("text", "")
        return ""
    if adapter_provider == "perplexity":
        # Perplexity (OpenAI-compatible): {choices: [{message: {content: "..."}}]}
        choices = result.get("choices", [])
        if choices and isinstance(choices, list):
            return choices[0].get("message", {}).get("content", "")
        return ""
    return ""


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
    adapter_provider = _GATEWAY_PROVIDER_MAP.get(provider, provider)
    envelope = {
        "provider": adapter_provider,
        "payload": {
            "model": model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
    }
    url = _gateway_url()
    token = _service_token()

    rc, body = await asyncio.to_thread(_post_sync, url, envelope, token, timeout_s)

    if rc != 0:
        log.error("llm_transport curl rc=%d body=%s", rc, body[:500])
        raise GatewayTransportError(f"curl failed rc={rc}: {body[:200]}")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as e:
        raise GatewayTransportError(f"Gateway returned non-JSON: {body[:200]}") from e

    # FastAPI validation/HTTPException shape: {"detail": ...}
    if "detail" in parsed and "result" not in parsed:
        raise GatewayTransportError(f"Gateway error: {parsed['detail']}")

    result = parsed.get("result")
    if not isinstance(result, dict):
        raise GatewayTransportError(
            f"Gateway response missing result: {list(parsed.keys())}"
        )

    text = _extract_text(adapter_provider, result)
    if not text:
        raise GatewayTransportError(
            f"Could not extract text from {adapter_provider} result: {list(result.keys())}"
        )

    log.info(
        "llm_transport success provider=%s model=%s response_len=%d",
        provider,
        model,
        len(text),
    )
    return text
