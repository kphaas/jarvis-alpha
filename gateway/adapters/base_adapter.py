import httpx
from abc import ABC, abstractmethod

from jarvis_common.logging_config import get_logger

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
