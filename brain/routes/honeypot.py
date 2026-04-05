"""Honeypot decoy endpoints — log and alert on suspicious access attempts."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from jarvis_common.logging_config import get_logger

from brain.db.pool import get_pool

logger = get_logger("alpha_brain")
honeypot_router = APIRouter(tags=["honeypot"])


async def _persist_event(request: Request, trap_path: str):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO alpha_honeypot_events (trap_path, source_ip, method, user_agent, headers)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            """,
            trap_path,
            request.client.host if request.client else "unknown",
            request.method,
            request.headers.get("user-agent", ""),
            json.dumps(dict(request.headers)),
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
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM alpha_honeypot_events ORDER BY captured_at DESC LIMIT $1",
            min(limit, 200),
        )
    return [dict(r) for r in rows]
