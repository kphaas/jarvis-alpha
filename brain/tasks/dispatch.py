from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_dispatch")

Handler = Callable[[dict], Awaitable[dict]]

_OLLAMA_GENERATE = "http://127.0.0.1:11434/api/generate"
_TIMEOUT_LLM = 60.0


async def call_tool_agent(step: dict) -> dict:
    # WORKER NODE UPGRADE PATH:
    # When extracting executor to worker node, replace this function body
    # with an HTTP POST to Brain API. Dispatch interface unchanged.
    return {
        "success": False,
        "error": "tool_agent not yet implemented — WORKER_UPGRADE_PATH",
    }


async def call_code_agent(step: dict) -> dict:
    # WORKER NODE UPGRADE PATH:
    # When extracting executor to worker node, replace this function body
    # with an HTTP POST to Brain API. Dispatch interface unchanged.
    try:
        config = step.get("config") or {}
        user_prompt = config.get("prompt", "")
        language = config.get("language", "python")
        system = (
            f"You are a code generation assistant. Write clean {language} code only. "
            "No explanation."
        )
        full_prompt = f"{system}\n\n{user_prompt}"
        model = "qwen2.5-coder:7b"
        async with httpx.AsyncClient(timeout=_TIMEOUT_LLM) as client:
            resp = await client.post(
                _OLLAMA_GENERATE,
                json={"model": model, "prompt": full_prompt, "stream": False},
            )
            resp.raise_for_status()
            data = resp.json()
        return {
            "success": True,
            "output": {"code": data["response"], "language": language},
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def call_memory_agent(step: dict) -> dict:
    # WORKER NODE UPGRADE PATH:
    # When extracting executor to worker node, replace this function body
    # with an HTTP POST to Brain API. Dispatch interface unchanged.
    return {
        "success": True,
        "output": {"result": "stub - not yet implemented"},
        "error": None,
    }


async def call_llm_agent(step: dict) -> dict:
    # WORKER NODE UPGRADE PATH:
    # When extracting executor to worker node, replace this function body
    # with an HTTP POST to Brain API. Dispatch interface unchanged.
    try:
        config = step.get("config") or {}
        prompt = config.get("prompt", "")
        model = config.get("model", "llama3.1:8b")
        async with httpx.AsyncClient(timeout=_TIMEOUT_LLM) as client:
            resp = await client.post(
                _OLLAMA_GENERATE,
                json={"model": model, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            data = resp.json()
        return {
            "success": True,
            "output": {"response": data["response"]},
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_ROUTERS: dict[str, Handler] = {
    "tool": call_tool_agent,
    "code": call_code_agent,
    "memory": call_memory_agent,
    "llm": call_llm_agent,
}


def _normalise_step(step: dict) -> dict:
    """Bridge old (executor+config) and new (step_type+input) schemas."""
    ex = step.get("executor") or step.get("step_type")
    step_input = step.get("input") or {}
    if not isinstance(step_input, dict):
        step_input = {}

    if ex == "llm":
        return {
            "executor": "llm",
            "config": {
                "prompt": step_input.get("prompt", ""),
                "model": step_input.get("model", "llama3.1:8b"),
            },
        }
    if ex == "code":
        return {
            "executor": "code",
            "config": {
                "prompt": step_input.get("prompt", ""),
                "language": step_input.get("language", "python"),
            },
        }
    if ex == "tool":
        return {
            "executor": "tool",
            "config": {
                "tool_name": step_input.get("tool_name", ""),
                "params": step_input.get("params", {}),
            },
        }
    if ex == "memory":
        return {"executor": "memory", "config": step_input}
    # Pass through if already normalised (has config key)
    if "config" in step:
        return step
    return {"executor": ex, "config": step_input}


async def dispatch(step: dict) -> dict:
    try:
        normalised = _normalise_step(step)
        ex = normalised.get("executor")
        if ex not in _ROUTERS:
            value = str(ex) if ex is not None else "None"
            return {
                "success": False,
                "output": {},
                "error": f"unknown executor type: {value}",
            }
        handler = _ROUTERS[ex]
        return await handler(normalised)
    except Exception as exc:
        return {
            "success": False,
            "output": {},
            "error": str(exc),
        }
