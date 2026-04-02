from __future__ import annotations

from collections.abc import Awaitable, Callable

Handler = Callable[[dict], Awaitable[dict]]


async def call_tool_agent(step: dict) -> dict:
    # WORKER NODE UPGRADE PATH:
    # When extracting executor to worker node, replace this function body
    # with an HTTP POST to Brain API. Dispatch interface unchanged.
    return {
        "success": True,
        "output": {"result": "stub - not yet implemented"},
        "error": None,
    }


async def call_code_agent(step: dict) -> dict:
    # WORKER NODE UPGRADE PATH:
    # When extracting executor to worker node, replace this function body
    # with an HTTP POST to Brain API. Dispatch interface unchanged.
    return {
        "success": True,
        "output": {"result": "stub - not yet implemented"},
        "error": None,
    }


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
    return {
        "success": True,
        "output": {"result": "stub - not yet implemented"},
        "error": None,
    }


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
