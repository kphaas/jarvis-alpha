"""Shared local-Ollama completion primitive.

Single source of truth for a synchronous (non-streaming) call to the local
Ollama ``/api/generate`` endpoint. Both the task executor (``brain/tasks/
dispatch.py``) and the internal LLM tool-call route reuse this — no duplicate
HTTP code. Localhost HTTP only (never Tailscale TLS), so ``httpx`` is fine.

The raw Ollama response is returned verbatim so callers can read token counts
(``prompt_eval_count`` / ``eval_count``). Transport / HTTP errors propagate as
exceptions — callers decide how to surface them (e.g. 503).
"""

from __future__ import annotations

from typing import Any

import httpx

from brain.core.config import OLLAMA_URL

_GENERATE_PATH = "/api/generate"
_DEFAULT_TIMEOUT_S = 60.0


async def generate(
    *,
    model: str,
    prompt: str,
    format: str | None = None,
    options: dict[str, Any] | None = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Call local Ollama ``/api/generate`` (stream=False) and return raw JSON.

    Args:
        model: Ollama model tag (caller is responsible for any whitelist).
        prompt: The prompt text.
        format: Optional Ollama ``format`` passthrough (e.g. ``"json"``).
        options: Optional Ollama ``options`` map (e.g. temperature, num_predict).
        timeout_s: Request timeout in seconds.

    Returns:
        The parsed Ollama response dict (includes ``response`` and, when
        provided by the model, ``prompt_eval_count`` / ``eval_count``).

    Raises:
        httpx.HTTPError: On transport failure or a non-2xx status.
    """
    payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
    if format is not None:
        payload["format"] = format
    if options:
        payload["options"] = options

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(f"{OLLAMA_URL}{_GENERATE_PATH}", json=payload)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data
