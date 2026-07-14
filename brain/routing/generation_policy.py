"""Provider-neutral controls for bounded chat generation."""

from __future__ import annotations

from dataclasses import dataclass


CHAT_GENERATION_POLICY_SCHEMA_VERSION = "chat_generation_policy.v1"


@dataclass(frozen=True)
class ChatGenerationPolicy:
    """Generation controls that provider adapters translate to native options."""

    deterministic: bool = False
    json_mode: bool = False

    def metadata(self) -> dict[str, object]:
        return {
            "chat_generation_policy_schema_version": (
                CHAT_GENERATION_POLICY_SCHEMA_VERSION
            ),
            "chat_generation_policy_deterministic": self.deterministic,
            "chat_generation_policy_structured_output": self.json_mode,
        }
