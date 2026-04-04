"""Loki log query proxy — lets the UI query logs without direct Loki access."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time

from fastapi import APIRouter, Query

from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")
logs_router = APIRouter()

_VALID_NODES = frozenset({"brain", "gateway", "endpoint", "sandbox"})
_VALID_LEVELS = frozenset({"INFO", "WARNING", "ERROR", "CRITICAL"})


def _build_logql(
    nodes_csv: str | None,
    level_csv: str | None,
    service: str,
    search: str | None,
) -> str:
    """Build LogQL for Fluent Bit lines: outer JSON with string field ``log`` holding inner JSON."""
    # Stream selector
    if not nodes_csv or not nodes_csv.strip():
        node_part = '{node=~".+"}'
    else:
        parts = [n.strip() for n in nodes_csv.split(",") if n.strip()]
        picked = [n for n in parts if n in _VALID_NODES]
        if not picked or len(picked) >= len(_VALID_NODES):
            node_part = '{node=~".+"}'
        else:
            node_part = '{node=~"' + "|".join(picked) + '"}'

    # Parse outer JSON, expand nested log line, parse inner JSON for level/service filters
    q = node_part + ' | json | line_format "{{.log}}" | json'

    if level_csv and level_csv.strip():
        levels = []
        for raw in level_csv.split(","):
            lv = raw.strip().upper()
            if lv in _VALID_LEVELS:
                levels.append(lv)
        if levels and len(levels) < len(_VALID_LEVELS):
            pattern = "|".join(re.escape(x) for x in levels)
            q += f' | level=~"{pattern}"'

    if service and service.strip() and service.strip() != "all":
        svc = service.strip().replace("\\", "\\\\").replace('"', '\\"')
        q += f' | service="{svc}"'

    if search and search.strip():
        esc = search.strip().replace("\\", "\\\\").replace('"', '\\"')
        q += f' |= "{esc}"'

    return q


@logs_router.get("/v1/logs/query")
async def query_logs(
    nodes: str | None = Query(
        default=None,
        description="Comma-separated nodes (brain,gateway,...); omit for all",
    ),
    level: str | None = Query(
        default=None,
        description="Comma-separated levels (INFO,ERROR,...); omit for all",
    ),
    service: str = Query(default="all"),
    search: str | None = Query(default=None, description="Free-text line filter"),
    limit: int = Query(default=100, ge=1, le=1000),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    since: str = Query(default="1h"),
):
    """Proxy LogQL queries to Loki on localhost:3100."""
    now_ns = int(time.time() * 1e9)

    if start and end:
        start_ns = start
        end_ns = end
    else:
        durations = {"15m": 900, "1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800}
        seconds = durations.get(since, 3600)
        start_ns = str(now_ns - seconds * 1_000_000_000)
        end_ns = str(now_ns)

    logql = _build_logql(nodes, level, service, search)

    # Use curl + asyncio.to_thread to avoid httpx TLS issues
    cmd = [
        "curl",
        "-s",
        "--max-time",
        "15",
        "-G",
        "http://127.0.0.1:3100/loki/api/v1/query_range",
        "--data-urlencode",
        f"query={logql}",
        "--data-urlencode",
        f"limit={limit}",
        "--data-urlencode",
        f"start={start_ns}",
        "--data-urlencode",
        f"end={end_ns}",
    ]

    result = await asyncio.to_thread(
        subprocess.run, cmd, capture_output=True, text=True, timeout=20
    )

    if result.returncode != 0:
        logger.warning("loki curl failed: %s", result.stderr)
        return {"status": "error", "error": result.stderr}

    try:
        loki_data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "error": "Invalid JSON from Loki"}

    # Parse and flatten log entries
    entries = []
    for stream in loki_data.get("data", {}).get("result", []):
        stream_labels = stream.get("stream", {})
        for ts_ns, raw_line in stream.get("values", []):
            entry = {
                "ts_ns": ts_ns,
                "node": stream_labels.get("node", "unknown"),
                "raw": raw_line,
            }
            # Try to parse the inner JSON from Fluent Bit wrapping
            try:
                outer = json.loads(raw_line)
                inner_str = outer.get("log", raw_line)
                inner = (
                    json.loads(inner_str) if isinstance(inner_str, str) else inner_str
                )
                entry.update(
                    {
                        "ts": inner.get("ts", ""),
                        "level": inner.get("level", "UNKNOWN"),
                        "service": inner.get("service", "unknown"),
                        "node": inner.get("node", stream_labels.get("node", "unknown")),
                        "trace_id": inner.get("trace_id", ""),
                        "message": inner.get("message", ""),
                    }
                )
            except (json.JSONDecodeError, TypeError):
                entry.update(
                    {
                        "ts": "",
                        "level": "UNKNOWN",
                        "service": "unknown",
                        "trace_id": "",
                        "message": raw_line,
                    }
                )
            entries.append(entry)

    # Sort newest first
    entries.sort(key=lambda e: e["ts_ns"], reverse=True)

    return {"status": "success", "count": len(entries), "entries": entries}
