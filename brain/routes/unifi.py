"""Alpha Brain UniFi proxy — calls alpha Gateway only."""

from fastapi import APIRouter, HTTPException

from brain.services import unifi_client

router = APIRouter(tags=["unifi"])


async def _proxy(path: str):
    try:
        return await unifi_client.gateway_get(path)
    except unifi_client.UniFiGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/v1/unifi/status")
async def unifi_status():
    return await _proxy("/v1/unifi/status")


@router.get("/v1/unifi/wan")
async def unifi_wan():
    return await _proxy("/v1/unifi/wan")


@router.get("/v1/unifi/clients")
async def unifi_clients():
    return await _proxy("/v1/unifi/clients")


@router.get("/v1/unifi/summary")
async def unifi_summary():
    return await _proxy("/v1/unifi/summary")


@router.get("/v1/unifi/health-check")
async def unifi_health_check():
    return await _proxy("/v1/unifi/health-check")
