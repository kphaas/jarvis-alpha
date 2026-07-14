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

import os
from collections.abc import Mapping
from typing import Any

import httpx

from brain.routing.generation_policy import ChatGenerationPolicy

_GENERATE_PATH = "/api/generate"
_DEFAULT_TIMEOUT_S = 60.0
_DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
_DETERMINISTIC_TEMPERATURE = 0.0
_DETERMINISTIC_SEED = 42


def _ollama_url() -> str:
    return os.environ.get("ALPHA_OLLAMA_URL", _DEFAULT_OLLAMA_URL).rstrip("/")


async def generate(
    *,
    model: str,
    prompt: str,
    format: str | Mapping[str, object] | None = None,
    options: dict[str, Any] | None = None,
    generation_policy: ChatGenerationPolicy | None = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Call local Ollama ``/api/generate`` (stream=False) and return raw JSON.

    Args:
        model: Ollama model tag (caller is responsible for any whitelist).
        prompt: The prompt text.
        format: Optional Ollama ``format`` passthrough (``"json"`` or a schema).
        options: Optional Ollama ``options`` map (e.g. temperature, num_predict).
        generation_policy: Provider-neutral controls translated by this adapter.
        timeout_s: Request timeout in seconds.

    Returns:
        The parsed Ollama response dict (includes ``response`` and, when
        provided by the model, ``prompt_eval_count`` / ``eval_count``).

    Raises:
        httpx.HTTPError: On transport failure or a non-2xx status.
    """
    payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
    effective_format = format
    effective_options = dict(options or {})
    if generation_policy is not None:
        if generation_policy.json_mode:
            effective_format = "json"
        if generation_policy.deterministic:
            effective_options.update(
                {
                    "temperature": _DETERMINISTIC_TEMPERATURE,
                    "seed": _DETERMINISTIC_SEED,
                }
            )
    if effective_format is not None:
        payload["format"] = effective_format
    if effective_options:
        payload["options"] = effective_options

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(f"{_ollama_url()}{_GENERATE_PATH}", json=payload)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data
