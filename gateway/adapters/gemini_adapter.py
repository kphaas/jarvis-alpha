import httpx
from jarvis_common.secrets import get_secret
from jarvis_common.logging_config import get_logger
from .base_adapter import BaseCloudAdapter

logger = get_logger("alpha_gateway")

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


def _content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return "" if content is None else str(content)


def _to_gemini_payload(payload: dict) -> tuple[str, dict]:
    """Translate common chat payloads into Gemini generateContent shape."""

    model = payload.get("model", "gemini-2.0-flash")
    if "contents" in payload:
        return model, {k: v for k, v in payload.items() if k != "model"}

    system_parts = []
    system_text = _content_to_text(payload.get("system")).strip()
    if system_text:
        system_parts.append({"text": system_text})

    contents = []
    for message in payload.get("messages", []):
        if not isinstance(message, dict):
            continue
        role = message.get("role", "user")
        text = _content_to_text(message.get("content")).strip()
        if not text:
            continue
        if role == "system":
            system_parts.append({"text": text})
            continue
        contents.append(
            {
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": text}],
            }
        )

    if not contents:
        prompt = _content_to_text(payload.get("prompt") or payload.get("input")).strip()
        if prompt:
            contents.append({"role": "user", "parts": [{"text": prompt}]})

    gemini_payload = {
        "contents": contents or [{"role": "user", "parts": [{"text": ""}]}]
    }
    if system_parts:
        gemini_payload["systemInstruction"] = {"parts": system_parts}

    generation_config = {}
    if payload.get("max_tokens") is not None:
        generation_config["maxOutputTokens"] = int(payload["max_tokens"])
    if payload.get("temperature") is not None:
        generation_config["temperature"] = float(payload["temperature"])
    if generation_config:
        gemini_payload["generationConfig"] = generation_config

    return model, gemini_payload


class GeminiAdapter(BaseCloudAdapter):
    def provider_name(self) -> str:
        return "gemini"

    async def call(self, payload: dict, idempotency_key: str | None = None) -> dict:
        api_key = get_secret("GEMINI_API_KEY")
        model, gemini_payload = _to_gemini_payload(payload)
        url = GEMINI_API_URL.format(model=model)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=gemini_payload, params={"key": api_key})
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                body = resp.text[:500]
                logger.error(
                    "gemini_adapter: status=%d model=%s body=%s",
                    resp.status_code,
                    model,
                    body,
                )
                raise RuntimeError(
                    f"Gemini API status={resp.status_code}: {body}"
                ) from e
            data = resp.json()
            logger.info("gemini_adapter: status=%d model=%s", resp.status_code, model)

            usage = data.get("usageMetadata", {})
            self._emit_cost(
                model=model,
                prompt_tokens=usage.get("promptTokenCount", 0),
                completion_tokens=usage.get("candidatesTokenCount", 0),
                total_tokens=usage.get("totalTokenCount", 0),
                idempotency_key=idempotency_key,
            )
            return data
