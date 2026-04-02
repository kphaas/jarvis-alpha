from __future__ import annotations

from typing import Any, Mapping


async def dispatch(step: Mapping[str, Any]) -> dict[str, Any]:
    """
    Execute a single task step. Override or replace on worker nodes with HTTP calls to Brain API.
    """
    return {"ok": True, "label": step.get("label")}
