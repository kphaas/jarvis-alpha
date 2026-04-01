import httpx
import logging
from brain.config.secrets import get_secret
from .base_adapter import BaseCloudAdapter

logger = logging.getLogger("jarvis.gateway.perplexity")

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"


class PerplexityAdapter(BaseCloudAdapter):
    def provider_name(self) -> str:
        return "perplexity"

    async def call(self, payload: dict) -> dict:
        api_key = get_secret("PERPLEXITY_API_KEY")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(PERPLEXITY_API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            logger.info("perplexity_adapter: status=%d", resp.status_code)
            return resp.json()
