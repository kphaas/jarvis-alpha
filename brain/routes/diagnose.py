"""AI diagnosis for log errors — local Ollama or Claude via Gateway."""

from __future__ import annotations

import asyncio
import json
import subprocess

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

from brain.config.node_addresses import GATEWAY_URL

diagnose_router = APIRouter()

JARVIS_CONTEXT = """You are a JARVIS infrastructure diagnostic assistant. JARVIS is a private multi-node AI system:
- Brain (Mac Studio M2 Ultra): FastAPI :8186, Postgres 16, Ollama, orchestrator
- Gateway (Mac Mini): Cloud LLM proxy (Claude/Perplexity/Gemini), sole internet egress
- Endpoint (Mac Mini M1): React UI :4100 via nginx, presentation only
- Sandbox (Mac Mini M4): jarvis-forge dev pipeline :5001
All nodes on Tailscale VPN mesh. Services managed via LaunchAgents. Logs are structured JSON shipped via Fluent Bit to Grafana Loki on Brain.

Common issues:
- Port conflicts: stale processes holding ports after restart
- __pycache__: stale bytecode causes import errors after code changes
- Tailscale cert expiry: certs expire Jun 18 2026
- JWT auth: missing Bearer token on API calls
- Fluent Bit: connection refused if Loki restarts
- nginx: bind errors if old worker processes linger

Given a log error, diagnose the root cause and provide a specific fix with exact commands to run. Always specify which node to run commands on."""


class DiagnoseRequest(BaseModel):
    entry: dict
    context_entries: list[dict] = Field(default_factory=list)
    provider: str = "local"  # "local" or "claude"


@diagnose_router.post("/v1/logs/diagnose")
async def diagnose_error(req: DiagnoseRequest = Body(...)):
    # Build the prompt
    error_text = json.dumps(req.entry, indent=2)
    context_text = ""
    if req.context_entries:
        context_text = "\n\nRelated logs (same trace_id or timeframe):\n"
        for e in req.context_entries[:10]:
            context_text += f"  [{e.get('level', '?')}] {e.get('service', '?')}: {e.get('message', '')}\n"

    user_prompt = f"Diagnose this error and tell me exactly how to fix it:\n\n{error_text}{context_text}"

    if req.provider == "local":
        return await _diagnose_ollama(user_prompt)
    elif req.provider == "claude":
        return await _diagnose_claude(user_prompt)
    else:
        return {"status": "error", "diagnosis": f"Unknown provider: {req.provider}"}


async def _diagnose_ollama(prompt: str) -> dict:
    """Call Ollama llama3.1:8b on Brain localhost."""
    payload = json.dumps(
        {
            "model": "llama3.1:8b",
            "messages": [
                {"role": "system", "content": JARVIS_CONTEXT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 500},
        }
    )

    cmd = [
        "curl",
        "-s",
        "--max-time",
        "60",
        "http://127.0.0.1:11434/api/chat",
        "-H",
        "Content-Type: application/json",
        "-d",
        payload,
    ]

    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=65
        )
        if result.returncode != 0:
            return {
                "status": "error",
                "diagnosis": f"Ollama call failed: {result.stderr}",
            }

        data = json.loads(result.stdout)
        diagnosis = data.get("message", {}).get("content", "No response from Ollama")
        return {"status": "success", "provider": "local", "diagnosis": diagnosis}
    except Exception as e:
        return {"status": "error", "diagnosis": str(e)}


async def _diagnose_claude(prompt: str) -> dict:
    """Call Claude via Gateway cloud adapter."""
    payload = json.dumps(
        {
            "provider": "claude",
            "payload": {
                "model": "claude-haiku-4-5-20251001",
                "system": JARVIS_CONTEXT,
                "messages": [
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 1000,
            },
        }
    )

    gateway_url = f"{GATEWAY_URL}/v1/cloud/call"

    cmd = [
        "curl",
        "-sS",
        "--max-time",
        "30",
        gateway_url,
        "-H",
        "Content-Type: application/json",
        "-d",
        payload,
    ]

    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=35
        )
        if result.returncode != 0:
            return {
                "status": "error",
                "diagnosis": f"Gateway call failed: {result.stderr}",
            }

        data = json.loads(result.stdout)
        # Gateway returns {"provider": "claude", "result": {<anthropic response>}}
        api_result = data.get("result", {})
        content = api_result.get("content", [])
        if isinstance(content, list):
            diagnosis = "\n".join(
                block.get("text", str(block))
                for block in content
                if block.get("type") == "text"
            )
        else:
            diagnosis = str(content) if content else "No response"
        if not diagnosis:
            diagnosis = "No response from Claude"
        return {"status": "success", "provider": "claude", "diagnosis": diagnosis}
    except Exception as e:
        return {"status": "error", "diagnosis": str(e)}
