import datetime
import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.request

BRAIN_URL = os.environ.get("JARVIS_ALPHA_BRAIN_URL", "https://jarvis-brain.tail40ed36.ts.net:8186")
NODE_NAME = os.environ.get("JARVIS_NODE_NAME", "unknown")

_COMBINED_MARKER = "combined power (cpu + gpu + ane):"


def get_watts_psutil() -> tuple[float, float]:
    import psutil
    cpu_pct = float(psutil.cpu_percent(interval=2))

    if NODE_NAME == "Brain":
        idle, tdp = 20.0, 60.0
    elif NODE_NAME == "Gateway":
        idle, tdp = 7.0, 39.0
    elif NODE_NAME == "Endpoint":
        idle, tdp = 7.0, 39.0
    elif NODE_NAME == "Sandbox":
        idle, tdp = 10.0, 38.0
    else:
        idle, tdp = 10.0, 40.0

    estimated_watts = idle + (cpu_pct / 100.0) * (tdp - idle)
    return (round(estimated_watts, 2), cpu_pct)


def get_watts_brain() -> tuple[float, float]:
    try:
        proc = subprocess.run(
            [
                "sudo",
                "powermetrics",
                "--samplers",
                "cpu_power",
                "-n",
                "1",
                "-i",
                "500",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        text = (proc.stdout or "") + (proc.stderr or "")
        mw = None
        for line in text.splitlines():
            low = line.lower()
            if _COMBINED_MARKER in low:
                after = line.split(":", 1)[-1]
                tok = after.lower().replace("mw", " ").strip().split()
                if tok:
                    try:
                        mw = float(tok[0])
                    except ValueError:
                        mw = None
                break
        if mw is None:
            return (10.0, 0.0)
        return (round(mw / 1000.0, 2), 0.0)
    except Exception:
        return (10.0, 0.0)


def post_reading(watts: float, cpu_pct: float, source: str) -> None:
    url = f"{BRAIN_URL.rstrip('/')}/v1/metrics/power"
    body = {
        "node_name": NODE_NAME,
        "watts": watts,
        "cpu_pct": cpu_pct,
        "source": source,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"post_reading error: {e}", flush=True)


def main() -> None:
    while True:
        watts, cpu_pct = get_watts_psutil()
        source = "psutil"

        post_reading(watts, cpu_pct, source)
        print(
            f"{datetime.datetime.now().isoformat()} {NODE_NAME} {watts}W cpu={cpu_pct}%",
            flush=True,
        )
        time.sleep(900)


if __name__ == "__main__":
    main()
