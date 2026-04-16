import httpx
from jarvis_common.secrets import get_secret
from jarvis_common.logging_config import get_logger
from .base_adapter import BaseCloudAdapter

logger = get_logger("alpha_gateway")

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
            data = resp.json()
            logger.info("gemini_adapter: status=%d model=%s", resp.status_code, model)

            usage = data.get("usageMetadata", {})
            self._emit_cost(
                model=model,
                prompt_tokens=usage.get("promptTokenCount", 0),
                completion_tokens=usage.get("candidatesTokenCount", 0),
                total_tokens=usage.get("totalTokenCount", 0),
            )
            return data
