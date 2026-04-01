import httpx
import logging
from brain.config.secrets import get_secret
from .base_adapter import BaseCloudAdapter

logger = logging.getLogger("jarvis.gateway.gemini")

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class GeminiAdapter(BaseCloudAdapter):
    def provider_name(self) -> str:
        return "gemini"

    async def call(self, payload: dict) -> dict:
        api_key = get_secret("GEMINI_API_KEY")
        model = payload.pop("model", "gemini-2.0-flash")
        url = GEMINI_API_URL.format(model=model)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, params={"key": api_key})
            resp.raise_for_status()
            logger.info("gemini_adapter: status=%d model=%s", resp.status_code, model)
            return resp.json()
