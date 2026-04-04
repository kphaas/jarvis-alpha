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
    async def call(self, payload: dict) -> dict: ...
