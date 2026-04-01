import asyncio

import httpx

from brain.core.config import GATEWAY_URL, OLLAMA_URL

_OLLAMA_REFINE_SYSTEM = (
    "You are a prompt engineer. Rewrite the user prompt to be clear, specific, "
    "and unambiguous. Return only the rewritten prompt, nothing else."
)
_OLLAMA_SYNTH_SYSTEM = (
    "You are a synthesis engine. Given two AI responses to the same question, "
    "identify: 1) Points both agree on 2) Points that differ 3) Write a unified best answer."
)


class CouncilOrchestrator:
    async def run(self, user_prompt: str) -> dict:
        out = {
            "mode": "council",
            "refined_prompt": "",
            "claude_response": "",
            "gemini_response": "",
            "synthesis": "",
            "final_answer": "",
            "steps_completed": 0,
        }

        try:
            async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
                r = await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": "qwen2.5-coder:7b",
                        "system": _OLLAMA_REFINE_SYSTEM,
                        "prompt": user_prompt,
                        "stream": False,
                    },
                )
                r.raise_for_status()
                data = r.json()
            out["refined_prompt"] = (data.get("response") or "").strip()
            out["steps_completed"] = 1
        except Exception as e:
            out["steps_completed"] = 1
            out["error"] = str(e)
            return out

        refined_prompt = out["refined_prompt"]

        async def _claude():
            async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
                resp = await client.post(
                    f"{GATEWAY_URL}/v1/cloud/claude",
                    json={"prompt": refined_prompt, "mode": "council"},
                )
                resp.raise_for_status()
                return (resp.json().get("result") or "").strip()

        async def _gemini():
            async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
                resp = await client.post(
                    f"{GATEWAY_URL}/v1/cloud/gemini",
                    json={"prompt": refined_prompt, "mode": "council"},
                )
                resp.raise_for_status()
                return (resp.json().get("result") or "").strip()

        try:
            claude_response, gemini_response = await asyncio.gather(
                _claude(), _gemini()
            )
            out["claude_response"] = claude_response
            out["gemini_response"] = gemini_response
            out["steps_completed"] = 2
        except Exception as e:
            out["steps_completed"] = 2
            out["error"] = str(e)
            return out

        user_msg = f"Response A:\n{out['claude_response']}\n\nResponse B:\n{out['gemini_response']}"

        try:
            async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
                r = await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": "qwen2.5-coder:7b",
                        "system": _OLLAMA_SYNTH_SYSTEM,
                        "prompt": user_msg,
                        "stream": False,
                    },
                )
                r.raise_for_status()
                data = r.json()
            out["synthesis"] = (data.get("response") or "").strip()
            out["steps_completed"] = 3
        except Exception as e:
            out["steps_completed"] = 3
            out["error"] = str(e)
            return out

        synthesis = out["synthesis"]

        try:
            async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
                resp = await client.post(
                    f"{GATEWAY_URL}/v1/cloud/perplexity",
                    json={
                        "prompt": (
                            f"Fact-check and supplement this answer with current research:\n{synthesis}"
                        ),
                        "mode": "council",
                    },
                )
                resp.raise_for_status()
            out["final_answer"] = (resp.json().get("result") or "").strip()
            out["steps_completed"] = 4
        except Exception as e:
            out["steps_completed"] = 4
            out["error"] = str(e)
            return out

        return out
