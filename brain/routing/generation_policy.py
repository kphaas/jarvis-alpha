"""Provider-neutral controls for bounded chat generation."""

from __future__ import annotations

from dataclasses import dataclass


CHAT_GENERATION_POLICY_SCHEMA_VERSION = "chat_generation_policy.v2"
_JSON_VALUE_TYPES = ("string", "number", "boolean", "object", "array", "null")


@dataclass(frozen=True)
class ChatGenerationPolicy:
    """Generation controls that provider adapters translate to native options."""

    deterministic: bool = False
    json_mode: bool = False
    exact_json_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.exact_json_keys and not self.json_mode:
            raise ValueError("exact JSON keys require JSON mode")
        if len(self.exact_json_keys) != len(set(self.exact_json_keys)):
            raise ValueError("exact JSON keys must be unique")

    def response_schema(self) -> dict[str, object] | None:
        if not self.exact_json_keys:
            return None
        return {
            "type": "object",
            "properties": {
                key: {"type": list(_JSON_VALUE_TYPES)} for key in self.exact_json_keys
            },
            "required": list(self.exact_json_keys),
            "additionalProperties": False,
        }

    def metadata(self) -> dict[str, object]:
        return {
            "chat_generation_policy_schema_version": (
                CHAT_GENERATION_POLICY_SCHEMA_VERSION
            ),
            "chat_generation_policy_deterministic": self.deterministic,
            "chat_generation_policy_structured_output": self.json_mode,
            "chat_generation_policy_exact_key_schema": bool(self.exact_json_keys),
            "chat_generation_policy_exact_key_count": len(self.exact_json_keys),
        }
