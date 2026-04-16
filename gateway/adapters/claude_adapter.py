import httpx
from jarvis_common.secrets import get_secret
from jarvis_common.logging_config import get_logger
from .base_adapter import BaseCloudAdapter

logger = get_logger("alpha_gateway")

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"


class ClaudeAdapter(BaseCloudAdapter):
    def provider_name(self) -> str:
        return "anthropic"

    async def call(self, payload: dict) -> dict:
        api_key = get_secret("ANTHROPIC_API_KEY")
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(CLAUDE_API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            logger.info("claude_adapter: status=%d", resp.status_code)

            usage = data.get("usage", {})
            self._emit_cost(
                model=payload.get("model", "unknown"),
                prompt_tokens=usage.get("input_tokens", 0),
                completion_tokens=usage.get("output_tokens", 0),
            )
            return data
