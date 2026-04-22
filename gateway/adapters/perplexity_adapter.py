import httpx
from jarvis_common.secrets import get_secret
from jarvis_common.logging_config import get_logger
from .base_adapter import BaseCloudAdapter

logger = get_logger("alpha_gateway")

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"


class PerplexityAdapter(BaseCloudAdapter):
    def provider_name(self) -> str:
        return "perplexity"

    async def call(self, payload: dict, idempotency_key: str | None = None) -> dict:
        api_key = get_secret("PERPLEXITY_API_KEY")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        if "messages" in payload:
            has_system = any(m.get("role") == "system" for m in payload["messages"])
            if not has_system:
                payload = dict(payload)
                payload["messages"] = [
                    {
                        "role": "system",
                        "content": (
                            "You are JARVIS, a private AI assistant built by Kenneth Haas. "
                            "You are currently using your web search capability to answer. "
                            "Always respond as JARVIS. Never identify yourself as Perplexity or any other AI. "
                            "Be concise, direct, and intelligent."
                        ),
                    }
                ] + payload["messages"]
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(PERPLEXITY_API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            logger.info("perplexity_adapter: status=%d", resp.status_code)

            usage = data.get("usage", {})
            self._emit_cost(
                model=payload.get("model", "unknown"),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                idempotency_key=idempotency_key,
            )
            return data
