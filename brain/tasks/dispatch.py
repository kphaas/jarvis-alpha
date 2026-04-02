from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

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


async def dispatch(step: dict) -> dict:
    try:
        ex = step.get("executor")
        if ex not in _ROUTERS:
            value = str(ex) if ex is not None else "None"
            return {
                "success": False,
                "output": {},
                "error": f"unknown executor type: {value}",
            }
        handler = _ROUTERS[ex]
        return await handler(step)
    except Exception as exc:
        return {
            "success": False,
            "output": {},
            "error": str(exc),
        }
