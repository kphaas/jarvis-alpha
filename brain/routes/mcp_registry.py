"""MCP server registry — tracks configured MCP servers and their status."""

from __future__ import annotations

from fastapi import APIRouter

mcp_router = APIRouter(prefix="/v1/security/mcp", tags=["mcp"])

MCP_SERVERS = [
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


@mcp_router.get("/registry")
async def mcp_registry():
    """Return all registered MCP servers with their status and permissions."""
    active = sum(1 for s in MCP_SERVERS if s["status"] == "active")
    planned = sum(1 for s in MCP_SERVERS if s["status"] == "planned")
    return {
        "total": len(MCP_SERVERS),
        "active": active,
        "planned": planned,
        "servers": MCP_SERVERS,
    }
