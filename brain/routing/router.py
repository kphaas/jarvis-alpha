import httpx

from brain.core.config import GATEWAY_URL, OLLAMA_URL
from brain.routing.complexity import score
from brain.routing.council import CouncilOrchestrator

COUNCIL_TRIGGER = "manual"  # future values: "complexity", "topic"


async def route(prompt: str, mode: str = "auto") -> dict:
    if mode == "council":
        return await CouncilOrchestrator().run(prompt)

    if mode == "auto":
        s = score(prompt)
        if s in (1, 2) or s == "code" or s == "scrape":
            mode = "local"
        elif s == 3:
            mode = "perplexity"
        elif s == 4:
            mode = "claude"
        else:
            mode = "gemini"

    try:
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            if mode == "local":
                r = await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": "llama3.1:8b",
                        "prompt": prompt,
                        "stream": False,
                    },
                )
                r.raise_for_status()
                text = (r.json().get("response") or "").strip()
                return {"mode": "local", "result": text}

            if mode == "claude":
                r = await client.post(
                    f"{GATEWAY_URL}/v1/cloud/claude",
                    json={"prompt": prompt},
                )
                r.raise_for_status()
                text = (r.json().get("result") or "").strip()
                return {"mode": "claude", "result": text}

            if mode == "gemini":
                r = await client.post(
                    f"{GATEWAY_URL}/v1/cloud/gemini",
                    json={"prompt": prompt},
                )
                r.raise_for_status()
                text = (r.json().get("result") or "").strip()
                return {"mode": "gemini", "result": text}

            if mode == "perplexity":
                r = await client.post(
                    f"{GATEWAY_URL}/v1/cloud/perplexity",
                    json={"prompt": prompt},
                )
                r.raise_for_status()
                text = (r.json().get("result") or "").strip()
                return {"mode": "perplexity", "result": text}

            return {"mode": mode, "result": "", "error": f"unknown mode: {mode}"}
    except Exception as e:
        return {"mode": mode, "result": "", "error": str(e)}
