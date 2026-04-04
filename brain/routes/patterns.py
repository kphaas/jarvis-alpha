"""Log pattern analysis — groups similar logs and uses LLM to diagnose patterns."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from collections import defaultdict

from fastapi import APIRouter, Query

from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")
patterns_router = APIRouter()

# Regex patterns to normalize log messages for grouping
NORMALIZERS = [
    (
        re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[.\d]*[Z+\-:\d]*"),
        "<TIMESTAMP>",
    ),
    (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?"), "<IP>"),
    (re.compile(r"\bPID[= ]\d+|\b\d{3,7}#\d+"), "<PID>"),
    (re.compile(r"[0-9a-f]{8,12}"), "<ID>"),
    (re.compile(r"port \d+|:\d{4,5}"), "<PORT>"),
]

JARVIS_CONTEXT = """You are a JARVIS infrastructure diagnostic assistant analyzing log patterns.

JARVIS is a private multi-node AI system:
- Brain (Mac Studio M2 Ultra): FastAPI :8186, Postgres 16, Ollama, orchestrator
- Gateway (Mac Mini): Cloud LLM proxy, sole internet egress
- Endpoint (Mac Mini M1): React UI :4100 via nginx, presentation only
- Sandbox (Mac Mini M4): jarvis-forge dev pipeline :5001
All nodes on Tailscale VPN mesh. Services managed via LaunchAgents.

You are given grouped log patterns with counts, affected nodes, and time ranges.

For each pattern:
1. Assign severity: CRITICAL (action needed now), HIGH (fix soon), MEDIUM (monitor), LOW (informational)
2. Explain the root cause in 1-2 sentences
3. Provide the exact fix with specific commands, always specifying which node (▶ BRAIN, ▶ GATEWAY, ▶ ENDPOINT, or ▶ SANDBOX)
4. Note if patterns are related to each other (same root cause)

Respond in this exact JSON format (no markdown, no backticks, just raw JSON):
{
  "patterns": [
    {
      "severity": "CRITICAL",
      "title": "Short pattern title",
      "count": 47,
      "nodes": ["endpoint"],
      "root_cause": "Explanation",
      "fix": "Exact commands with node prefix",
      "related_to": null
    }
  ],
  "summary": "One sentence overall assessment"
}"""


def _normalize(msg: str) -> str:
    """Reduce a log message to a template by stripping variable parts."""
    result = msg
    for pattern, replacement in NORMALIZERS:
        result = pattern.sub(replacement, result)
    return result.strip()


@patterns_router.get("/v1/logs/analyze-patterns")
async def analyze_patterns(
    since: str = Query(default="1h"),
    nodes: str = Query(default="brain,gateway,endpoint,sandbox"),
):
    """Fetch recent WARNING/ERROR/CRITICAL/UNKNOWN logs, group by pattern, analyze with LLM."""

    # Step 1: Fetch logs via Loki
    now_ns = int(time.time() * 1e9)
    durations = {"15m": 900, "1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800}
    seconds = durations.get(since, 3600)
    start_ns = str(now_ns - seconds * 1_000_000_000)
    end_ns = str(now_ns)

    node_list = [n.strip() for n in nodes.split(",") if n.strip()]
    node_regex = "|".join(node_list) if node_list else ".+"
    logql = f'{{node=~"{node_regex}"}}'

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
        "limit=1000",
        "--data-urlencode",
        f"start={start_ns}",
        "--data-urlencode",
        f"end={end_ns}",
    ]

    result = await asyncio.to_thread(
        subprocess.run, cmd, capture_output=True, text=True, timeout=20
    )

    if result.returncode != 0:
        logger.warning("loki fetch for patterns failed: %s", result.stderr)
        return {"status": "error", "error": "Failed to fetch logs from Loki"}

    try:
        loki_data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "error": "Invalid JSON from Loki"}

    # Step 2: Parse entries and filter to WARNING/ERROR/CRITICAL/UNKNOWN
    entries = []
    warn_levels = frozenset({"WARNING", "ERROR", "CRITICAL", "UNKNOWN"})
    for stream in loki_data.get("data", {}).get("result", []):
        stream_labels = stream.get("stream", {})
        for ts_ns, raw_line in stream.get("values", []):
            entry = {"node": stream_labels.get("node", "unknown"), "ts_ns": ts_ns}
            try:
                outer = json.loads(raw_line)
                inner_str = outer.get("log", raw_line)
                inner = (
                    json.loads(inner_str) if isinstance(inner_str, str) else inner_str
                )
                lv = str(inner.get("level", "UNKNOWN")).upper()
                entry.update(
                    {
                        "level": lv,
                        "service": inner.get("service", "unknown"),
                        "message": inner.get("message", ""),
                    }
                )
            except (json.JSONDecodeError, TypeError):
                msg = raw_line
                try:
                    msg = json.loads(raw_line).get("log", raw_line)
                except Exception:
                    pass
                entry.update({"level": "UNKNOWN", "service": "unknown", "message": msg})

            if entry["level"] in warn_levels:
                entries.append(entry)

    if not entries:
        return {
            "status": "success",
            "pattern_count": 0,
            "raw_log_count": 0,
            "analysis": {
                "patterns": [],
                "summary": (
                    "No warning, error, or critical logs found in the selected timeframe."
                ),
            },
        }

    # Step 3: Group by normalized message template
    groups = defaultdict(
        lambda: {
            "count": 0,
            "nodes": set(),
            "levels": set(),
            "samples": [],
            "first_ts": None,
            "last_ts": None,
        }
    )
    for e in entries:
        template = _normalize(e["message"])
        g = groups[template]
        g["count"] += 1
        g["nodes"].add(e["node"])
        g["levels"].add(e["level"])
        if len(g["samples"]) < 3:
            g["samples"].append(e["message"][:200])
        ts = e["ts_ns"]
        if g["first_ts"] is None or ts < g["first_ts"]:
            g["first_ts"] = ts
        if g["last_ts"] is None or ts > g["last_ts"]:
            g["last_ts"] = ts

    # Step 4: Sort by count descending, take top 10
    sorted_patterns = sorted(groups.items(), key=lambda x: x[1]["count"], reverse=True)[
        :10
    ]

    # Build prompt for LLM
    pattern_text = ""
    for i, (_template, data) in enumerate(sorted_patterns, 1):
        pattern_text += f"\nPattern {i}:\n"
        pattern_text += f"  Count: {data['count']}\n"
        pattern_text += f"  Nodes: {', '.join(sorted(data['nodes']))}\n"
        pattern_text += f"  Levels: {', '.join(sorted(data['levels']))}\n"
        pattern_text += "  Sample messages:\n"
        for s in data["samples"]:
            pattern_text += f"    - {s}\n"

    user_prompt = (
        f"Analyze these {len(sorted_patterns)} log patterns from the last {since} "
        f"and provide diagnosis with fixes:\n{pattern_text}"
    )

    # Step 5: Call Ollama
    payload = json.dumps(
        {
            "model": "llama3.1:8b",
            "messages": [
                {"role": "system", "content": JARVIS_CONTEXT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 1500},
        }
    )

    llm_cmd = [
        "curl",
        "-s",
        "--max-time",
        "90",
        "http://127.0.0.1:11434/api/chat",
        "-H",
        "Content-Type: application/json",
        "-d",
        payload,
    ]

    try:
        llm_result = await asyncio.to_thread(
            subprocess.run, llm_cmd, capture_output=True, text=True, timeout=95
        )

        if llm_result.returncode != 0:
            return {
                "status": "error",
                "error": f"Ollama call failed: {llm_result.stderr}",
            }

        llm_data = json.loads(llm_result.stdout)
        analysis_text = llm_data.get("message", {}).get("content", "")

        try:
            clean = analysis_text.strip()
            if clean.startswith("```"):
                clean = "\n".join(clean.split("\n")[1:])
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]
            analysis = json.loads(clean.strip())
        except json.JSONDecodeError:
            analysis = {"patterns": [], "summary": analysis_text}

        return {
            "status": "success",
            "pattern_count": len(sorted_patterns),
            "raw_log_count": len(entries),
            "analysis": analysis,
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}
