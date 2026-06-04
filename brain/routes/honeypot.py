"""Honeypot decoy endpoints — log and alert on suspicious access attempts."""

from __future__ import annotations

import json
from ipaddress import ip_address

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from jarvis_common.logging_config import get_logger

from brain.agents.events import AgentEvent, emit_agent_event
from brain.db.pool import get_pool
from brain.db.rls import platform_admin_connection
from brain.middleware.scopes import check_scopes

logger = get_logger("alpha_brain")
honeypot_router = APIRouter(tags=["honeypot"])
TRIPWIRE_AGENT_ID = "tripwire"
TRIPWIRE_EVENT_TYPE = "honeypot.hit"
TRIPWIRE_NOTIFY_WINDOW = "15 minutes"
TRIPWIRE_TRAPS = (
    "/admin",
    "/wp-login.php",
    "/.env",
    "/.git/config",
    "/phpmyadmin",
    "/api/v1/debug",
)


def _serialize_honeypot_event(row) -> dict:
    captured_at = row["captured_at"]
    event = {
        "id": row["id"],
        "ts": captured_at.isoformat() if captured_at else None,
        "path": row["trap_path"],
        "trap_type": _trap_type(row["trap_path"]),
        "client_ip": row["source_ip"],
        "user_agent": row["user_agent"] or "",
        "method": row["method"] or "GET",
    }
    event["source_reputation"] = source_reputation(
        event["client_ip"],
        event["user_agent"],
    )
    return event


def source_reputation(
    source_ip: str,
    user_agent: str = "",
    *,
    hit_count: int = 1,
    unique_paths: int = 1,
) -> dict:
    tags: list[str] = []
    status = "single_probe"
    severity = "low"
    summary = "Single honeypot probe"

    try:
        parsed = ip_address(source_ip)
    except ValueError:
        tags.append("invalid_ip")
        return {
            "status": "unknown_source",
            "severity": "medium",
            "summary": "Source IP could not be parsed",
            "tags": tags,
        }

    if (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_reserved
    ):
        tags.append("internal_or_reserved")
        status = "internal_or_reserved"
        severity = "medium"
        summary = "Internal, private, or reserved source reached a honeypot trap"

    ua = user_agent.lower()
    scanner_terms = ("bot", "crawler", "scanner", "masscan", "zgrab", "nuclei")
    if any(term in ua for term in scanner_terms):
        tags.append("scanner_user_agent")
        status = "scanner"
        severity = "medium"
        summary = "Scanner-like user agent hit a honeypot trap"

    if unique_paths >= 2 or hit_count >= 3:
        tags.append("repeat_probe")
        status = "repeat_probe"
        severity = "high" if hit_count >= 5 or unique_paths >= 3 else "medium"
        summary = f"Repeat source hit {hit_count} trap(s) across {unique_paths} path(s)"

    return {
        "status": status,
        "severity": severity,
        "summary": summary,
        "tags": tags,
    }


def cluster_honeypot_events(events: list[dict]) -> list[dict]:
    clusters: dict[str, dict] = {}
    for event in events:
        source_ip = str(event.get("client_ip") or "unknown")
        cluster = clusters.setdefault(
            source_ip,
            {
                "source_ip": source_ip,
                "hit_count": 0,
                "paths": set(),
                "methods": set(),
                "last_seen": None,
                "user_agent": "",
            },
        )
        cluster["hit_count"] += 1
        cluster["paths"].add(str(event.get("path") or "unknown"))
        cluster["methods"].add(str(event.get("method") or "GET").upper())
        if event.get("user_agent") and not cluster["user_agent"]:
            cluster["user_agent"] = str(event.get("user_agent"))
        ts = event.get("ts")
        if ts and (cluster["last_seen"] is None or ts > cluster["last_seen"]):
            cluster["last_seen"] = ts

    out = []
    for cluster in clusters.values():
        unique_paths = len(cluster["paths"])
        reputation = source_reputation(
            cluster["source_ip"],
            cluster["user_agent"],
            hit_count=cluster["hit_count"],
            unique_paths=unique_paths,
        )
        out.append(
            {
                "source_ip": cluster["source_ip"],
                "hit_count": cluster["hit_count"],
                "unique_paths": unique_paths,
                "paths": sorted(cluster["paths"]),
                "methods": sorted(cluster["methods"]),
                "last_seen": cluster["last_seen"],
                "source_reputation": reputation,
            }
        )
    return sorted(
        out,
        key=lambda item: (
            item["source_reputation"]["severity"] != "high",
            -item["hit_count"],
            item["source_ip"],
        ),
    )


def source_reputation_summary(clusters: list[dict]) -> dict:
    return {
        "repeat_sources": sum(
            1
            for cluster in clusters
            if cluster["source_reputation"]["status"] == "repeat_probe"
        ),
        "scanner_sources": sum(
            1
            for cluster in clusters
            if "scanner_user_agent" in cluster["source_reputation"]["tags"]
        ),
        "internal_sources": sum(
            1
            for cluster in clusters
            if "internal_or_reserved" in cluster["source_reputation"]["tags"]
        ),
    }


def _trap_type(path: str) -> str:
    return {
        "/admin": "admin_panel",
        "/wp-login.php": "wordpress",
        "/.env": "env_file",
        "/.git/config": "git_config",
        "/phpmyadmin": "phpmyadmin",
        "/api/v1/debug": "debug_api",
    }.get(path, "unknown")


async def _persist_event(request: Request, trap_path: str):
    pool = get_pool()
    source_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "") or ""
    should_notify = False
    async with platform_admin_connection(
        source="http", audit_actor="tripwire_honeypot", pool=pool
    ) as conn:
        await conn.execute(
            """
            INSERT INTO public.alpha_honeypot_events
                (trap_path, source_ip, method, user_agent, headers)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            """,
            trap_path,
            source_ip,
            request.method,
            user_agent,
            json.dumps(dict(request.headers)),
        )
        recent_match = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM public.alpha_agent_events
                WHERE agent_id = $1
                  AND event_type = $2
                  AND payload->>'trap_path' = $3
                  AND payload->>'source_ip' = $4
                  AND created_at >= NOW() - INTERVAL '15 minutes'
            )
            """,
            TRIPWIRE_AGENT_ID,
            TRIPWIRE_EVENT_TYPE,
            trap_path,
            source_ip,
        )
        should_notify = not bool(recent_match)
    await _emit_tripwire_event(
        trap_path=trap_path,
        source_ip=source_ip,
        method=request.method,
        user_agent=user_agent,
        should_notify=should_notify,
        pool=pool,
    )


async def _emit_tripwire_event(
    *,
    trap_path: str,
    source_ip: str,
    method: str,
    user_agent: str,
    should_notify: bool,
    pool,
) -> None:
    try:
        await emit_agent_event(
            AgentEvent(
                agent_id=TRIPWIRE_AGENT_ID,
                event_type=TRIPWIRE_EVENT_TYPE,
                title="Tripwire honeypot hit",
                message=f"{method} {trap_path} from {source_ip}",
                severity="warning",
                channel_key="security_alerts",
                notify=should_notify,
                payload={
                    "trap_path": trap_path,
                    "source_ip": source_ip,
                    "method": method,
                    "user_agent": user_agent[:200],
                    "source_reputation": source_reputation(source_ip, user_agent),
                    "notify_debounce_window": TRIPWIRE_NOTIFY_WINDOW,
                },
            ),
            pool=pool,
        )
    except Exception as exc:
        logger.error(
            "TRIPWIRE_EVENT_FAILED path=%s ip=%s error=%s",
            trap_path,
            source_ip,
            exc,
            exc_info=True,
        )


def _log_hit(request: Request, path: str, trap_type: str) -> None:
    logger.warning(
        "HONEYPOT_HIT path=%s trap=%s ip=%s ua=%s",
        path,
        trap_type,
        request.client.host if request.client else "unknown",
        (request.headers.get("user-agent", "unknown") or "unknown")[:80],
    )


@honeypot_router.get("/admin", response_class=HTMLResponse)
@honeypot_router.post("/admin", response_class=HTMLResponse)
async def trap_admin(request: Request):
    await _persist_event(request, "/admin")
    _log_hit(request, "/admin", "admin_panel")
    return HTMLResponse(
        content="""<!DOCTYPE html><html><head><title>Admin Login</title></head>
<body style="font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;background:#f5f5f5">
<div style="background:white;padding:40px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,0.1)">
<h2>System Administration</h2>
<form method="post"><input type="text" name="username" placeholder="Username" style="display:block;width:200px;margin:8px 0;padding:8px">
<input type="password" name="password" placeholder="Password" style="display:block;width:200px;margin:8px 0;padding:8px">
<button type="submit" style="padding:8px 24px;margin-top:8px">Login</button></form></div></body></html>""",
        status_code=200,
    )


@honeypot_router.get("/wp-login.php", response_class=HTMLResponse)
@honeypot_router.post("/wp-login.php", response_class=HTMLResponse)
async def trap_wordpress(request: Request):
    await _persist_event(request, "/wp-login.php")
    _log_hit(request, "/wp-login.php", "wordpress")
    return HTMLResponse(
        content="""<!DOCTYPE html><html><head><title>WordPress &rsaquo; Log In</title></head>
<body style="font-family:-apple-system,sans-serif;background:#f0f0f1;display:flex;justify-content:center;padding-top:8%">
<div style="background:white;padding:26px 24px;border-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,.13);width:320px">
<h1 style="text-align:center;margin:0 0 16px"><span style="font-size:20px;color:#3c434a">WordPress</span></h1>
<form method="post"><label style="font-size:14px">Username or Email<br>
<input type="text" name="log" style="width:100%;padding:6px;margin:4px 0 16px;box-sizing:border-box"></label>
<label style="font-size:14px">Password<br>
<input type="password" name="pwd" style="width:100%;padding:6px;margin:4px 0 16px;box-sizing:border-box"></label>
<button type="submit" style="background:#2271b1;color:white;border:none;padding:8px 20px;border-radius:3px">Log In</button></form></div></body></html>""",
        status_code=200,
    )


@honeypot_router.get("/.env", response_class=PlainTextResponse)
async def trap_env(request: Request):
    await _persist_event(request, "/.env")
    _log_hit(request, "/.env", "env_file")
    return PlainTextResponse(
        content="""# Application Configuration
APP_ENV=production
APP_DEBUG=false
DB_HOST=localhost
DB_PORT=5432
DB_DATABASE=app_production
DB_USERNAME=app_user
DB_PASSWORD=FAKE_PASSWORD_HONEYPOT_TRAP
API_KEY=FAKE_KEY_HONEYPOT_TRAP_sk_live_xxxxxxxxxxxx
SECRET_KEY=FAKE_SECRET_HONEYPOT_TRAP_xxxxxxxxxxxx
AWS_ACCESS_KEY_ID=AKIAFAKEXXXXXXXXHONEYPOT
AWS_SECRET_ACCESS_KEY=FAKE+SECRET+KEY+HONEYPOT+TRAP+xxxxxxxx
""",
        status_code=200,
    )


@honeypot_router.get("/.git/config", response_class=PlainTextResponse)
async def trap_git(request: Request):
    await _persist_event(request, "/.git/config")
    _log_hit(request, "/.git/config", "git_config")
    return PlainTextResponse(
        content="""[core]
    repositoryformatversion = 0
    filemode = true
    bare = false
[remote "origin"]
    url = https://github.com/internal/app-production.git
    fetch = +refs/heads/*:refs/remotes/origin/*
[branch "main"]
    remote = origin
    merge = refs/heads/main
[user]
    name = deploy-bot
    email = deploy@internal.local
""",
        status_code=200,
    )


@honeypot_router.get("/phpmyadmin", response_class=HTMLResponse)
@honeypot_router.get("/phpmyadmin/", response_class=HTMLResponse)
async def trap_phpmyadmin(request: Request):
    await _persist_event(request, "/phpmyadmin")
    _log_hit(request, "/phpmyadmin", "phpmyadmin")
    return HTMLResponse(
        content="""<!DOCTYPE html><html><head><title>phpMyAdmin</title></head>
<body style="font-family:sans-serif;background:#e7e9ed;display:flex;justify-content:center;padding-top:10%">
<div style="background:white;padding:30px;border-radius:4px;box-shadow:0 1px 5px rgba(0,0,0,.15);width:350px">
<h1 style="font-size:18px;color:#333;margin:0 0 20px">phpMyAdmin</h1>
<form method="post"><input type="text" name="pma_username" placeholder="Username" style="display:block;width:100%;padding:8px;margin:8px 0;box-sizing:border-box">
<input type="password" name="pma_password" placeholder="Password" style="display:block;width:100%;padding:8px;margin:8px 0;box-sizing:border-box">
<button type="submit" style="padding:8px 24px;margin-top:8px;background:#6c9">Go</button></form></div></body></html>""",
        status_code=200,
    )


@honeypot_router.get("/api/v1/debug", response_class=JSONResponse)
async def trap_debug(request: Request):
    await _persist_event(request, "/api/v1/debug")
    _log_hit(request, "/api/v1/debug", "debug_api")
    return JSONResponse(
        content={
            "debug": True,
            "env": "production",
            "version": "3.2.1",
            "database": "connected",
            "api_key": "FAKE_KEY_HONEYPOT_xxxxxxxxxxx",
            "secret": "FAKE_SECRET_HONEYPOT_xxxxxxxxxxx",
            "internal_url": "http://internal.fake.local:8080",
        },
        status_code=200,
    )


@honeypot_router.get("/v1/honeypot/events")
async def get_honeypot_events(request: Request, limit: int = 50):
    """Return recent honeypot hits. Protected by JWT (normal auth middleware applies)."""
    check_scopes(request, "security.read", "security_read")
    pool = get_pool()
    async with platform_admin_connection(
        source="http", audit_actor="tripwire_events", pool=pool
    ) as conn:
        rows = await conn.fetch(
            """
            SELECT id, trap_path, source_ip, method, user_agent, captured_at
            FROM public.alpha_honeypot_events
            ORDER BY captured_at DESC
            LIMIT $1
            """,
            min(limit, 200),
        )
        total = int(
            await conn.fetchval("SELECT COUNT(*) FROM public.alpha_honeypot_events")
            or 0
        )
        hits_24h = int(
            await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM public.alpha_honeypot_events
                WHERE captured_at >= NOW() - INTERVAL '24 hours'
                """
            )
            or 0
        )
        unique_clients_24h = int(
            await conn.fetchval(
                """
                SELECT COUNT(DISTINCT source_ip)
                FROM public.alpha_honeypot_events
                WHERE captured_at >= NOW() - INTERVAL '24 hours'
                """
            )
            or 0
        )
    events = [_serialize_honeypot_event(row) for row in rows]
    clusters = cluster_honeypot_events(events)
    reputation_by_source = {
        cluster["source_ip"]: cluster["source_reputation"] for cluster in clusters
    }
    for event in events:
        event["source_reputation"] = reputation_by_source.get(
            event["client_ip"],
            event["source_reputation"],
        )
    return {
        "agent_id": TRIPWIRE_AGENT_ID,
        "display_name": "Tripwire",
        "total": total,
        "hits_24h": hits_24h,
        "unique_clients_24h": unique_clients_24h,
        "traps_active": len(TRIPWIRE_TRAPS),
        "traps": list(TRIPWIRE_TRAPS),
        "events": events,
        "probe_clusters": clusters,
        "source_reputation_summary": source_reputation_summary(clusters),
    }
