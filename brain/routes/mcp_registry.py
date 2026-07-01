"""MCP server registry — tracks configured MCP servers and their status."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request

from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes

mcp_router = APIRouter(prefix="/v1/security/mcp", tags=["mcp"])

REPO_ROOT = Path(__file__).resolve().parents[2]
BEACON_CRAWLER_MCP_ADAPTER_ENABLED = "BEACON_CRAWLER_MCP_ADAPTER_ENABLED"
BEACON_CRAWLER_MCP_CONTRACT = (
    REPO_ROOT / "docs" / "contracts" / "beacon_crawler_mcp_adapter.v1.json"
)

BASE_MCP_SERVERS = [
    {
        "name": "Home Assistant",
        "id": "homeassistant",
        "endpoint": "gateway",
        "status": "planned",
        "permissions": ["device.read", "device.control", "automation.trigger"],
        "backlog_ref": "F-030",
        "description": "Smart home control via Gateway MCP client",
    },
    {
        "name": "UniFi",
        "id": "unifi",
        "endpoint": "gateway",
        "status": "planned",
        "permissions": ["network.read", "firewall.read", "client.list"],
        "backlog_ref": "F-031",
        "description": "Network management via UDM Pro API",
    },
    {
        "name": "Google Calendar",
        "id": "gcal",
        "endpoint": "gateway",
        "status": "planned",
        "permissions": ["calendar.read", "calendar.write", "event.create"],
        "backlog_ref": "F-032",
        "description": "Calendar access via Google Calendar API",
    },
    {
        "name": "Unraid",
        "id": "unraid",
        "endpoint": "gateway",
        "status": "planned",
        "permissions": ["storage.read", "docker.list", "vm.list"],
        "backlog_ref": "F-033",
        "description": "NAS management via Unraid API",
    },
]


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def _beacon_crawler_contract() -> dict[str, Any]:
    return json.loads(BEACON_CRAWLER_MCP_CONTRACT.read_text(encoding="utf-8"))


def _beacon_crawler_server() -> dict[str, object]:
    return {
        "name": "Beacon Crawler",
        "id": "beacon-crawler",
        "endpoint": "alpha",
        "status": "planned",
        "permissions": [
            "internet_scout.research",
            "crawler.scrape",
            "crawler.map",
            "crawler.crawl",
            "crawler.extract",
            "crawler.render.approval",
        ],
        "backlog_ref": "BEACON-MCP-001",
        "description": (
            "Disabled-by-default MCP adapter skeleton over Beacon crawler "
            "contracts; status-only until invocation is reviewed."
        ),
        "adapter_route": "/v1/security/mcp/adapters/beacon-crawler",
        "runtime_enabled": _env_enabled(BEACON_CRAWLER_MCP_ADAPTER_ENABLED),
    }


def mcp_servers() -> list[dict[str, object]]:
    return [*BASE_MCP_SERVERS, _beacon_crawler_server()]


def beacon_crawler_adapter_status() -> dict[str, object]:
    contract = _beacon_crawler_contract()
    enabled = _env_enabled(BEACON_CRAWLER_MCP_ADAPTER_ENABLED)
    tools = contract.get("tools", [])
    return {
        "id": "beacon-crawler",
        "name": "Beacon Crawler",
        "enabled": enabled,
        "runtime_status": "blocked_unimplemented" if enabled else "disabled",
        "invoke_enabled": False,
        "invoke_route": None,
        "activation_env": BEACON_CRAWLER_MCP_ADAPTER_ENABLED,
        "contract_ref": "docs/contracts/beacon_crawler_mcp_adapter.v1.json",
        "contract_status": contract.get("status"),
        "tool_count": len(tools) if isinstance(tools, list) else 0,
        "tools": [
            {
                "name": tool.get("name"),
                "route": tool.get("route"),
                "approval": tool.get("approval"),
                "risk_tier": tool.get("risk_tier"),
            }
            for tool in tools
            if isinstance(tool, dict)
        ],
        "boundaries": {
            "alpha_auth_required": True,
            "gateway_egress_only": True,
            "raw_browser_runtime_access_allowed": False,
            "render_requires_human_approval": True,
            "audit_required": True,
        },
        "blocked_by": ["runtime_execution_not_implemented"]
        + ([] if enabled else [f"{BEACON_CRAWLER_MCP_ADAPTER_ENABLED}=true"]),
    }


@mcp_router.get("/registry")
async def mcp_registry():
    """Return all registered MCP servers with their status and permissions."""
    servers = mcp_servers()
    active = sum(1 for s in servers if s["status"] == "active")
    planned = sum(1 for s in servers if s["status"] == "planned")
    return {
        "total": len(servers),
        "active": active,
        "planned": planned,
        "servers": servers,
    }


@mcp_router.get("/adapters/beacon-crawler")
async def mcp_beacon_crawler_adapter(
    request: Request,
    _user_id: str = Depends(require_auth),
):
    """Return the fail-closed Beacon crawler MCP adapter runtime status."""
    check_scopes(request, "security.read", "internet_scout.research", "admin")
    return beacon_crawler_adapter_status()
