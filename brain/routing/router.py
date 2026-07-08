import json
import subprocess
import asyncio

from brain.core.config import GATEWAY_URL, OLLAMA_URL
from brain.core.models import (
    CLAUDE_SMART,
    GEMINI_FAST,
    LOCAL_CHAT,
    PERPLEXITY_FAST,
)
from brain.routing.council import CouncilOrchestrator
from brain.routing.strategy import select_chat_strategy

COUNCIL_TRIGGER = "manual"  # future values: "complexity", "topic"


async def route(prompt: str, mode: str = "auto") -> dict:
    if mode == "council":
        result = await CouncilOrchestrator().run(prompt)
        result.update(
            select_chat_strategy(prompt=prompt, requested_model=mode).metadata()
        )
        return result

    strategy_plan = select_chat_strategy(prompt=prompt, requested_model=mode)
    mode = strategy_plan.route_mode
    metadata = strategy_plan.metadata()

    def _curl_gateway(endpoint: str, payload: dict) -> dict:
        cmd = [
            "curl",
            "-s",
            "-X",
            "POST",
            f"{GATEWAY_URL}{endpoint}",
            "-H",
            "Content-Type: application/json",
            "-d",
            json.dumps(payload),
            "--max-time",
            "30",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
        if result.returncode != 0:
            raise RuntimeError(f"curl failed: {result.stderr}")
        return json.loads(result.stdout)

    try:
        if mode == "local":
            cmd = [
                "curl",
                "-s",
                "-X",
                "POST",
                f"{OLLAMA_URL}/api/generate",
                "-H",
                "Content-Type: application/json",
                "-d",
                json.dumps({"model": LOCAL_CHAT, "prompt": prompt, "stream": False}),
                "--max-time",
                "60",
            ]
            result = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, timeout=65
            )
            text = json.loads(result.stdout).get("response", "").strip()
            return {"mode": "local", "result": text, **metadata}

        if mode == "claude":
            raw = await asyncio.to_thread(
                _curl_gateway,
                "/v1/cloud/call",
                {
                    "provider": "claude",
                    "payload": {
                        "model": CLAUDE_SMART,
                        "max_tokens": 1024,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                },
            )
            try:
                text = raw["result"]["content"][0]["text"]
            except (KeyError, IndexError, TypeError):
                text = ""
            return {"mode": "claude", "result": text, **metadata}

        if mode == "gemini":
            raw = await asyncio.to_thread(
                _curl_gateway,
                "/v1/cloud/call",
                {
                    "provider": "gemini",
                    "payload": {
                        "model": GEMINI_FAST,
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"maxOutputTokens": 1024},
                    },
                },
            )
            try:
                text = raw["result"]["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError):
                text = ""
            return {"mode": "gemini", "result": text, **metadata}

        if mode == "perplexity":
            raw = await asyncio.to_thread(
                _curl_gateway,
                "/v1/cloud/call",
                {
                    "provider": "perplexity",
                    "payload": {
                        "model": PERPLEXITY_FAST,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                },
            )
            try:
                text = raw["result"]["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                text = ""
            return {"mode": "perplexity", "result": text, **metadata}

        return {
            "mode": mode,
            "result": "",
            "error": f"unknown mode: {mode}",
            **metadata,
        }

    except Exception as e:
        return {"mode": mode, "result": "", "error": str(e), **metadata}
