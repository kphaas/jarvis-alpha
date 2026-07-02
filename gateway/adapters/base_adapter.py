import httpx
from abc import ABC, abstractmethod

from jarvis_common.logging_config import get_logger
from gateway.resilience.transport import request_with_resilience

logger = get_logger("alpha_gateway")


class BaseCloudAdapter(ABC):
    """
    Gateway adapters are pure pass-through.
    Brain orchestrates — gateway adds API key and forwards.
    No business logic here.
    """

    timeout = httpx.Timeout(30.0)

    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    async def call(self, payload: dict, idempotency_key: str | None = None) -> dict: ...

    async def _request(
        self,
        *,
        operation: str,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        json_body: dict | None = None,
        data: dict[str, str] | None = None,
        payload_summary: dict[str, object] | None = None,
    ) -> httpx.Response:
        return await request_with_resilience(
            operation=operation,
            method=method,
            url=url,
            timeout=self.timeout,
            headers=headers,
            params=params,
            json_body=json_body,
            data=data,
            client_factory=httpx.AsyncClient,
            payload_summary=payload_summary,
            failure_detail=f"{self.provider_name()} egress",
        )

    def _emit_cost(
        self,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        session_type: str | None = None,
        intent: str | None = None,
        on_behalf_of: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        """Buffer a cost event. Never raises — fire-and-forget."""
        try:
            from gateway.cost_emitter import buffer_event

            buffer_event(
                provider=self.provider_name(),
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens or (prompt_tokens + completion_tokens),
                session_type=session_type,
                executor="gateway",
                intent=intent,
                on_behalf_of=on_behalf_of,
                idempotency_key=idempotency_key,
            )
        except Exception:
            pass
